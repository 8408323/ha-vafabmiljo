"""Tests for the VafabMiljö API client."""

from __future__ import annotations

import pytest
from aiohttp import ClientConnectionError, ClientSession
from aioresponses import aioresponses
from vafabmiljo.api import (
    API_BASE,
    VafabMiljoAuthError,
    VafabMiljoClient,
    VafabMiljoError,
    VafabMiljoTimeoutError,
)
from vafabmiljo.const import APP_VERSION
from yarl import URL


@pytest.fixture
async def client():
    async with ClientSession() as session:
        yield VafabMiljoClient(session, device_uuid="abc123", device_bearer="bearer-token-value")


async def test_register_requires_bearer_first():
    async with ClientSession() as session:
        bare_client = VafabMiljoClient(session, device_uuid="abc123")
        with pytest.raises(VafabMiljoError):
            await bare_client.register(model="Pixel", os_version="14")


async def test_register_sends_expected_body(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.post(f"{API_BASE}/register", payload={"id": 1, "token": None})
        await client.register(model="Pixel", os_version="14")
        request = mocked.requests[("POST", URL(f"{API_BASE}/register"))][0]
        assert request.kwargs["json"] == {
            "identifier": "abc123",
            "uuid": "abc123",
            "platform": "android",
            "version": APP_VERSION,
            "os_version": "14",
            "model": "Pixel",
            "test": False,
        }
        assert request.kwargs["headers"]["authorization"] == "Bearer bearer-token-value"


async def test_401_raises_auth_error(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.get(f"{API_BASE}/services/invoices", status=401)
        with pytest.raises(VafabMiljoAuthError):
            await client.get_invoices()


async def test_202_waiting_is_retried_until_200(client: VafabMiljoClient, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("vafabmiljo.api.asyncio.sleep", no_sleep)
    with aioresponses() as mocked:
        mocked.get(f"{API_BASE}/services/invoices", status=202, payload={"status": "waiting"})
        mocked.get(f"{API_BASE}/services/invoices", status=202, payload={"status": "waiting"})
        mocked.get(f"{API_BASE}/services/invoices", status=200, payload={"data": []})
        result = await client.get_invoices()
        assert result == {"data": []}


async def test_202_waiting_forever_times_out(client: VafabMiljoClient, monkeypatch):
    async def no_sleep(_seconds):
        return None

    times = iter([0, 5, 10, 40])  # exceeds PENDING_POLL_TIMEOUT on the last check
    monkeypatch.setattr("vafabmiljo.api.asyncio.sleep", no_sleep)
    monkeypatch.setattr(
        "vafabmiljo.api.asyncio.get_event_loop", lambda: type("L", (), {"time": lambda self=None: next(times)})()
    )
    with aioresponses() as mocked:
        mocked.get(f"{API_BASE}/services/invoices", status=202, payload={"status": "waiting"}, repeat=True)
        with pytest.raises(VafabMiljoTimeoutError):
            await client.get_invoices()


async def test_session_cookie_is_remembered(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.post(
            f"{API_BASE}/authenticate/auth",
            payload={"token": "auto123", "customer": False, "qr": "<svg/>"},
            headers={"Set-Cookie": "vafab_session=abc123; Path=/; HttpOnly"},
        )
        await client.start_bankid_auth()
        assert client.session_cookie == "abc123"


async def test_search_addresses_flattens_city_grouping(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.get(
            f"{API_BASE}/next-pickup/search?address=Testgatan",
            payload={
                "Arboga": [{"address": "Österby 257", "plant_id": "p1"}],
                "Teststad": [{"address": "Testgatan 1", "plant_id": "p2"}],
            },
        )
        addresses = await client.search_addresses("Testgatan")
        assert {"address": "Österby 257", "plant_id": "p1", "city": "Arboga"} in addresses
        assert {"address": "Testgatan 1", "plant_id": "p2", "city": "Teststad"} in addresses


async def test_device_bearer_property(client: VafabMiljoClient):
    assert client.device_bearer == "bearer-token-value"


async def test_session_cookie_sent_once_set(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.post(
            f"{API_BASE}/authenticate/auth",
            payload={"token": "auto123", "customer": False, "qr": "<svg/>"},
            headers={"Set-Cookie": "vafab_session=first; Path=/; HttpOnly"},
        )
        await client.start_bankid_auth()

        mocked.get(f"{API_BASE}/authenticate/keep-alive", payload={})
        await client.keep_alive()
        request = mocked.requests[("GET", URL(f"{API_BASE}/authenticate/keep-alive"))][0]
        assert request.kwargs["headers"]["cookie"] == "vafab_session=first"


async def test_unexpected_status_raises_vafabmiljo_error(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.get(f"{API_BASE}/services/invoices", status=500)
        with pytest.raises(VafabMiljoError):
            await client.get_invoices()


async def test_poll_bankid_status_returns_payload(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.get(
            f"{API_BASE}/authenticate/status", payload={"status": "authenticated successfully", "qr": "", "hint": ""}
        )
        result = await client.poll_bankid_status()
        assert result["status"] == "authenticated successfully"


async def test_get_sanitation(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.get(f"{API_BASE}/services/sanitation", payload={"contracts": []})
        assert await client.get_sanitation() == {"contracts": []}


async def test_update_settings_sends_patch(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.post(f"{API_BASE}/settings", payload={"garbage": False})
        result = await client.update_settings({"garbage": False})
        request = mocked.requests[("POST", URL(f"{API_BASE}/settings"))][0]
        assert request.kwargs["json"] == {"garbage": False}
        assert result == {"garbage": False}


async def test_no_set_cookie_leaves_session_cookie_unset(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.get(f"{API_BASE}/services/invoices", payload={"data": []})
        await client.get_invoices()
        assert client.session_cookie is None


async def test_connection_error_raises_vafabmiljo_error(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.get(f"{API_BASE}/services/invoices", exception=ClientConnectionError())
        with pytest.raises(VafabMiljoError):
            await client.get_invoices()


async def test_list_next_pickup_ignores_non_list_response(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.get(f"{API_BASE}/next-pickup/list", payload={"unexpected": "shape"})
        assert await client.list_next_pickup() == []


@pytest.mark.parametrize(
    ("method_name", "path"),
    [
        ("get_properties", "/services/properties"),
        ("get_parameters", "/services/parameters"),
        ("get_orders", "/services/orders"),
        ("get_complaints", "/services/complaints"),
        ("get_customer", "/services/customer"),
    ],
)
async def test_simple_get_endpoints(client: VafabMiljoClient, method_name: str, path: str):
    with aioresponses() as mocked:
        mocked.get(f"{API_BASE}{path}", payload={"ok": True})
        result = await getattr(client, method_name)()
        assert result == {"ok": True}


async def test_keep_alive(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.get(f"{API_BASE}/authenticate/keep-alive", payload={})
        await client.keep_alive()  # just needs to not raise


async def test_set_address_sends_expected_body(client: VafabMiljoClient):
    with aioresponses() as mocked:
        mocked.post(f"{API_BASE}/next-pickup/set-status", payload=[{"address": "Testgatan 1"}])
        await client.set_address("plant-id-value")
        request = mocked.requests[("POST", URL(f"{API_BASE}/next-pickup/set-status"))][0]
        assert request.kwargs["json"] == {
            "plant_id": "plant-id-value",
            "address_enabled": True,
            "notification_enabled": True,
        }
