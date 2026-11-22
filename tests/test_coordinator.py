"""Tests for VafabMiljoCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
        get_invoices=AsyncMock(return_value={"data": [{"item": {"amount": 500}}]}),
    )

    data = await _make_coordinator(client)._async_update_data()

    assert data.authenticated is True
    assert data.invoices == {"data": [{"item": {"amount": 500}}]}
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


async def _assert_expired_keeps_pickups(client):
    client.list_next_pickup.return_value = [{"bins": [{"type": "Restavfall", "pickup_date": "2026-10-19"}]}]
    coordinator = _make_coordinator(client)
    data = await coordinator._async_update_data()
    # the pickup calendar keeps working; HA is asked for a new BankID login
    assert data.pickups and data.authenticated and data.session_expired
    assert data.invoices is None
    assert coordinator.entry.reauth_started == 1
    # a repair in Settings -> Repairs, linking to the panel
    issue = coordinator.hass.data["_issues"][("vafabmiljo", "bankid_expired_test_entry")]
    assert issue["learn_more_url"] == "homeassistant://vafabmiljo"
    assert issue["severity"] == "error"
    assert issue["translation_placeholders"] == {"address": "Testgatan 1, Teststad"}


async def test_expired_session_triggers_reauth():
    client = AsyncMock()
    client.session_cookie = "abc123"
    client.get_invoices.side_effect = VafabMiljoAuthError("expired")
    await _assert_expired_keeps_pickups(client)


async def test_keep_alive_called_before_account_data(caplog):
    # Matches the real app's own behavior of extending the session
    # periodically - not a workaround for anything (see coordinator.py).
    client = _authenticated_client()

    await _make_coordinator(client)._async_update_data()

    client.keep_alive.assert_awaited_once()


async def test_keep_alive_failure_is_tolerated(caplog):
    client = _authenticated_client(keep_alive=AsyncMock(side_effect=VafabMiljoError("boom")))

    data = await _make_coordinator(client)._async_update_data()

    assert data.authenticated is True
    assert "Failed to keep the BankID session alive: boom" in caplog.text


async def test_keep_alive_auth_error_triggers_reauth():
    client = _authenticated_client(keep_alive=AsyncMock(side_effect=VafabMiljoAuthError("expired")))
    await _assert_expired_keeps_pickups(client)


async def test_get_customer_called_before_account_data(caplog):
    # Confirmed live: fixes a real account whose invoices stayed 202
    # "waiting" for hours (see api.py's VafabMiljoClient.get_customer).
    client = _authenticated_client()

    await _make_coordinator(client)._async_update_data()

    client.get_customer.assert_awaited_once()


async def test_get_customer_failure_is_tolerated(caplog):
    client = _authenticated_client(get_customer=AsyncMock(side_effect=VafabMiljoError("boom")))

    data = await _make_coordinator(client)._async_update_data()

    assert data.authenticated is True
    assert "Failed to fetch customer record: boom" in caplog.text


async def test_get_customer_auth_error_triggers_reauth():
    client = _authenticated_client(get_customer=AsyncMock(side_effect=VafabMiljoAuthError("expired")))
    await _assert_expired_keeps_pickups(client)


async def test_authenticated_account_fetch_failure_is_tolerated(caplog):
    # invoices/sanitation/properties/orders/complaints are independent - one
    # endpoint stuck or failing (e.g. an account whose /services/invoices
    # never leaves the backend's 202 "waiting" state) shouldn't take down the
    # pickup-schedule sensors, which don't need any of this account data.
    client = _authenticated_client()
    client.get_invoices.side_effect = VafabMiljoError("boom")

    data = await _make_coordinator(client)._async_update_data()

    assert data.authenticated is True
    assert data.invoices is None
    assert data.sanitation == {"contracts": []}
    assert "Failed to fetch invoices: boom" in caplog.text


async def test_orders_fetch_failure_is_tolerated(caplog):
    client = _authenticated_client(
        get_parameters=AsyncMock(return_value={"ordersAvailable": True, "complaintsAvailable": False}),
        get_orders=AsyncMock(side_effect=VafabMiljoError("boom")),
    )

    data = await _make_coordinator(client)._async_update_data()

    assert data.authenticated is True
    assert data.orders is None
    assert "Failed to fetch orders: boom" in caplog.text


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


def test_as_invoice_id_rejects_malformed_values_without_raising():
    from vafabmiljo.coordinator import _as_invoice_id

    assert _as_invoice_id(5) == 5
    assert _as_invoice_id(" 5 ") == 5
    # str.isdigit() is true for both, int() refuses the first and silently
    # normalises the second; plain ASCII decimals only, so both are rejected.
    assert _as_invoice_id("\u00b2") is None
    assert _as_invoice_id("\uff15") is None
    assert _as_invoice_id(True) is None
    assert _as_invoice_id(None) is None
    assert _as_invoice_id([]) is None
    assert _as_invoice_id("12a") is None
    # int() would read these as 10; a junk row must not shadow the real id 10.
    assert _as_invoice_id("1_0") is None
    assert _as_invoice_id("\uff11\uff10") is None
    assert _as_invoice_id("-5") == -5
    # Past sys.int_max_str_digits int() raises; a corrupt stored id must not
    # abort entry setup.
    assert _as_invoice_id("1" * 5000) is None


async def test_a_working_login_clears_the_repair():
    client = _authenticated_client()
    coordinator = _make_coordinator(client)
    coordinator.hass.data["_issues"] = {("vafabmiljo", "bankid_expired_test_entry"): {}}
    await coordinator._async_update_data()
    assert coordinator.hass.data["_issues"] == {}


def _keep_alive_coordinator(client, *, cookie_in_entry="abc123", expired=False) -> VafabMiljoCoordinator:
    hass = HomeAssistant()
    entry = ConfigEntry(data={"session_cookie": cookie_in_entry})
    coordinator = VafabMiljoCoordinator(hass, entry, client)
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, session_expired=expired)
    return coordinator


async def test_keep_alive_tick_pings_the_backend():
    client = _authenticated_client()
    coordinator = _keep_alive_coordinator(client)

    await coordinator._async_keep_alive()

    client.keep_alive.assert_awaited_once()
    assert coordinator.hass.config_entries.updates == []  # cookie unchanged: nothing saved


async def test_keep_alive_tick_saves_a_rotated_cookie():
    client = _authenticated_client()
    coordinator = _keep_alive_coordinator(client)

    async def _rotate():
        client.session_cookie = "rotated"

    client.keep_alive = AsyncMock(side_effect=_rotate)
    await coordinator._async_keep_alive()

    assert coordinator.entry.data["session_cookie"] == "rotated"
    assert coordinator.is_own_entry_update(coordinator.entry)


async def test_keep_alive_tick_leaves_a_cookie_from_a_new_login_alone():
    client = _authenticated_client()
    coordinator = _keep_alive_coordinator(client)
    coordinator.entry.data = {"session_cookie": "from-panel-login"}  # saved meanwhile; a reload follows
    client.session_cookie = "rotated-old-session"

    await coordinator._async_keep_alive()

    assert coordinator.entry.data["session_cookie"] == "from-panel-login"
    assert not coordinator.is_own_entry_update(coordinator.entry)


async def test_keep_alive_tick_skips_an_expired_or_missing_session():
    client = _authenticated_client()
    await _keep_alive_coordinator(client, expired=True)._async_keep_alive()
    client.session_cookie = None
    await _keep_alive_coordinator(client)._async_keep_alive()

    client.keep_alive.assert_not_awaited()


async def test_keep_alive_tick_rejected_runs_the_expiry_handling():
    client = _authenticated_client(keep_alive=AsyncMock(side_effect=VafabMiljoAuthError("expired")))
    coordinator = _keep_alive_coordinator(client)

    await coordinator._async_keep_alive()

    # the refresh it triggered marked the session expired and asked for a new login
    assert coordinator.data.session_expired is True
    assert coordinator.entry.reauth_started == 1


async def test_keep_alive_tick_tolerates_a_network_error():
    client = _authenticated_client(keep_alive=AsyncMock(side_effect=VafabMiljoError("boom")))
    coordinator = _keep_alive_coordinator(client)

    await coordinator._async_keep_alive()

    assert coordinator.data.session_expired is False


async def test_refresh_saves_a_rotated_cookie():
    client = _authenticated_client()
    coordinator = _keep_alive_coordinator(client, cookie_in_entry="old")

    await coordinator._async_update_data()

    assert coordinator.entry.data["session_cookie"] == "abc123"


# -- No customer record for the logged-in person -----------------------------------------------------

_NO_CUSTOMER = {"status": "error", "code": "api_error", "message": "No customer data", "no_customer": True}


async def test_no_customer_skips_account_endpoints_and_raises_a_repair(caplog):
    # seen live: /services/customer answers 200 with no_customer, parameters then 404s and sanitation 500s
    client = _authenticated_client(get_customer=AsyncMock(return_value=_NO_CUSTOMER))
    client.get_settings.return_value = {"garbage": True}
    coordinator = _make_coordinator(client)

    data = await coordinator._async_update_data()

    assert data.authenticated is True
    assert data.no_customer is True
    assert data.session_expired is False
    assert data.settings == {"garbage": True}
    assert data.invoices is None
    for skipped in (client.get_invoices, client.get_sanitation, client.get_properties, client.get_parameters):
        skipped.assert_not_called()
    issue = coordinator.hass.data["_issues"][("vafabmiljo", "no_customer_test_entry")]
    assert issue["severity"] == "warning"
    assert issue["translation_key"] == "no_customer"
    assert issue["translation_placeholders"] == {"address": "Testgatan 1, Teststad"}
    assert "no customer data" in caplog.text


async def test_no_customer_is_logged_once_not_every_refresh(caplog):
    client = _authenticated_client(get_customer=AsyncMock(return_value=_NO_CUSTOMER))
    coordinator = _make_coordinator(client)

    await coordinator._async_update_data()
    await coordinator._async_update_data()

    assert caplog.text.count("no customer data") == 1


async def test_customer_data_coming_back_clears_the_no_customer_repair(caplog):
    client = _authenticated_client(get_customer=AsyncMock(return_value=_NO_CUSTOMER))
    coordinator = _make_coordinator(client)
    await coordinator._async_update_data()

    client.get_customer = AsyncMock(return_value={"status": "ok"})
    data = await coordinator._async_update_data()

    assert data.no_customer is False
    assert ("vafabmiljo", "no_customer_test_entry") not in coordinator.hass.data["_issues"]
    client.get_invoices.assert_awaited()

    # and if it disappears again, that is logged again
    client.get_customer = AsyncMock(return_value=_NO_CUSTOMER)
    await coordinator._async_update_data()
    assert caplog.text.count("no customer data") == 2


async def test_settings_are_fetched_with_the_account_data():
    client = _authenticated_client()
    client.get_settings.return_value = {"garbage": False, "time": "07:30"}

    data = await _make_coordinator(client)._async_update_data()

    assert data.settings == {"garbage": False, "time": "07:30"}


async def test_failing_or_odd_settings_are_ignored(caplog):
    client = _authenticated_client()
    client.get_settings.side_effect = VafabMiljoError("boom")
    assert (await _make_coordinator(client)._async_update_data()).settings is None

    client.get_settings.side_effect = None
    client.get_settings.return_value = ["not", "a", "dict"]
    assert (await _make_coordinator(client)._async_update_data()).settings is None


async def test_apply_setting_updates_the_fetched_settings():
    client = _authenticated_client()
    client.get_settings.return_value = {"garbage": True, "news": True}
    coordinator = _make_coordinator(client)
    coordinator.data = await coordinator._async_update_data()

    coordinator.async_apply_setting("garbage", False)

    assert coordinator.data.settings == {"garbage": False, "news": True}


async def test_apply_setting_without_fetched_settings_is_a_no_op():
    coordinator = _make_coordinator(_authenticated_client())
    coordinator.data = None
    coordinator.async_apply_setting("garbage", False)  # before the first refresh
    coordinator.data = VafabMiljoData(settings=None)
    coordinator.async_apply_setting("garbage", False)
    assert coordinator.data.settings is None
