"""Tests for the VafabMiljö config flow.

VafabMiljoClient is constructed directly inside config_flow.py, so we patch the
class itself to hand back a pre-configured AsyncMock instead of hitting a real
API client constructor.
"""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntry, FlowResultType
from homeassistant.core import HomeAssistant
from vafabmiljo.api import VafabMiljoError
from vafabmiljo.config_flow import (
    VafabMiljoConfigFlow,
    VafabMiljoOptionsFlow,
    bankid_autostart_desktop_url,
    bankid_autostart_url,
)


def _make_flow(hass: HomeAssistant, client=None) -> VafabMiljoConfigFlow:
    flow = VafabMiljoConfigFlow()
    flow.hass = hass
    if client is not None:
        # Mimics whatever async_step_user would have set - needed when a test
        # starts mid-flow without going through that step first.
        flow._client = client
    return flow


async def _settle(task: asyncio.Task) -> None:
    # Waits for the background poll task without re-raising its exception
    # here - the flow itself is what's supposed to catch it via task.result().
    await asyncio.wait([task])


@pytest.fixture
def hass():
    h = HomeAssistant()
    h.data["test_session"] = object()  # never actually used - VafabMiljoClient is mocked out
    return h


@pytest.fixture
def mock_client(monkeypatch):
    client = AsyncMock()
    client.session_cookie = None
    monkeypatch.setattr("vafabmiljo.config_flow.VafabMiljoClient", lambda *a, **k: client)
    return client


async def test_user_step_no_matches_shows_error(hass, mock_client):
    mock_client.search_addresses.return_value = []
    flow = _make_flow(hass)

    result = await flow.async_step_user({"query": "nonexistent street"})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_matches"}


async def test_user_step_match_moves_to_address_select(hass, mock_client):
    # Filtering happens server-side (see api.search_addresses) - the mock here
    # returns exactly what the backend would for this query.
    mock_client.search_addresses.return_value = [
        {"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"},
    ]
    flow = _make_flow(hass)

    result = await flow.async_step_user({"query": "testgatan"})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "address"
    mock_client.search_addresses.assert_awaited_once_with("testgatan")
    assert len(flow._matches) == 1
    assert flow._matches[0]["plant_id"] == "p1"


def test_autostart_urls_escape_the_token():
    assert bankid_autostart_url("a b&c") == "https://app.bankid.com/?autostarttoken=a%20b%26c&redirect=null"
    assert bankid_autostart_desktop_url("a/b") == "bankid:///?autostarttoken=a%2Fb&redirect=null"


async def test_user_step_register_failure_shows_cannot_connect(hass, mock_client):
    mock_client.register.side_effect = VafabMiljoError("boom")
    flow = _make_flow(hass)

    result = await flow.async_step_user({"query": "anything"})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_entry_point_delegates_to_confirm(hass, mock_client):
    flow = _make_flow(hass, mock_client)
    entry = ConfigEntry(data={"device_uuid": "dev1", "device_bearer": "bearer1"})
    flow._reauth_entry = entry

    result = await flow.async_step_reauth({})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"


async def test_reconfigure_no_matches_shows_error(hass, mock_client):
    mock_client.search_addresses.return_value = []
    flow = _make_flow(hass)
    flow._reconfigure_entry = ConfigEntry(
        data={"device_uuid": "dev1", "device_bearer": "bearer1", "session_cookie": "old-cookie"}
    )

    result = await flow.async_step_reconfigure({"query": "nonexistent street"})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "no_matches"}


async def test_reconfigure_register_failure_shows_cannot_connect(hass, mock_client):
    mock_client.search_addresses.side_effect = VafabMiljoError("boom")
    flow = _make_flow(hass)
    flow._reconfigure_entry = ConfigEntry(data={"device_uuid": "dev1", "device_bearer": "bearer1"})

    result = await flow.async_step_reconfigure({"query": "anything"})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_match_moves_to_address_select(hass, mock_client):
    mock_client.search_addresses.return_value = [
        {"address": "Nygatan 5", "city": "Teststad", "plant_id": "p2"},
    ]
    flow = _make_flow(hass)
    flow._reconfigure_entry = ConfigEntry(data={"device_uuid": "dev1", "device_bearer": "bearer1"})

    result = await flow.async_step_reconfigure({"query": "nygatan"})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure_address"
    assert flow._matches[0]["plant_id"] == "p2"


async def test_reconfigure_address_updates_entry_and_reloads(hass, mock_client):
    entry = ConfigEntry(
        data={
            "device_uuid": "dev1",
            "device_bearer": "bearer1",
            "address": "Testgatan 1",
            "city": "Teststad",
            "plant_id": "p1",
        }
    )
    flow = _make_flow(hass, mock_client)
    flow._reconfigure_entry = entry
    flow._matches = [{"address": "Nygatan 5", "city": "Teststad", "plant_id": "p2"}]

    result = await flow.async_step_reconfigure_address({"plant_id": "p2"})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["address"] == "Nygatan 5"
    assert entry.data["plant_id"] == "p2"
    mock_client.set_address.assert_awaited_once_with("p2")


def test_async_get_options_flow_returns_options_flow():
    entry = ConfigEntry(data={})
    options_flow = VafabMiljoConfigFlow.async_get_options_flow(entry)
    assert isinstance(options_flow, VafabMiljoOptionsFlow)


async def test_options_flow_shows_current_default():
    entry = ConfigEntry(data={})
    flow = VafabMiljoOptionsFlow(entry)

    result = await flow.async_step_init()

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_saves_scan_interval():
    entry = ConfigEntry(data={})
    flow = VafabMiljoOptionsFlow(entry)

    result = await flow.async_step_init({"scan_interval": 15})

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {"scan_interval": 15}


def _decode_qr_markdown(markdown: str) -> str:
    encoded = markdown.split("base64,", 1)[1].rstrip(")")
    return base64.b64decode(encoded).decode()


async def test_address_step_creates_the_entry_without_a_login(hass, mock_client):
    flow = _make_flow(hass, mock_client)
    flow._device_uuid = "dev1"
    flow._device_bearer = "bearer1"
    flow._matches = [{"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"}]

    result = await flow.async_step_address({"plant_id": "p1"})

    # Keyed on the address (plant_id), not device_uuid, so two entries for the
    # same address collide but different addresses are free to coexist.
    assert flow._unique_id == "p1"
    mock_client.set_address.assert_awaited_once_with("p1")
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Testgatan 1, Teststad"
    assert result["data"] == {
        "device_uuid": "dev1",
        "device_bearer": "bearer1",
        "address": "Testgatan 1",
        "city": "Teststad",
        "plant_id": "p1",
    }


async def test_reauth_points_to_the_panel(hass, mock_client):
    flow = _make_flow(hass, mock_client)
    flow._reauth_entry = ConfigEntry(data={"device_uuid": "dev1", "device_bearer": "bearer1"})

    result = await flow.async_step_reauth({})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await flow.async_step_reauth_confirm({})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_use_panel"
