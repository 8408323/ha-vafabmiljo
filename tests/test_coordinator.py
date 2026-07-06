"""Tests for VafabMiljoCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from vafabmiljo.api import VafabMiljoAuthError, VafabMiljoError
from vafabmiljo.coordinator import VafabMiljoCoordinator, VafabMiljoData


def _make_coordinator(client) -> VafabMiljoCoordinator:
    hass = HomeAssistant()
    entry = ConfigEntry(data={})
    return VafabMiljoCoordinator(hass, entry, client)


def _authenticated_client(**overrides) -> AsyncMock:
    client = AsyncMock()
    client.session_cookie = "abc123"
    client.list_next_pickup.return_value = []
    client.get_invoices.return_value = {"data": []}
    client.get_sanitation.return_value = {"contracts": []}
    client.get_properties.return_value = {"current": {"id": 1}}
    client.get_parameters.return_value = {"ordersAvailable": False, "complaintsAvailable": False}
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


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
    client = _authenticated_client(
        get_invoices=AsyncMock(return_value={"data": [{"item": {"amount": 817}}]}),
    )

    data = await _make_coordinator(client)._async_update_data()

    assert data.authenticated is True
    assert data.invoices == {"data": [{"item": {"amount": 817}}]}
    assert data.sanitation == {"contracts": []}
    assert data.properties == {"current": {"id": 1}}
    client.get_orders.assert_not_called()
    client.get_complaints.assert_not_called()


async def test_orders_and_complaints_fetched_only_when_available():
    client = _authenticated_client(
        get_parameters=AsyncMock(return_value={"ordersAvailable": True, "complaintsAvailable": True}),
        get_orders=AsyncMock(return_value={"1": {"10": [{"id": 719, "title": "Budning"}]}}),
        get_complaints=AsyncMock(return_value={"1": {"10": [{"description": "Utebliven hämtning"}]}}),
    )

    data = await _make_coordinator(client)._async_update_data()

    assert data.available_orders == [{"id": 719, "title": "Budning"}]
    assert data.available_complaints == [{"description": "Utebliven hämtning"}]


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


def test_available_orders_and_complaints_empty_without_properties():
    data = VafabMiljoData(orders={"1": {"10": [{"id": 1}]}})
    assert data.current_property_id is None
    assert data.available_orders == []
    assert data.available_complaints == []


def test_available_orders_flattens_across_contracts():
    data = VafabMiljoData(
        properties={"current": {"id": 1}},
        orders={"1": {"10": [{"id": 1}], "20": [{"id": 2}]}},
    )
    assert data.current_property_id == 1
    assert {o["id"] for o in data.available_orders} == {1, 2}
