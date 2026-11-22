"""Tests for VafabMiljoCoordinator."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from vafabmiljo.api import VafabMiljoAuthError, VafabMiljoError
from vafabmiljo.const import EVENT_LOGIN_EXPIRING
from vafabmiljo.coordinator import VafabMiljoCoordinator, VafabMiljoData, _order_item

_BANKID_ISSUE = ("vafabmiljo", "bankid_expired_test_entry")
_EXPIRING_ISSUE = ("vafabmiljo", "login_expiring_test_entry")

_INVOICES = [
    {
        "archived": True,
        "invoiceDate": "2026-08-01T00:00:00",
        "invoiceExpirationDate": "2026-08-31T00:00:00",
        "invoiceNr": 4382143,
        "ocrNr": "111",
        "paymentStatus": "Helt betald",
        "renmainingAmount": 826.0,
    },
    {
        "archived": True,
        "invoiceDate": "2026-11-01T00:00:00",
        "invoiceExpirationDate": "2026-12-01T00:00:00",
        "invoiceNr": 4476065,
        "ocrNr": "222",
        "paymentStatus": "Obetald",
        "renmainingAmount": 826.0,
    },
]
_BUILDINGS = [
    {"id": "1", "address": "Annangatan 9", "designation": "Annan 1:1", "zipcode": "11111", "city": "Teststad"},
    {"id": "985520", "address": "Testgatan 1", "designation": "Test 2:7", "zipcode": "12345", "city": "Teststad"},
]
_SERVICES = [
    {
        "id": 435588,
        "name": "Grundavgift",
        "description": "Fast grundavgift, småhus",
        "serviceType": "RH Service",
        "cost": 1916.62,
        "hide": False,
        "hidePrice": False,
    }
]
_BILLING = {"autogiroStatus": True, "buildingBillingInfo": [{"buildingId": "985520", "paymentType": "AGBG"}]}


def _app_client() -> AsyncMock:
    client = AsyncMock()
    client.list_next_pickup.return_value = []
    client.get_settings.return_value = {"garbage": True}
    return client


def _minasidor(*, expires_in: float = 7 * 24 * 3600, **overrides) -> AsyncMock:
    ms = AsyncMock()
    ms.refresh_expires = time.time() + expires_in
    ms.get_invoices.return_value = _INVOICES
    ms.get_buildings.return_value = _BUILDINGS
    ms.get_services.return_value = _SERVICES
    ms.get_billing_info.return_value = _BILLING
    ms.get_extra_orders.return_value = []
    for key, value in overrides.items():
        setattr(ms, key, value)
    return ms


def _make_coordinator(client=None, minasidor=None, data=None) -> VafabMiljoCoordinator:
    hass = HomeAssistant()
    entry = ConfigEntry(data=data if data is not None else {"address": "Testgatan 1"})
    return VafabMiljoCoordinator(hass, entry, client or _app_client(), minasidor)


# -- Without a Mina sidor login ----------------------------------------------------------------------


async def test_unauthenticated_fetches_pickups_and_settings_only():
    client = _app_client()
    client.list_next_pickup.return_value = [{"address": "Testgatan 1", "bins": []}]
    coordinator = _make_coordinator(client)

    data = await coordinator._async_update_data()

    assert data.authenticated is False
    assert data.pickups == [{"address": "Testgatan 1", "bins": []}]
    assert data.settings == {"garbage": True}
    assert data.invoices is None
    assert coordinator.hass.data.get("_issues", {}) == {}


async def test_an_old_app_login_asks_for_the_mina_sidor_login():
    coordinator = _make_coordinator(data={"address": "Testgatan 1", "session_cookie": "old"})

    data = await coordinator._async_update_data()

    assert data.authenticated is False
    issue = coordinator.hass.data["_issues"][_BANKID_ISSUE]
    assert issue["severity"] == "error"
    assert issue["learn_more_url"] == "homeassistant://vafabmiljo"
    assert issue["translation_placeholders"] == {"address": "Testgatan 1, Teststad"}


async def test_pickup_fetch_failure_raises_update_failed():
    client = _app_client()
    client.list_next_pickup.side_effect = VafabMiljoError("boom")

    with pytest.raises(UpdateFailed):
        await _make_coordinator(client)._async_update_data()


async def test_failing_or_odd_settings_are_ignored(caplog):
    client = _app_client()
    client.get_settings.side_effect = VafabMiljoError("boom")
    assert (await _make_coordinator(client)._async_update_data()).settings is None
    assert "Failed to fetch settings" in caplog.text

    client.get_settings.side_effect = None
    client.get_settings.return_value = ["not", "a", "dict"]
    assert (await _make_coordinator(client)._async_update_data()).settings is None


async def test_a_settings_auth_error_does_not_break_the_refresh():
    # the app API is used without login; its auth errors say nothing about the Mina sidor login
    client = _app_client()
    client.get_settings.side_effect = VafabMiljoAuthError("no")
    coordinator = _make_coordinator(client, _minasidor())

    data = await coordinator._async_update_data()

    assert data.settings is None
    assert data.session_expired is False


# -- With a Mina sidor login -------------------------------------------------------------------------


async def test_account_data_comes_from_mina_sidor():
    ms = _minasidor(get_extra_orders=AsyncMock(return_value=[{"name": "Extra tömning", "id": 7}]))
    coordinator = _make_coordinator(minasidor=ms)

    data = await coordinator._async_update_data()

    assert data.authenticated is True
    assert data.session_expired is False
    assert data.settings == {"garbage": True}
    assert data.login_expires == ms.refresh_expires
    # newest invoice first, in the app's shape
    assert [i["id"] for i in data.invoice_items] == [4476065, 4382143]
    assert data.invoice_items[0]["paymentStatus"] == "Obetald"
    assert data.invoice_items[0]["amount"] == 826.0
    # the building at the entry's address, not the first one
    ms.get_services.assert_awaited_once_with("985520")
    ms.get_extra_orders.assert_awaited_once_with("985520")
    current = data.properties["current"]
    assert current["designation"] == "Test 2:7"
    assert current["autogiro"] is True
    assert current["payment_type"] == "AGBG"
    assert data.sanitation["contracts"][0]["fee"] == {"price": 1916.62, "unit": "kr/år"}
    assert data.parameters == {"ordersAvailable": True, "complaintsAvailable": False}
    assert data.available_orders == [{"name": "Extra tömning", "id": 7, "title": "Extra tömning"}]


async def test_no_orders_and_no_building():
    ms = _minasidor(get_buildings=AsyncMock(return_value=[]))
    data = await _make_coordinator(minasidor=ms)._async_update_data()

    ms.get_services.assert_not_called()
    ms.get_extra_orders.assert_not_called()
    assert data.properties is None
    assert data.sanitation is None
    assert data.orders is None
    assert data.parameters == {"ordersAvailable": False, "complaintsAvailable": False}


async def test_each_failing_endpoint_is_tolerated(caplog):
    boom = AsyncMock(side_effect=VafabMiljoError("boom"))
    ms = _minasidor(get_invoices=boom, get_buildings=boom, get_billing_info=AsyncMock(side_effect=VafabMiljoError("x")))
    data = await _make_coordinator(minasidor=ms)._async_update_data()

    assert data.authenticated is True
    assert data.invoices is None
    assert data.properties is None
    for name in ("invoices", "buildings", "billing info"):
        assert f"Failed to fetch {name}" in caplog.text


async def test_failing_services_and_orders_are_tolerated(caplog):
    ms = _minasidor(
        get_services=AsyncMock(side_effect=VafabMiljoError("boom")),
        get_extra_orders=AsyncMock(side_effect=VafabMiljoError("boom")),
        get_billing_info=AsyncMock(return_value=["odd"]),
    )
    data = await _make_coordinator(minasidor=ms)._async_update_data()

    assert data.sanitation is None
    assert data.orders is None
    assert data.properties["current"]["autogiro"] is None
    assert "Failed to fetch services" in caplog.text
    assert "Failed to fetch extra orders" in caplog.text


async def test_an_expired_login_keeps_pickups_and_raises_a_repair():
    client = _app_client()
    client.list_next_pickup.return_value = [{"bins": [{"type": "Restavfall", "pickup_date": "2026-10-19"}]}]
    ms = _minasidor(get_invoices=AsyncMock(side_effect=VafabMiljoAuthError("expired")))
    coordinator = _make_coordinator(client, ms)
    coordinator.hass.data["_issues"] = {_EXPIRING_ISSUE: {}}

    data = await coordinator._async_update_data()

    assert data.pickups and data.authenticated and data.session_expired
    assert data.invoices is None
    assert data.settings == {"garbage": True}
    assert data.login_expires == ms.refresh_expires
    issue = coordinator.hass.data["_issues"][_BANKID_ISSUE]
    assert issue["learn_more_url"] == "homeassistant://vafabmiljo"
    assert issue["severity"] == "error"
    assert _EXPIRING_ISSUE not in coordinator.hass.data["_issues"]


async def test_a_working_login_clears_the_repair():
    coordinator = _make_coordinator(minasidor=_minasidor())
    coordinator.hass.data["_issues"] = {_BANKID_ISSUE: {}}
    await coordinator._async_update_data()
    assert coordinator.hass.data["_issues"] == {}


async def test_a_login_with_days_left_has_no_expiry_warning():
    coordinator = _make_coordinator(minasidor=_minasidor(expires_in=3 * 24 * 3600))
    coordinator.hass.data["_issues"] = {_EXPIRING_ISSUE: {}}

    await coordinator._async_update_data()

    assert _EXPIRING_ISSUE not in coordinator.hass.data["_issues"]
    assert coordinator.hass.bus.fired == []


async def test_a_login_about_to_run_out_warns_once():
    ms = _minasidor(expires_in=24 * 3600)
    coordinator = _make_coordinator(minasidor=ms)

    await coordinator._async_update_data()
    await coordinator._async_update_data()

    issue = coordinator.hass.data["_issues"][_EXPIRING_ISSUE]
    assert issue["severity"] == "warning"
    assert issue["translation_key"] == "login_expiring"
    assert issue["translation_placeholders"]["address"] == "Testgatan 1, Teststad"
    assert issue["translation_placeholders"]["expires"]
    events = [e for e in coordinator.hass.bus.fired if e[0] == EVENT_LOGIN_EXPIRING]
    assert len(events) == 1
    assert events[0][1]["entry_id"] == "test_entry"
    assert events[0][1]["expires"] == issue["translation_placeholders"]["expires"]


def test_order_item():
    assert _order_item({"title": "Extra"}) == {"title": "Extra"}
    assert _order_item({"description": "Grovavfall"})["title"] == "Grovavfall"
    assert _order_item({"serviceName": "Kärltvätt"})["title"] == "Kärltvätt"
    assert _order_item("Budning") == {"title": "Budning"}


# -- Data helpers ------------------------------------------------------------------------------------


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


def test_as_invoice_id_rejects_malformed_values_without_raising():
    from vafabmiljo.coordinator import _as_invoice_id

    assert _as_invoice_id(5) == 5
    assert _as_invoice_id(" 5 ") == 5
    # str.isdigit() is true for both, int() refuses the first and silently
    # normalises the second; plain ASCII decimals only, so both are rejected.
    assert _as_invoice_id("²") is None
    assert _as_invoice_id("５") is None
    assert _as_invoice_id(True) is None
    assert _as_invoice_id(None) is None
    assert _as_invoice_id([]) is None
    assert _as_invoice_id("12a") is None
    # int() would read these as 10; a junk row must not shadow the real id 10.
    assert _as_invoice_id("1_0") is None
    assert _as_invoice_id("１０") is None
    assert _as_invoice_id("-5") == -5
    # Past sys.int_max_str_digits int() raises; a corrupt stored id must not
    # abort entry setup.
    assert _as_invoice_id("1" * 5000) is None


async def test_apply_setting_updates_the_fetched_settings():
    client = _app_client()
    client.get_settings.return_value = {"garbage": True, "news": True}
    coordinator = _make_coordinator(client)
    coordinator.data = await coordinator._async_update_data()

    coordinator.async_apply_setting("garbage", False)

    assert coordinator.data.settings == {"garbage": False, "news": True}


async def test_apply_setting_without_fetched_settings_is_a_no_op():
    coordinator = _make_coordinator()
    coordinator.data = None
    coordinator.async_apply_setting("garbage", False)  # before the first refresh
    coordinator.data = VafabMiljoData(settings=None)
    coordinator.async_apply_setting("garbage", False)
    assert coordinator.data.settings is None
