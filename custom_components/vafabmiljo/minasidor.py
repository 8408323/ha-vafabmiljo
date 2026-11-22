"""VafabMiljö Mina sidor (minasidor.vafabmiljo.se): the customer portal, source of the account data.

Since November 2026 the app's own API (api.py) answers "No customer data" for logged-in customers -
the VafabMiljö app itself can't log in either - while Mina sidor still shows invoices, fees and the
property. So account data comes from here; the app API is still used, without any login, for the
pickup schedule and the device's notification settings.

Login is BankID through Criipto (an OpenID Connect broker), driven headless:

1. GET /api//Authenticate/login-bankid?acrValue=qr|same redirects to Criipto's authorize page, whose
   `data-bootstrap` JSON holds the BankID order: the QR string (`initialQrCode`) or the same-device
   `launchUrl` (bankid:///?autostarttoken=...), and a `pollUrl`.
2. The pollUrl answers 202 while waiting (with the next animated `qrCode`), a 4xx text such as
   "Collect failed: startFailed" when the order died, and finally `{"targetUrl": ...}`.
3. Following targetUrl ends at Mina sidor's callback, which sets the `refreshToken` cookie (HttpOnly,
   valid 7 days, *not* extended by refreshing) and redirects to /signing-in?customerId=...&token=...
   with a 15-minute JWT access token.
4. Data calls only need `Authorization: Bearer <token>`; POST /api/Authenticate/refresh-token with the
   refreshToken cookie and {"accessToken": <last token, may be expired>} returns {"token": ...}.

A QR order and a same-device order run side by side, so the panel can show the QR and a "BankID on this
device" button at once; whichever is signed wins. A BankID QR order dies after about 30 seconds unless
scanned, so a dead order is restarted (the caller's own timeout bounds the whole login).
"""

from __future__ import annotations

import base64
import html
import json
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import segno
from aiohttp import ClientError, ClientSession

from .api import VafabMiljoAuthError, VafabMiljoError

MS_API = "https://minasidor.vafabmiljo.se/api/"
# Criipto's page is built for browsers; a browser user agent keeps it from treating us differently.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
REFRESH_COOKIE = "refreshToken"
REFRESH_LIFETIME = 7 * 24 * 3600  # used when the cookie carries no expiry of its own
_ACCESS_TOKEN_MARGIN = 60  # refresh this many seconds before the access token expires
# BankID's own "this order is gone, start a new one" hint codes; anything else is a real failure
_RESTARTABLE = {"startFailed", "expiredTransaction"}
_BOOTSTRAP = re.compile(r'data-bootstrap="([^"]+)"')


class MinaSidorLoginError(VafabMiljoError):
    """The BankID login failed for good; `hint` is BankID's hint code (userCancel, ...) or a short reason."""

    def __init__(self, hint: str) -> None:
        super().__init__(f"Mina sidor login failed: {hint}")
        self.hint = hint


@dataclass
class MinaSidorCredentials:
    """What a finished login leaves behind; refresh_cookie + refresh_expires are what's persisted."""

    refresh_cookie: str
    refresh_expires: float  # epoch seconds
    access_token: str
    customer_id: str | None


def jwt_expiry(token: str | None) -> float:
    """The `exp` of a JWT (epoch seconds), 0 for anything that isn't one."""
    if not token:
        return 0.0
    try:
        payload = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"])
    except (IndexError, ValueError, KeyError, TypeError):
        return 0.0


def qr_image(qr_string: str) -> str:
    """A BankID QR string as an SVG data URI (black on white, so it reads on dark themes too)."""
    return segno.make(qr_string, error="m").svg_data_uri(scale=6, border=4, dark="#000000", light="#ffffff")


def _cookie_expiry(morsel: Any) -> float:
    try:
        return parsedate_to_datetime(morsel["expires"]).timestamp()
    except (KeyError, TypeError, ValueError, IndexError):
        return time.time() + REFRESH_LIFETIME


class _Order:
    """One Criipto BankID order (a QR one or a same-device one)."""

    def __init__(self, acr: str) -> None:
        self.acr = acr  # "qr" or "same"
        self.poll_url = ""
        self.qr = ""  # the current animated QR string (QR orders)
        self.autostart_token: str | None = None  # same-device orders

    async def start(self, http: ClientSession) -> None:
        try:
            async with http.get(
                MS_API + "/Authenticate/login-bankid",
                params={"backUrl": "https://minasidor.vafabmiljo.se/", "acrValue": self.acr},
            ) as resp:
                page = await resp.text()
                base = str(resp.url)
        except ClientError as err:
            raise VafabMiljoError("Failed to reach Mina sidor") from err
        match = _BOOTSTRAP.search(page)
        if match is None:
            raise VafabMiljoError("Mina sidor's BankID page had no login data")
        try:
            rendition = json.loads(html.unescape(match.group(1)))["screen"]["rendition"]
            self.poll_url = urljoin(base, rendition["pollUrl"])
        except (ValueError, KeyError, TypeError) as err:
            raise VafabMiljoError("Mina sidor's BankID page had unexpected login data") from err
        self.qr = rendition.get("initialQrCode") or ""
        if launch := rendition.get("launchUrl"):
            self.autostart_token = (parse_qs(urlparse(launch).query).get("autostarttoken") or [None])[0]

    async def poll(self, http: ClientSession) -> str | None:
        """None while waiting; the targetUrl once signed. Raises MinaSidorLoginError(hint) when it died."""
        try:
            async with http.get(self.poll_url) as resp:
                if resp.status >= 400:
                    text = (await resp.text()).strip().strip('"')
                    raise MinaSidorLoginError(text.rsplit(":", 1)[-1].strip() or f"HTTP {resp.status}")
                body = await resp.json(content_type=None)
        except ClientError as err:
            raise VafabMiljoError("Failed to reach Criipto") from err
        if not isinstance(body, dict):
            return None
        if body.get("qrCode"):
            self.qr = body["qrCode"]
        return body.get("targetUrl") or None


class MinaSidorLogin:
    """One BankID login to Mina sidor, polled by the caller (panel or config flow) until done."""

    def __init__(self, http: ClientSession) -> None:
        # needs a session with a real cookie jar: Criipto keeps the order in its own cookies
        self._http = http
        self._qr = _Order("qr")
        self._same = _Order("same")
        self.credentials: MinaSidorCredentials | None = None

    @property
    def qr(self) -> str:
        return self._qr.qr

    @property
    def autostart_token(self) -> str | None:
        return self._same.autostart_token

    async def start(self) -> None:
        await self._qr.start(self._http)
        await self._same.start(self._http)

    async def poll(self) -> bool:
        """One round: True once logged in (credentials set), False while waiting."""
        for order in (self._qr, self._same):
            try:
                target = await order.poll(self._http)
            except MinaSidorLoginError as err:
                if err.hint not in _RESTARTABLE:
                    raise
                await order.start(self._http)  # unscanned order timed out: offer a fresh one
                continue
            if target:
                self.credentials = await self._finish(target)
                return True
        return False

    async def _finish(self, url: str) -> MinaSidorCredentials:
        refresh: tuple[str, float] | None = None
        for _hop in range(8):
            try:
                async with self._http.get(url, allow_redirects=False) as resp:
                    if (morsel := resp.cookies.get(REFRESH_COOKIE)) is not None and morsel.value:
                        refresh = (morsel.value, _cookie_expiry(morsel))
                    location = resp.headers.get("Location")
                    current = str(resp.url)
            except ClientError as err:
                raise VafabMiljoError("Failed to complete the Mina sidor login") from err
            if not location:
                break
            url = urljoin(current, location)
            query = parse_qs(urlparse(url).query)
            if "/signing-in" in urlparse(url).path and query.get("token"):
                if refresh is None:
                    raise MinaSidorLoginError("no_refresh_cookie")
                return MinaSidorCredentials(
                    refresh_cookie=refresh[0],
                    refresh_expires=refresh[1],
                    access_token=query["token"][0],
                    customer_id=(query.get("customerId") or [None])[0],
                )
        raise MinaSidorLoginError("no_token")


class MinaSidorClient:
    """Account data from Mina sidor, refreshing the 15-minute access token as needed."""

    def __init__(
        self, http: ClientSession, refresh_cookie: str, refresh_expires: float, access_token: str | None = None
    ) -> None:
        self._http = http  # no cookie jar needed: the refresh cookie is sent by hand
        self.refresh_cookie = refresh_cookie
        self.refresh_expires = refresh_expires
        self.access_token = access_token

    @property
    def expired(self) -> bool:
        return time.time() >= self.refresh_expires

    async def _refresh(self) -> None:
        if self.expired:
            raise VafabMiljoAuthError("The Mina sidor login has expired")
        try:
            async with self._http.post(
                MS_API + "Authenticate/refresh-token",
                json={"accessToken": self.access_token or ""},
                headers={"Cookie": f"{REFRESH_COOKIE}={self.refresh_cookie}", "User-Agent": USER_AGENT},
            ) as resp:
                if resp.status in (400, 401, 403):
                    raise VafabMiljoAuthError(f"Mina sidor refused the refresh (HTTP {resp.status})")
                if resp.status != 200:
                    raise VafabMiljoError(f"Mina sidor refresh returned HTTP {resp.status}")
                body = await resp.json(content_type=None)
        except ClientError as err:
            raise VafabMiljoError("Failed to reach Mina sidor") from err
        token = body.get("token") if isinstance(body, dict) else None
        if not token:
            raise VafabMiljoError("Mina sidor refresh returned no token")
        self.access_token = token

    async def _request(self, path: str, params: dict[str, Any] | None = None, *, raw: bool = False) -> Any:
        if jwt_expiry(self.access_token) - _ACCESS_TOKEN_MARGIN <= time.time():
            await self._refresh()
        for attempt in range(2):
            try:
                async with self._http.get(
                    MS_API + path,
                    params=params,
                    headers={"Authorization": f"Bearer {self.access_token}", "User-Agent": USER_AGENT},
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        await self._refresh()
                        continue
                    if resp.status in (401, 403):
                        raise VafabMiljoAuthError(f"{path} rejected the Mina sidor login")
                    if resp.status == 204:
                        return None
                    if resp.status != 200:
                        raise VafabMiljoError(f"{path} returned HTTP {resp.status}")
                    return await resp.read() if raw else await resp.json(content_type=None)
            except ClientError as err:
                raise VafabMiljoError(f"Failed to reach {path}") from err
        raise VafabMiljoAuthError(f"{path} rejected the Mina sidor login")  # pragma: no cover - loop always returns

    async def get_invoices(self) -> list[dict[str, Any]]:
        data = await self._request("EdpServices/invoices-for-customer")
        return data if isinstance(data, list) else []

    async def get_buildings(self) -> list[dict[str, Any]]:
        data = await self._request("EdpServices/buildings-by-customer")
        return data if isinstance(data, list) else []

    async def get_services(self, building_id: str) -> list[dict[str, Any]]:
        data = await self._request(
            "EdpServices/services-by-building", {"excludeAnnual": "false", "buildingId": building_id}
        )
        return data if isinstance(data, list) else []

    async def get_billing_info(self) -> dict[str, Any]:
        data = await self._request("EdpServices/billing-info")
        return data if isinstance(data, dict) else {}

    async def get_extra_orders(self, building_id: str) -> list[dict[str, Any]]:
        data = await self._request("EdpServices/extra-service-orders", {"buildingid": building_id})
        return data if isinstance(data, list) else []

    async def download_invoice(self, invoice_id: int | str) -> bytes:
        data = await self._request("EdpServices/invoice-pdf", {"invoiceId": str(invoice_id)}, raw=True)
        if not data:
            raise VafabMiljoError(f"Mina sidor has no PDF for invoice {invoice_id}")
        return data


# -- Mapping Mina sidor's shapes onto the ones the sensors and the invoice notifier already read ----------


def invoices_payload(invoices: list[dict[str, Any]]) -> dict[str, Any]:
    """Mina sidor's invoice list as the app's {"data": [{"item": {...}}]}, newest first."""
    rows = [i for i in invoices if isinstance(i, dict) and i.get("invoiceNr") is not None]
    rows.sort(key=lambda i: str(i.get("invoiceDate") or ""), reverse=True)
    return {
        "data": [
            {
                "item": {
                    "id": i["invoiceNr"],
                    # the only amount Mina sidor lists; equal to the invoiced amount until something is paid
                    "amount": i.get("renmainingAmount", i.get("remainingAmount")),
                    "invoiceDate": i.get("invoiceDate"),
                    "invoiceExpirationDate": i.get("invoiceExpirationDate"),
                    "paymentStatus": i.get("paymentStatus"),
                    "ocrNumber": i.get("ocrNr"),
                }
            }
            for i in rows
        ]
    }


def pick_building(buildings: list[dict[str, Any]], address: str) -> dict[str, Any] | None:
    """The customer's building at this entry's address (a customer can have several), else the first."""
    wanted = address.strip().lower()
    for building in buildings:
        if isinstance(building, dict) and str(building.get("address") or "").strip().lower().startswith(wanted):
            return building
    return next((b for b in buildings if isinstance(b, dict)), None)


def properties_payload(building: dict[str, Any] | None, billing: dict[str, Any] | None) -> dict[str, Any] | None:
    if building is None:
        return None
    payment = next(
        (
            b.get("paymentType")
            for b in (billing or {}).get("buildingBillingInfo") or []
            if isinstance(b, dict) and str(b.get("buildingId")) == str(building.get("id"))
        ),
        None,
    )
    return {
        "current": {
            "id": building.get("id"),
            "designation": building.get("designation"),
            "zip": building.get("zipcode"),
            "autogiro": (billing or {}).get("autogiroStatus"),
            "payment_type": payment,
        }
    }


def sanitation_payload(services: list[dict[str, Any]]) -> dict[str, Any]:
    """The building's services with a cost, as the app's {"contracts": [...]} for the fee sensors."""
    return {
        "contracts": [
            {
                "id": s["id"],
                "description": s.get("description") or s.get("name") or "",
                "type": s.get("serviceType"),
                "fee": {"price": s.get("cost"), "unit": "kr/år"},
            }
            for s in services
            if isinstance(s, dict) and s.get("id") is not None and not s.get("hide") and not s.get("hidePrice")
        ]
    }
