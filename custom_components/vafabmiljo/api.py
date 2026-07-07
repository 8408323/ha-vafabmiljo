"""Thin async client for the VafabMiljö app's backend.

None of this is documented publicly - it was reverse-engineered by capturing the
Android app's traffic. See the project README for the endpoint catalog.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    API_BASE,
    APP_VERSION,
    PENDING_POLL_INTERVAL,
    PENDING_POLL_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class VafabMiljoError(Exception):
    """Base error talking to the VafabMiljö backend."""


class VafabMiljoAuthError(VafabMiljoError):
    """The device credential or BankID session was rejected - needs re-auth."""


class VafabMiljoTimeoutError(VafabMiljoError):
    """A 202 'waiting' response never resolved within the poll budget."""


class VafabMiljoClient:
    """Talks to vafab.avfallsapp.se on behalf of one registered device."""

    def __init__(
        self,
        session: ClientSession,
        device_uuid: str,
        device_bearer: str | None = None,
        session_cookie: str | None = None,
    ) -> None:
        self._session = session
        self._device_uuid = device_uuid
        self._device_bearer = device_bearer
        self._session_cookie = session_cookie

    @property
    def device_bearer(self) -> str | None:
        return self._device_bearer

    @property
    def session_cookie(self) -> str | None:
        return self._session_cookie

    def _headers(self) -> dict[str, str]:
        headers = {
            "x-app-identifier": self._device_uuid,
            "x-app-version": APP_VERSION,
            "accept": "application/json",
        }
        if self._device_bearer:
            headers["authorization"] = f"Bearer {self._device_bearer}"
        if self._session_cookie:
            headers["cookie"] = f"vafab_session={self._session_cookie}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        allow_pending: bool = True,
    ) -> dict[str, Any]:
        url = f"{API_BASE}{path}"
        deadline = asyncio.get_event_loop().time() + PENDING_POLL_TIMEOUT
        while True:
            try:
                async with self._session.request(
                    method, url, headers=self._headers(), json=json, params=params
                ) as resp:
                    if resp.status == 401:
                        raise VafabMiljoAuthError(f"{path} rejected the current credentials")
                    if resp.status not in (200, 202):
                        raise VafabMiljoError(f"{path} returned HTTP {resp.status}")
                    data = await resp.json(content_type=None)
                    self._remember_session_cookie(resp)
            except ClientError as err:
                raise VafabMiljoError(f"Failed to reach {path}") from err

            # Right after BankID login the backend needs a moment to provision the
            # session; it answers 202 {"status": "waiting"} until it's ready.
            if allow_pending and isinstance(data, dict) and data.get("status") == "waiting":
                if asyncio.get_event_loop().time() >= deadline:
                    raise VafabMiljoTimeoutError(f"{path} kept returning 'waiting'")
                await asyncio.sleep(PENDING_POLL_INTERVAL)
                continue
            return data

    def _remember_session_cookie(self, resp) -> None:
        cookie = resp.cookies.get("vafab_session")
        if cookie is not None:
            self._session_cookie = cookie.value

    # -- Device registration (anonymous, once per install) -----------------

    async def register(self, model: str, os_version: str) -> None:
        """Register this device.

        The bearer credential is *not* issued by this call - it's a fixed
        app-wide value (DEVICE_AUTH_KEY, see const.py) sent as the
        Authorization header on this very first request; the backend
        associates it with this device_uuid from here on. The response's
        own "token" field is null in practice.
        """
        if not self._device_bearer:
            raise VafabMiljoError("device_bearer must be set before calling register()")
        await self._request(
            "POST",
            "/register",
            json={
                "identifier": self._device_uuid,
                "uuid": self._device_uuid,
                "platform": "android",
                "version": APP_VERSION,
                "os_version": os_version,
                "model": model,
                "test": False,
            },
            allow_pending=False,
        )

    # -- Address / pickup schedule (no login required) ----------------------

    async def search_addresses(self, query: str) -> list[dict[str, Any]]:
        """Search for addresses matching query, server-side.

        The endpoint requires an `address` query param - calling it with none
        makes the backend try to join against its entire nationwide plant_id
        dataset, which currently overflows MySQL's prepared-statement
        placeholder limit (SQLSTATE[HY000] 1390) and fails every time. This
        isn't specific to our client: the official app's own address search
        hits the same crash if you watch its raw traffic without a filter.
        """
        data = await self._request("GET", "/next-pickup/search", params={"address": query}, allow_pending=False)
        addresses: list[dict[str, Any]] = []
        for city, entries in data.items():
            for entry in entries:
                addresses.append({**entry, "city": city})
        return addresses

    async def set_address(self, plant_id: str) -> list[dict[str, Any]]:
        data = await self._request(
            "POST",
            "/next-pickup/set-status",
            json={"plant_id": plant_id, "address_enabled": True, "notification_enabled": True},
        )
        return data if isinstance(data, list) else []

    async def list_next_pickup(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/next-pickup/list")
        return data if isinstance(data, list) else []

    # -- BankID login ---------------------------------------------------------

    async def start_bankid_auth(self) -> dict[str, Any]:
        """Start a BankID login; returns the first QR (as base64 SVG) + autostart token."""
        return await self._request("POST", "/authenticate/auth", json={"loginType": "private"}, allow_pending=False)

    async def poll_bankid_status(self) -> dict[str, Any]:
        """One poll of the BankID login status. Caller drives the polling loop."""
        return await self._request("GET", "/authenticate/status", allow_pending=False)

    async def keep_alive(self) -> None:
        await self._request("GET", "/authenticate/keep-alive", allow_pending=False)

    # -- Authenticated account data -------------------------------------------

    async def get_properties(self) -> dict[str, Any]:
        return await self._request("GET", "/services/properties")

    async def get_customer(self) -> dict[str, Any]:
        """Fetch the account's customer record.

        Confirmed (not just theorized) to unstick a persistently-202 invoices
        endpoint: reproduced live against a real account where invoices had
        been stuck returning "waiting" for hours - one call to this endpoint
        and the very next invoices call immediately returned 200. The real
        app always calls this in parallel with properties/invoices/parameters
        right after login. The response includes personal data (name, SSN,
        contact info), so the coordinator calls this purely for the side
        effect and discards the result - never store or expose it as an
        entity.
        """
        return await self._request("GET", "/services/customer")

    async def get_invoices(self) -> dict[str, Any]:
        return await self._request("GET", "/services/invoices")

    async def get_parameters(self) -> dict[str, Any]:
        return await self._request("GET", "/services/parameters")

    async def get_sanitation(self) -> dict[str, Any]:
        return await self._request("GET", "/services/sanitation")

    async def get_orders(self) -> dict[str, Any]:
        return await self._request("GET", "/services/orders")

    async def get_complaints(self) -> dict[str, Any]:
        return await self._request("GET", "/services/complaints")

    async def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/settings", json=patch, allow_pending=False)
