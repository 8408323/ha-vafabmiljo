"""Tests for the Mina sidor login and client (minasidor.py)."""

from __future__ import annotations

import base64
import html
import json
import re
import time
from types import SimpleNamespace

import aioresponses.core as aioresponses_core
import pytest
from aiohttp import ClientConnectionError, ClientResponse, ClientSession, CookieJar
from aioresponses import aioresponses
from vafabmiljo import minasidor
from vafabmiljo.api import VafabMiljoAuthError, VafabMiljoError
from vafabmiljo.minasidor import (
    MS_API,
    MinaSidorClient,
    MinaSidorLogin,
    MinaSidorLoginError,
    _cookie_expiry,
    _Order,
    invoices_payload,
    jwt_expiry,
    pick_building,
    properties_payload,
    qr_image,
    sanitation_payload,
)
from yarl import URL

CRIIPTO = "https://vafab-mina-sidor.criipto.id"
START = re.compile(r"^https://minasidor\.vafabmiljo\.se/api//Authenticate/login-bankid\?.*$")
AUTHORIZE = f"{CRIIPTO}/oauth2/authorize?response_type=code"
QR_POLL = f"{CRIIPTO}/SEBankIdAsync/PollQr/?cs_v1=q1"
SAME_POLL = f"{CRIIPTO}/SEBankIdAsync/Poll/?cs_v1=s1"
COOKIE_EXPIRES = "Sun, 29 Nov 2026 13:28:07 GMT"


class _MockedClientResponse(ClientResponse):
    """aioresponses 0.7.9 builds its fake responses without the stream_writer that aiohttp >= 3.10 requires."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("stream_writer", SimpleNamespace(output_size=0))
        super().__init__(*args, **kwargs)


@pytest.fixture(autouse=True)
def _aioresponses_compat(monkeypatch):
    monkeypatch.setattr(aioresponses_core, "ClientResponse", _MockedClientResponse)


@pytest.fixture
async def http():
    async with ClientSession(cookie_jar=CookieJar()) as session:
        yield session


def _jwt(exp: float) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{payload}.sig"


def _page(rendition: dict | None) -> str:
    if rendition is None:
        return "<html><body>no bootstrap here</body></html>"
    boot = html.escape(json.dumps({"screen": {"screen": "x", "rendition": rendition}}), quote=True)
    return f'<html><body><div id="criipto_react_root" data-bootstrap="{boot}"></div></body></html>'


QR_RENDITION = {"pollUrl": QR_POLL, "initialQrCode": "bankid.a.0.b"}
SAME_RENDITION = {"pollUrl": "/SEBankIdAsync/Poll/?cs_v1=s1", "launchUrl": "bankid:///?autostarttoken=tok-1"}


def _mock_start(mocked, rendition: dict) -> None:
    # the start URL redirects to Criipto's authorize page, as live
    mocked.get(START, status=302, headers={"Location": AUTHORIZE})
    mocked.get(AUTHORIZE, body=_page(rendition))


# -- Helpers -------------------------------------------------------------------------------------------


def test_jwt_expiry():
    assert jwt_expiry(_jwt(1800000000)) == 1800000000.0
    assert jwt_expiry("not-a-jwt") == 0.0
    assert jwt_expiry("a.!!!.c") == 0.0
    assert jwt_expiry(None) == 0.0


def test_qr_image_is_an_svg_data_uri():
    assert qr_image("bankid.a.0.b").startswith("data:image/svg+xml")


def test_cookie_expiry():
    assert _cookie_expiry({"expires": COOKIE_EXPIRES}) == 1795958887.0
    before = time.time()
    assert _cookie_expiry({"expires": ""}) >= before + minasidor.REFRESH_LIFETIME - 1
    assert _cookie_expiry({}) >= before + minasidor.REFRESH_LIFETIME - 1


# -- One Criipto order -----------------------------------------------------------------------------------


async def test_qr_order_start(http):
    order = _Order("qr")
    with aioresponses() as mocked:
        _mock_start(mocked, QR_RENDITION)
        await order.start(http)
    assert order.qr == "bankid.a.0.b"
    assert order.poll_url == QR_POLL
    assert order.autostart_token is None


async def test_same_device_order_start_joins_the_poll_url_to_criipto(http):
    order = _Order("same")
    with aioresponses() as mocked:
        _mock_start(mocked, SAME_RENDITION)
        await order.start(http)
    assert order.poll_url == SAME_POLL
    assert order.autostart_token == "tok-1"
    assert order.qr == ""


async def test_order_start_errors(http):
    order = _Order("qr")
    with aioresponses() as mocked:
        mocked.get(START, body=_page(None))
        with pytest.raises(VafabMiljoError, match="no login data"):
            await order.start(http)
        mocked.get(START, body=_page({"initialQrCode": "x"}))  # no pollUrl
        with pytest.raises(VafabMiljoError, match="unexpected login data"):
            await order.start(http)
        mocked.get(START, exception=ClientConnectionError())
        with pytest.raises(VafabMiljoError, match="Failed to reach Mina sidor"):
            await order.start(http)


async def test_order_poll(http):
    order = _Order("qr")
    order.poll_url = QR_POLL
    with aioresponses() as mocked:
        mocked.get(QR_POLL, status=202, payload={"qrCode": "bankid.a.1.c"})
        assert await order.poll(http) is None
        assert order.qr == "bankid.a.1.c"

        mocked.get(QR_POLL, payload={"targetUrl": f"{CRIIPTO}/SEBankIdAsync/Done/?cs_v1=q1"})
        assert await order.poll(http) == f"{CRIIPTO}/SEBankIdAsync/Done/?cs_v1=q1"

        mocked.get(QR_POLL, status=202, body="[1, 2]")
        assert await order.poll(http) is None

        mocked.get(QR_POLL, status=400, body='"Collect failed: startFailed"')
        with pytest.raises(MinaSidorLoginError) as err:
            await order.poll(http)
        assert err.value.hint == "startFailed"

        mocked.get(QR_POLL, status=500, body="")
        with pytest.raises(MinaSidorLoginError) as err:
            await order.poll(http)
        assert err.value.hint == "HTTP 500"

        mocked.get(QR_POLL, exception=ClientConnectionError())
        with pytest.raises(VafabMiljoError, match="Failed to reach Criipto"):
            await order.poll(http)


# -- The whole login -------------------------------------------------------------------------------------


def _mock_finish(mocked, *, cookie: bool = True, token: bool = True, final_location: bool = True) -> str:
    done = f"{CRIIPTO}/SEBankIdAsync/Done/?cs_v1=q1"
    callback = "https://minasidor.vafabmiljo.se/api/authenticate/callback?code=c&state=s"
    mocked.get(done, status=302, headers={"Location": callback})
    headers = {}
    if cookie:
        headers["Set-Cookie"] = f"refreshToken=refresh-1; expires={COOKIE_EXPIRES}; path=/; secure; httponly"
    if final_location:
        query = "customerId=1&token=access-1" if token else "customerId=1"
        headers["Location"] = f"/signing-in?{query}"
    mocked.get(callback, status=302 if final_location else 200, headers=headers)
    return done


async def test_login_qr_signed(http):
    login = MinaSidorLogin(http)
    with aioresponses() as mocked:
        _mock_start(mocked, QR_RENDITION)
        _mock_start(mocked, SAME_RENDITION)
        await login.start()
        assert login.qr == "bankid.a.0.b"
        assert login.autostart_token == "tok-1"

        mocked.get(QR_POLL, status=202, payload={"qrCode": "bankid.a.1.c"})
        mocked.get(SAME_POLL, status=202, payload={})
        assert await login.poll() is False
        assert login.qr == "bankid.a.1.c"

        done = _mock_finish(mocked)
        mocked.get(QR_POLL, payload={"targetUrl": done})
        assert await login.poll() is True

    creds = login.credentials
    assert creds.refresh_cookie == "refresh-1"
    assert creds.refresh_expires == 1795958887.0
    assert creds.access_token == "access-1"
    assert creds.customer_id == "1"


async def test_login_restarts_an_order_that_timed_out(http):
    login = MinaSidorLogin(http)
    with aioresponses() as mocked:
        _mock_start(mocked, QR_RENDITION)
        _mock_start(mocked, SAME_RENDITION)
        await login.start()

        mocked.get(QR_POLL, status=400, body='"Collect failed: startFailed"')
        _mock_start(mocked, {**QR_RENDITION, "initialQrCode": "bankid.new.0.x"})
        mocked.get(SAME_POLL, status=202, payload={})
        assert await login.poll() is False
        assert login.qr == "bankid.new.0.x"

        # the same-device order signed this time
        done = _mock_finish(mocked)
        mocked.get(QR_POLL, status=202, payload={})
        mocked.get(SAME_POLL, payload={"targetUrl": done})
        assert await login.poll() is True


async def test_login_real_failure_is_raised(http):
    login = MinaSidorLogin(http)
    login._qr.poll_url = QR_POLL
    with aioresponses() as mocked:
        mocked.get(QR_POLL, status=400, body='"Collect failed: userCancel"')
        with pytest.raises(MinaSidorLoginError) as err:
            await login.poll()
    assert err.value.hint == "userCancel"


@pytest.mark.parametrize(
    ("kwargs", "hint"),
    [({"cookie": False}, "no_refresh_cookie"), ({"final_location": False}, "no_token"), ({"token": False}, None)],
)
async def test_finish_errors(http, kwargs, hint):
    login = MinaSidorLogin(http)
    with aioresponses() as mocked:
        done = _mock_finish(mocked, **kwargs)
        if hint is None:
            # /signing-in without a token is followed like any other hop; it then has nowhere to go
            mocked.get("https://minasidor.vafabmiljo.se/signing-in?customerId=1", status=200)
            hint = "no_token"
        with pytest.raises(MinaSidorLoginError) as err:
            await login._finish(done)
    assert err.value.hint == hint


async def test_finish_network_error(http):
    login = MinaSidorLogin(http)
    with aioresponses() as mocked:
        mocked.get(f"{CRIIPTO}/done", exception=ClientConnectionError())
        with pytest.raises(VafabMiljoError, match="complete the Mina sidor login"):
            await login._finish(f"{CRIIPTO}/done")


async def test_finish_gives_up_after_too_many_hops(http):
    login = MinaSidorLogin(http)
    with aioresponses() as mocked:
        mocked.get(f"{CRIIPTO}/loop", status=302, headers={"Location": f"{CRIIPTO}/loop"}, repeat=True)
        with pytest.raises(MinaSidorLoginError) as err:
            await login._finish(f"{CRIIPTO}/loop")
    assert err.value.hint == "no_token"


# -- The data client -------------------------------------------------------------------------------------

REFRESH = f"{MS_API}Authenticate/refresh-token"
INVOICES = f"{MS_API}EdpServices/invoices-for-customer"


def _client(http, *, token: str | None = None, expires_in: float = 3600) -> MinaSidorClient:
    return MinaSidorClient(http, "refresh-1", time.time() + expires_in, token)


async def test_client_refreshes_a_missing_token_and_sends_the_cookie(http):
    client = _client(http)
    fresh = _jwt(time.time() + 900)
    with aioresponses() as mocked:
        mocked.post(REFRESH, payload={"token": fresh})
        mocked.get(INVOICES, payload=[{"invoiceNr": 1}])
        assert await client.get_invoices() == [{"invoiceNr": 1}]
        (refresh_call,) = [c for k, c in mocked.requests.items() if k[0] == "POST"]
        assert refresh_call[0].kwargs["headers"]["Cookie"] == "refreshToken=refresh-1"
        assert refresh_call[0].kwargs["json"] == {"accessToken": ""}
        get_call = mocked.requests[("GET", URL(INVOICES))][0]
    assert client.access_token == fresh
    assert get_call.kwargs["headers"]["Authorization"] == f"Bearer {fresh}"
    assert not client.expired


async def test_client_keeps_a_valid_token(http):
    client = _client(http, token=_jwt(time.time() + 900))
    with aioresponses() as mocked:
        mocked.get(INVOICES, payload={"not": "a list"})
        assert await client.get_invoices() == []


async def test_client_refreshes_an_expiring_token_with_the_old_one(http):
    old = _jwt(time.time() + 10)
    client = _client(http, token=old)
    with aioresponses() as mocked:
        mocked.post(REFRESH, payload={"token": _jwt(time.time() + 900)})
        mocked.get(INVOICES, payload=[])
        await client.get_invoices()
        (refresh_call,) = [c for k, c in mocked.requests.items() if k[0] == "POST"]
        assert refresh_call[0].kwargs["json"] == {"accessToken": old}


async def test_an_expired_login_is_refused_without_a_request(http):
    client = _client(http, expires_in=-1)
    assert client.expired
    with aioresponses() as mocked:
        with pytest.raises(VafabMiljoAuthError):
            await client.get_invoices()
        assert mocked.requests == {}


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"status": 400}, VafabMiljoAuthError),
        ({"status": 401}, VafabMiljoAuthError),
        ({"status": 500}, VafabMiljoError),
        ({"payload": {"nothing": 1}}, VafabMiljoError),
        ({"payload": ["odd"]}, VafabMiljoError),
        ({"exception": ClientConnectionError()}, VafabMiljoError),
    ],
)
async def test_refresh_failures(http, response, error):
    client = _client(http)
    with aioresponses() as mocked:
        mocked.post(REFRESH, **response)
        with pytest.raises(error):
            await client.get_invoices()


async def test_a_401_is_retried_once_after_a_refresh(http):
    client = _client(http, token=_jwt(time.time() + 900))
    with aioresponses() as mocked:
        mocked.get(INVOICES, status=401)
        mocked.post(REFRESH, payload={"token": _jwt(time.time() + 900)})
        mocked.get(INVOICES, payload=[{"invoiceNr": 2}])
        assert await client.get_invoices() == [{"invoiceNr": 2}]

        mocked.get(INVOICES, status=401)
        mocked.post(REFRESH, payload={"token": _jwt(time.time() + 900)})
        mocked.get(INVOICES, status=401)
        with pytest.raises(VafabMiljoAuthError):
            await client.get_invoices()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"status": 403}, VafabMiljoAuthError),
        ({"status": 500}, VafabMiljoError),
        ({"exception": ClientConnectionError()}, VafabMiljoError),
    ],
)
async def test_request_failures(http, response, error):
    client = _client(http, token=_jwt(time.time() + 900))
    with aioresponses() as mocked:
        mocked.get(INVOICES, **response)
        with pytest.raises(error):
            await client.get_invoices()


async def test_getters(http):
    client = _client(http, token=_jwt(time.time() + 900))
    base = re.escape(MS_API)
    with aioresponses() as mocked:
        mocked.get(f"{MS_API}EdpServices/buildings-by-customer", payload=[{"id": "985520"}])
        assert await client.get_buildings() == [{"id": "985520"}]
        mocked.get(f"{MS_API}EdpServices/buildings-by-customer", status=204)
        assert await client.get_buildings() == []

        mocked.get(re.compile(rf"^{base}EdpServices/services-by-building\?.*buildingId=985520.*$"), payload=[{"id": 1}])
        assert await client.get_services("985520") == [{"id": 1}]
        mocked.get(re.compile(rf"^{base}EdpServices/services-by-building\?.*$"), payload={})
        assert await client.get_services("985520") == []

        mocked.get(f"{MS_API}EdpServices/billing-info", payload={"autogiroStatus": True})
        assert await client.get_billing_info() == {"autogiroStatus": True}
        mocked.get(f"{MS_API}EdpServices/billing-info", payload=[])
        assert await client.get_billing_info() == {}

        mocked.get(f"{MS_API}EdpServices/extra-service-orders?buildingid=985520", payload=[{"name": "Extra"}])
        assert await client.get_extra_orders("985520") == [{"name": "Extra"}]
        mocked.get(f"{MS_API}EdpServices/extra-service-orders?buildingid=985520", payload={})
        assert await client.get_extra_orders("985520") == []

        mocked.get(f"{MS_API}EdpServices/invoice-pdf?invoiceId=4476065", body=b"%PDF-1.4")
        assert await client.download_invoice(4476065) == b"%PDF-1.4"
        mocked.get(f"{MS_API}EdpServices/invoice-pdf?invoiceId=4476065", status=204)
        with pytest.raises(VafabMiljoError, match="no PDF"):
            await client.download_invoice("4476065")


# -- Mapping -----------------------------------------------------------------------------------------------


def test_invoices_payload():
    rows = [
        {"invoiceNr": 1, "invoiceDate": "2026-08-01T00:00:00", "renmainingAmount": 826.0, "ocrNr": "111"},
        {"invoiceNr": 2, "invoiceDate": "2026-11-01T00:00:00", "remainingAmount": 500.0, "paymentStatus": "Obetald"},
        {"invoiceDate": "2026-12-01T00:00:00"},  # no invoiceNr
        "junk",
    ]
    payload = invoices_payload(rows)
    items = [r["item"] for r in payload["data"]]
    assert [i["id"] for i in items] == [2, 1]
    assert items[0]["amount"] == 500.0
    assert items[0]["paymentStatus"] == "Obetald"
    assert items[1] == {
        "id": 1,
        "amount": 826.0,
        "invoiceDate": "2026-08-01T00:00:00",
        "invoiceExpirationDate": None,
        "paymentStatus": None,
        "ocrNumber": "111",
    }


def test_pick_building():
    buildings = [{"id": "1", "address": "Annangatan 9"}, "junk", {"id": "2", "address": "Testgatan 1, Teststad"}]
    assert pick_building(buildings, " Testgatan 1 ")["id"] == "2"
    assert pick_building(buildings, "Elsewhere 3")["id"] == "1"
    assert pick_building(["junk"], "x") is None
    assert pick_building([], "x") is None


def test_properties_payload():
    building = {"id": "985520", "designation": "Test 2:7", "zipcode": "12345"}
    billing = {
        "autogiroStatus": True,
        "buildingBillingInfo": [
            "junk",
            {"buildingId": "1", "paymentType": "X"},
            {"buildingId": 985520, "paymentType": "AGBG"},
        ],
    }
    assert properties_payload(None, billing) is None
    assert properties_payload(building, billing) == {
        "current": {"id": "985520", "designation": "Test 2:7", "zip": "12345", "autogiro": True, "payment_type": "AGBG"}
    }
    current = properties_payload(building, None)["current"]
    assert current["autogiro"] is None and current["payment_type"] is None
    assert properties_payload(building, {"buildingBillingInfo": None})["current"]["payment_type"] is None


def test_sanitation_payload():
    services = [
        {"id": 435588, "description": "Fast grundavgift, småhus", "serviceType": "RH Service", "cost": 1916.62},
        {"id": 2, "name": "Kärl", "cost": 1.0},
        {"id": 3, "description": "Hidden", "hide": True},
        {"id": 4, "description": "No price", "hidePrice": True},
        {"description": "No id"},
        "junk",
    ]
    contracts = sanitation_payload(services)["contracts"]
    assert contracts == [
        {
            "id": 435588,
            "description": "Fast grundavgift, småhus",
            "type": "RH Service",
            "fee": {"price": 1916.62, "unit": "kr/år"},
        },
        {"id": 2, "description": "Kärl", "type": None, "fee": {"price": 1.0, "unit": "kr/år"}},
    ]
    assert sanitation_payload([{"id": 5}])["contracts"][0]["description"] == ""
