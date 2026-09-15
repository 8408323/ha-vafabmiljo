"""Tests for the event-based new-invoice / due-reminder notifier."""

from __future__ import annotations

from datetime import datetime, time, timezone
from unittest.mock import Mock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from vafabmiljo.const import EVENT_INVOICE_DUE_REMINDER, EVENT_NEW_INVOICE
from vafabmiljo.coordinator import VafabMiljoData
from vafabmiljo.invoices import DEFAULT_INVOICE_REMINDER_TIME, VafabMiljoInvoiceNotifier, _parse_date

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _pin_now():
    dt_util.NOW_OVERRIDE = NOW
    yield
    dt_util.NOW_OVERRIDE = None


def _inv(inv_id: int, due: str | None = "2026-09-30T00:00:00", status: str = "Obetald", amount: int = 826) -> dict:
    item = {
        "id": inv_id,
        "amount": amount,
        "invoiceDate": "2026-09-01T00:00:00",
        "paymentStatus": status,
        "ocrNumber": "1",
    }
    if due is not None:
        item["invoiceExpirationDate"] = due
    return {"item": item}


def _coordinator(invoices: list[dict] | None) -> Mock:
    coordinator = Mock()
    coordinator.data = VafabMiljoData(
        pickups=[], authenticated=True, invoices=None if invoices is None else {"data": invoices}
    )
    listeners: list = []
    coordinator.async_add_listener = Mock(
        side_effect=lambda cb: (listeners.append(cb), lambda: listeners.remove(cb))[1]
    )
    coordinator.listeners = listeners
    return coordinator


def _entry() -> ConfigEntry:
    return ConfigEntry(data={"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"})


async def _setup(hass: HomeAssistant, invoices: list[dict] | None):
    coordinator = _coordinator(invoices)
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    await notifier.async_setup()
    return notifier, coordinator


def _events(hass: HomeAssistant, event_type: str) -> list[dict]:
    return [data for etype, data in hass.bus.fired if etype == event_type]


async def _fire_timer(hass: HomeAssistant):
    """Simulate the scheduled point-in-time firing: real HA drops a fired timer before calling it."""
    action, when = hass.scheduled_timers.pop(0)
    dt_util.NOW_OVERRIDE = when
    await action(when)
    return when


async def test_first_run_seeds_existing_invoices_without_announcing():
    hass = HomeAssistant()
    notifier, _ = await _setup(hass, [_inv(2, status="Helt betald"), _inv(1, status="Helt betald")])

    assert _events(hass, EVENT_NEW_INVOICE) == []
    assert notifier.announced_count == 2
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["announced"] == [1, 2]


async def test_new_invoice_is_announced_exactly_once_across_polls_and_restarts():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(1, status="Helt betald")])

    coordinator.data = VafabMiljoData(
        pickups=[], authenticated=True, invoices={"data": [_inv(2), _inv(1, status="Helt betald")]}
    )
    await notifier._async_check()
    await notifier._async_check()  # same data again: nothing new

    events = _events(hass, EVENT_NEW_INVOICE)
    assert len(events) == 1
    assert events[0]["invoice_id"] == 2
    assert events[0]["amount"] == 826
    assert events[0]["due_date"] == "2026-09-30"
    assert events[0]["invoice_date"] == "2026-09-01"
    assert events[0]["days_until_due"] == 15
    assert events[0]["address"] == "Testgatan 1"
    assert events[0]["payment_status"] == "Obetald"

    # "Restart": a fresh notifier reading the same store must stay quiet.
    notifier.async_unload()
    fresh = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    await fresh.async_setup()
    assert len(_events(hass, EVENT_NEW_INVOICE)) == 1


async def test_burst_of_new_invoices_is_announced_oldest_first():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [])
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(3), _inv(2)]})
    await notifier._async_check()
    assert [e["invoice_id"] for e in _events(hass, EVENT_NEW_INVOICE)] == [2, 3]


async def test_coordinator_update_triggers_a_check():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [])
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(9)]})
    assert len(coordinator.listeners) == 1
    coordinator.listeners[0]()
    # the listener schedules a task; let it run
    import asyncio

    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert [e["invoice_id"] for e in _events(hass, EVENT_NEW_INVOICE)] == [9]
    notifier.async_unload()
    assert coordinator.listeners == []


async def test_failed_first_poll_defers_seeding_until_a_valid_snapshot():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, None)  # invoices endpoint failed on first refresh
    assert notifier.announced_count == 0
    assert "vafabmiljo.test_entry.invoices" not in hass.data.get("_stores", {})  # not baselined on an empty set

    # First valid snapshot = the baseline; the existing history is NOT announced.
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(2), _inv(1)]})
    await notifier._async_check()
    assert _events(hass, EVENT_NEW_INVOICE) == []
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["announced"] == [1, 2]

    # ...and only genuinely new invoices after that are.
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(3), _inv(2), _inv(1)]})
    await notifier._async_check()
    assert [e["invoice_id"] for e in _events(hass, EVENT_NEW_INVOICE)] == [3]


@pytest.mark.parametrize(
    "invoices",
    [
        None,  # endpoint failed
        {"data": None},
        {"data": "junk"},
        {"data": [None, "junk", {"item": None}, {"item": "junk"}, {"item": {"amount": 1}}]},
    ],
)
async def test_malformed_invoice_envelopes_are_ignored(invoices):
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(1, status="Helt betald")])
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices=invoices)
    await notifier._async_check()
    assert _events(hass, EVENT_NEW_INVOICE) == []
    coordinator.data = None  # e.g. before the first refresh completed
    await notifier._async_check()
    assert _events(hass, EVENT_NEW_INVOICE) == []


async def test_failed_poll_keeps_the_pending_reminder_timer():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])
    assert len(hass.scheduled_timers) == 1
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices=None)
    await notifier._async_check()
    assert len(hass.scheduled_timers) == 1
    assert notifier.pending_reminder_invoice_id == 1
    # The timer still fires from the cached data even though the poll failed.
    await _fire_timer(hass)
    assert [e["invoice_id"] for e in _events(hass, EVENT_INVOICE_DUE_REMINDER)] == [1]


async def test_reminder_is_scheduled_the_day_before_due_at_reminder_time():
    hass = HomeAssistant()
    notifier, _ = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])

    assert len(hass.scheduled_timers) == 1
    assert hass.scheduled_timers[0][1] == datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)
    assert notifier.pending_reminder_invoice_id == 1
    assert notifier.reminder_time == DEFAULT_INVOICE_REMINDER_TIME

    # Timer fires: the reminder goes out once and is persisted.
    await _fire_timer(hass)
    events = _events(hass, EVENT_INVOICE_DUE_REMINDER)
    assert len(events) == 1
    assert events[0]["invoice_id"] == 1
    assert events[0]["days_until_due"] == 1
    assert notifier.reminded_count == 1
    assert notifier.pending_reminder_invoice_id is None
    assert hass.scheduled_timers == []

    # Another poll must not send it again.
    await notifier._async_check()
    assert len(_events(hass, EVENT_INVOICE_DUE_REMINDER)) == 1
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["reminded"] == [1]


async def test_missed_reminder_is_sent_immediately_while_invoice_still_not_due():
    # Due tomorrow, reminder time (18:00 yesterday relative to due) already passed.
    dt_util.NOW_OVERRIDE = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)
    hass = HomeAssistant()
    notifier, _ = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])
    assert [e["invoice_id"] for e in _events(hass, EVENT_INVOICE_DUE_REMINDER)] == [1]
    assert hass.scheduled_timers == []
    assert notifier.reminded_count == 1


@pytest.mark.parametrize(
    "invoices",
    [
        [_inv(1, status="Helt betald")],  # paid
        [_inv(1, status="HELT BETALD ")],  # paid, odd casing/whitespace
        [_inv(1, due="2026-09-01T00:00:00")],  # already past due
        [_inv(1, due="2026-09-15T00:00:00")],  # due today: the day-before moment is gone
        [_inv(1, due=None)],  # no due date at all
        [_inv(1, due="not-a-date")],
    ],
)
async def test_no_reminder_when_nothing_is_actionable(invoices):
    hass = HomeAssistant()
    notifier, _ = await _setup(hass, invoices)
    assert hass.scheduled_timers == []
    assert _events(hass, EVENT_INVOICE_DUE_REMINDER) == []
    assert notifier.pending_reminder_invoice_id is None


async def test_nearest_unpaid_invoice_is_reminded_first_then_the_next():
    hass = HomeAssistant()
    notifier, _ = await _setup(hass, [_inv(2, due="2026-10-15T00:00:00"), _inv(1, due="2026-09-30T00:00:00")])
    assert notifier.pending_reminder_invoice_id == 1
    await _fire_timer(hass)
    assert [e["invoice_id"] for e in _events(hass, EVENT_INVOICE_DUE_REMINDER)] == [1]
    # the next one is now scheduled
    assert notifier.pending_reminder_invoice_id == 2
    assert hass.scheduled_timers[0][1] == datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)


async def test_setting_reminder_time_persists_and_reschedules():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])
    await notifier.async_set_reminder_time(time(7, 30))
    assert hass.scheduled_timers[0][1] == datetime(2026, 9, 29, 7, 30, tzinfo=timezone.utc)
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["reminder_time"] == "07:30"

    # A restart picks the stored time back up.
    notifier.async_unload()
    assert hass.scheduled_timers == []
    fresh = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    await fresh.async_setup()
    assert fresh.reminder_time == time(7, 30)


async def test_unload_is_safe_to_call_twice():
    hass = HomeAssistant()
    notifier, _ = await _setup(hass, [_inv(1)])
    notifier.async_unload()
    notifier.async_unload()
    assert hass.scheduled_timers == []


def test_parse_date_handles_garbage():
    assert _parse_date(None) is None
    assert _parse_date("2026-09") is None
    assert _parse_date("2026-13-45T00:00:00") is None
    assert _parse_date("2026-09-30T00:00:00").isoformat() == "2026-09-30"


def test_event_data_without_dates():
    hass = HomeAssistant()
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), _coordinator([]))
    data = notifier._event_data({"id": 7, "amount": 1})
    assert data["due_date"] is None and data["invoice_date"] is None and data["days_until_due"] is None
