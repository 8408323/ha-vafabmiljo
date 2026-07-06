"""Tests for VafabMiljoCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from vafabmiljo.api import VafabMiljoAuthError, VafabMiljoError
from vafabmiljo.coordinator import VafabMiljoCoordinator


def _make_coordinator(client) -> VafabMiljoCoordinator:
    hass = HomeAssistant()
    entry = ConfigEntry(data={})
    return VafabMiljoCoordinator(hass, entry, client)


async def test_unauthenticated_skips_account_endpoints():
    client = AsyncMock()
    client.session_cookie = None
    client.list_next_pickup.return_value = [{"address": "Testgatan 1", "bins": []}]

    data = await _make_coordinator(client)._async_update_data()

    assert data.authenticated is False
    assert data.invoices is None
    assert data.sanitation is None
    client.get_invoices.assert_not_called()


async def test_authenticated_fetches_account_data():
    client = AsyncMock()
    client.session_cookie = "abc123"
    client.list_next_pickup.return_value = [{"address": "Testgatan 1", "bins": []}]
    client.get_invoices.return_value = {"data": [{"item": {"amount": 817}}]}
    client.get_sanitation.return_value = {"contracts": []}

    data = await _make_coordinator(client)._async_update_data()

    assert data.authenticated is True
    assert data.invoices == {"data": [{"item": {"amount": 817}}]}
    assert data.sanitation == {"contracts": []}


async def test_expired_session_triggers_reauth():
    client = AsyncMock()
    client.session_cookie = "abc123"
    client.list_next_pickup.return_value = []
    client.get_invoices.side_effect = VafabMiljoAuthError("expired")

    with pytest.raises(ConfigEntryAuthFailed):
        await _make_coordinator(client)._async_update_data()


async def test_authenticated_account_fetch_failure_raises_update_failed():
    client = AsyncMock()
    client.session_cookie = "abc123"
    client.list_next_pickup.return_value = []
    client.get_invoices.side_effect = VafabMiljoError("boom")

    with pytest.raises(UpdateFailed):
        await _make_coordinator(client)._async_update_data()


async def test_pickup_fetch_failure_raises_update_failed():
    client = AsyncMock()
    client.session_cookie = None
    client.list_next_pickup.side_effect = VafabMiljoError("boom")

    with pytest.raises(UpdateFailed):
        await _make_coordinator(client)._async_update_data()
