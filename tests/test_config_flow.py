"""Tests for the VafabMiljö config flow.

VafabMiljoClient is constructed directly inside config_flow.py, so we patch the
class itself to hand back a pre-configured AsyncMock instead of hitting a real
API client constructor.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntry, FlowResultType
from homeassistant.core import HomeAssistant
from vafabmiljo.api import VafabMiljoAuthError, VafabMiljoError
from vafabmiljo.config_flow import VafabMiljoConfigFlow, _is_authenticated, _qr_markdown


def _make_flow(hass: HomeAssistant, client=None) -> VafabMiljoConfigFlow:
    flow = VafabMiljoConfigFlow()
    flow.hass = hass
    if client is not None:
        # Mimics whatever async_step_user would have set - needed when a test
        # starts mid-flow without going through that step first.
        flow._client = client
    return flow


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
    mock_client.fetch_all_addresses.return_value = [{"address": "Storgatan 1", "city": "Teststad", "plant_id": "p1"}]
    flow = _make_flow(hass)

    result = await flow.async_step_user({"query": "nonexistent street"})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_matches"}


async def test_user_step_match_moves_to_address_select(hass, mock_client):
    mock_client.fetch_all_addresses.return_value = [
        {"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"},
        {"address": "Storgatan 1", "city": "Teststad", "plant_id": "p2"},
    ]
    flow = _make_flow(hass)

    result = await flow.async_step_user({"query": "testgatan"})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "address"
    assert len(flow._matches) == 1
    assert flow._matches[0]["plant_id"] == "p1"


async def test_address_step_selects_and_moves_to_bankid_start(hass, mock_client):
    flow = _make_flow(hass)
    flow._matches = [{"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"}]

    result = await flow.async_step_address({"plant_id": "p1"})

    assert flow._selected["address"] == "Testgatan 1"
    assert result["step_id"] == "bankid_start"


async def test_bankid_start_skip_creates_entry_directly(hass, mock_client):
    flow = _make_flow(hass, mock_client)
    flow._selected = {"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"}
    flow._device_uuid = "dev1"
    flow._device_bearer = "bearer1"

    result = await flow.async_step_bankid_start({"enable_bankid": False})

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["address"] == "Testgatan 1"
    mock_client.set_address.assert_awaited_once_with("p1")
    mock_client.start_bankid_auth.assert_not_called()


async def test_bankid_start_enabled_moves_to_wait(hass, mock_client):
    mock_client.start_bankid_auth.return_value = {"qr": "<svg>first</svg>"}
    mock_client.poll_bankid_status.return_value = {
        "status": {"message": {"hintCode": "outstandingTransaction"}},
        "qr": "<svg>poll</svg>",
        "hint": "outstandingTransaction",
    }
    flow = _make_flow(hass, mock_client)
    flow._selected = {"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"}

    result = await flow.async_step_bankid_start({"enable_bankid": True})

    assert result["type"] == FlowResultType.SHOW_PROGRESS
    assert result["step_id"] == "bankid_wait"
    qr_markdown = result["description_placeholders"]["qr_code"]
    encoded = qr_markdown.split("base64,", 1)[1].rstrip(")")
    assert "poll" in base64.b64decode(encoded).decode()


async def test_bankid_wait_completes_when_authenticated(hass, mock_client):
    mock_client.poll_bankid_status.return_value = {"status": "authenticated successfully", "qr": "", "hint": ""}
    flow = _make_flow(hass, mock_client)

    result = await flow.async_step_bankid_wait()

    assert result == {"type": FlowResultType.SHOW_PROGRESS_DONE, "next_step_id": "finish"}


async def test_finish_creates_entry_with_all_data(hass, mock_client):
    mock_client.session_cookie = "cookie123"
    flow = _make_flow(hass, mock_client)
    flow._device_uuid = "dev1"
    flow._device_bearer = "bearer1"
    flow._selected = {"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"}

    result = await flow.async_step_finish()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Testgatan 1, Teststad"
    assert result["data"]["session_cookie"] == "cookie123"
    assert result["data"]["device_uuid"] == "dev1"


async def test_reauth_flow_updates_session_cookie(hass, mock_client):
    mock_client.start_bankid_auth.return_value = {"qr": "<svg/>"}
    mock_client.poll_bankid_status.side_effect = [
        {
            "status": {"message": {"hintCode": "outstandingTransaction"}},
            "qr": "<svg>pending</svg>",
            "hint": "outstandingTransaction",
        },
        {"status": "authenticated successfully", "qr": "", "hint": ""},
    ]
    mock_client.session_cookie = "new-cookie"

    flow = _make_flow(hass)
    entry = ConfigEntry(data={"device_uuid": "dev1", "device_bearer": "bearer1", "session_cookie": "old-cookie"})
    flow._reauth_entry = entry

    # First entry into reauth_confirm starts BankID and does the first (pending) poll.
    confirm_result = await flow.async_step_reauth_confirm({})
    assert confirm_result["type"] == FlowResultType.SHOW_PROGRESS
    assert flow._client is mock_client

    # Frontend re-enters the wait step; second poll comes back authenticated.
    wait_result = await flow.async_step_reauth_bankid_wait()
    assert wait_result == {"type": FlowResultType.SHOW_PROGRESS_DONE, "next_step_id": "reauth_finish"}

    finish_result = await flow.async_step_reauth_finish()
    assert finish_result["type"] == FlowResultType.ABORT
    assert finish_result["reason"] == "reauth_successful"
    assert entry.data["session_cookie"] == "new-cookie"


async def test_user_step_register_failure_shows_cannot_connect(hass, mock_client):
    mock_client.register.side_effect = VafabMiljoError("boom")
    flow = _make_flow(hass)

    result = await flow.async_step_user({"query": "anything"})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_bankid_wait_error_falls_back_to_failed_step(hass, mock_client):
    mock_client.poll_bankid_status.side_effect = VafabMiljoError("boom")
    flow = _make_flow(hass, mock_client)

    result = await flow.async_step_bankid_wait()
    assert result == {"type": FlowResultType.SHOW_PROGRESS_DONE, "next_step_id": "bankid_failed"}

    failed_result = await flow.async_step_bankid_failed()
    assert failed_result["type"] == FlowResultType.FORM
    assert failed_result["step_id"] == "bankid_start"
    assert failed_result["errors"] == {"base": "cannot_connect"}


async def test_reauth_entry_point_delegates_to_confirm(hass, mock_client):
    flow = _make_flow(hass, mock_client)
    entry = ConfigEntry(data={"device_uuid": "dev1", "device_bearer": "bearer1"})
    flow._reauth_entry = entry

    result = await flow.async_step_reauth({})

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"


async def test_reauth_bankid_wait_auth_error_reprompts(hass, mock_client):
    mock_client.poll_bankid_status.side_effect = VafabMiljoAuthError("still rejected")
    flow = _make_flow(hass, mock_client)

    result = await flow.async_step_reauth_bankid_wait()

    assert result == {"type": FlowResultType.SHOW_PROGRESS_DONE, "next_step_id": "reauth_confirm"}


def test_is_authenticated_handles_both_shapes():
    assert _is_authenticated({"status": "authenticated successfully"}) is True
    assert _is_authenticated({"status": {"code": "BANKID_MSG"}}) is False


def test_qr_markdown_produces_data_uri():
    markdown = _qr_markdown("<svg>x</svg>")
    assert markdown.startswith("![BankID QR code](data:image/svg+xml;base64,")
