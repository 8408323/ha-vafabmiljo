"""Tests for the event-based new-invoice / due-reminder notifier."""

from __future__ import annotations

from datetime import datetime, time, timezone
from unittest.mock import Mock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.util import dt as dt_util
from vafabmiljo.const import EVENT_INVOICE_DUE_REMINDER, EVENT_NEW_INVOICE
from vafabmiljo.coordinator import VafabMiljoData
from vafabmiljo.invoices import VafabMiljoInvoiceNotifier, _parse_date, async_remove_invoice_store

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
    assert notifier.reminder_time == time(18, 0)

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
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["reminder_time"] == "07:30:00"

    # A restart picks the stored time back up.
    notifier.async_unload()
    assert hass.scheduled_timers == []
    fresh = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    await fresh.async_setup()
    assert fresh.reminder_time == time(7, 30)


async def test_first_check_waits_for_ha_start_on_cold_boot():
    import asyncio

    hass = HomeAssistant()
    hass.state = CoreState.starting
    coordinator = _coordinator([_inv(1, due="2026-09-30T00:00:00")])
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    await notifier.async_setup()

    # Nothing seeded, no timer yet: automations may not be listening.
    assert notifier.announced_count == 0
    assert hass.scheduled_timers == []
    assert len(hass.started_callbacks) == 1

    # A coordinator refresh completing mid-boot must not check either.
    coordinator.listeners[0]()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert notifier.announced_count == 0

    hass.state = CoreState.running
    hass.started_callbacks[0](hass)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert notifier.announced_count == 1
    assert len(hass.scheduled_timers) == 1


async def test_unload_before_ha_start_cancels_the_start_hook():
    hass = HomeAssistant()
    hass.state = CoreState.starting
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), _coordinator([_inv(1)]))
    await notifier.async_setup()
    notifier.async_unload()
    assert hass.started_callbacks == []


async def test_unload_blocks_late_checks_and_scheduling_but_never_loses_a_delivered_event():
    import asyncio

    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(2), _inv(1)]})
    coordinator.listeners[0]()  # spawns a check task that has not run yet
    notifier.async_unload()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # The late task saw the unloaded flag before doing anything.
    assert _events(hass, EVENT_NEW_INVOICE) == []
    assert hass.scheduled_timers == []

    # A stale direct call after unload must not schedule anything either.
    await notifier._async_check()
    await notifier._async_schedule_reminder()
    assert hass.scheduled_timers == []


async def test_event_fired_before_unload_is_still_persisted():
    # A check that has already fired must complete its save even if unload
    # happens while the save is in flight - otherwise the replacement notifier
    # would announce the same invoice again.
    import asyncio

    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [])
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(7)]})
    saved = asyncio.Event()
    original_save = notifier._store.async_save

    async def slow_save(data):
        notifier.async_unload()  # unload lands mid-save
        await original_save(data)
        saved.set()

    notifier._store.async_save = slow_save
    await notifier._async_check()
    assert saved.is_set()
    assert [e["invoice_id"] for e in _events(hass, EVENT_NEW_INVOICE)] == [7]
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["announced"] == [7]


async def test_remove_invoice_store_deletes_persisted_state():
    hass = HomeAssistant()
    await _setup(hass, [_inv(1)])
    assert "vafabmiljo.test_entry.invoices" in hass.data["_stores"]
    await async_remove_invoice_store(hass, _entry())
    assert "vafabmiljo.test_entry.invoices" not in hass.data["_stores"]


async def test_reminder_time_with_seconds_is_scheduled_and_persisted_exactly():
    hass = HomeAssistant()
    notifier, _ = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])
    await notifier.async_set_reminder_time(time(18, 30, 45))
    assert hass.scheduled_timers[0][1] == datetime(2026, 9, 29, 18, 30, 45, tzinfo=timezone.utc)
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["reminder_time"] == "18:30:45"


async def test_reminder_time_saved_before_seeding_does_not_count_as_a_baseline():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, None)  # first poll failed: not seeded
    await notifier.async_set_reminder_time(time(7, 0))  # writes the store anyway
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["seeded"] is False

    # "Restart" with the store present but unseeded, then the first valid snapshot arrives.
    notifier.async_unload()
    fresh = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    await fresh.async_setup()
    assert fresh.reminder_time == time(7, 0)
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(2), _inv(1)]})
    await fresh._async_check()
    assert _events(hass, EVENT_NEW_INVOICE) == []  # history was baselined, not announced
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["seeded"] is True


async def test_all_junk_rows_do_not_count_as_a_snapshot():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])
    assert len(hass.scheduled_timers) == 1
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [None, {"item": "junk"}]})
    await notifier._async_check()
    assert len(hass.scheduled_timers) == 1  # cached good list kept, timer untouched
    # ...whereas a genuinely empty list is a real (empty) snapshot on first run
    hass2 = HomeAssistant()
    n2, _ = await _setup(hass2, [])
    assert hass2.data["_stores"]["vafabmiljo.test_entry.invoices"]["seeded"] is True
    assert n2.announced_count == 0


async def test_duplicate_ids_in_one_response_announce_once_and_ids_are_normalised():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [])
    coordinator.data = VafabMiljoData(
        pickups=[],
        authenticated=True,
        invoices={
            "data": [
                _inv(4),
                _inv(4),
                {"item": {"id": "5", "amount": 1}},
                {"item": {"id": [], "amount": 2}},
                {"item": {"id": True}},
            ]
        },
    )
    await notifier._async_check()
    assert [e["invoice_id"] for e in _events(hass, EVENT_NEW_INVOICE)] == [5, 4]
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["announced"] == [4, 5]


async def test_reminder_recovers_after_restart_with_failed_first_poll():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])
    stored = hass.data["_stores"]["vafabmiljo.test_entry.invoices"]
    assert [i["id"] for i in stored["invoices"]] == [1]
    notifier.async_unload()

    # Restart: the first poll fails, but the persisted list still schedules the reminder.
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices=None)
    fresh = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    await fresh.async_setup()
    assert fresh.pending_reminder_invoice_id == 1
    assert hass.scheduled_timers[0][1] == datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)

    # A second failed poll while the timer is armed leaves it alone.
    await fresh._async_check()
    assert len(hass.scheduled_timers) == 1

    # Once a valid snapshot says it is paid, the next scheduling pass drops it.
    coordinator.data = VafabMiljoData(
        pickups=[], authenticated=True, invoices={"data": [_inv(1, status="Helt betald")]}
    )
    await fresh._async_check()
    assert hass.scheduled_timers == []
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["invoices"][0]["paymentStatus"] == "Helt betald"


async def test_store_with_string_or_junk_ids_is_normalised_on_load():
    hass = HomeAssistant()
    hass.data["_stores"] = {
        "vafabmiljo.test_entry.invoices": {"seeded": True, "announced": ["5", 4, None, "x"], "reminded": "junk"}
    }
    coordinator = _coordinator([_inv(5), _inv(4)])
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    await notifier.async_setup()
    assert _events(hass, EVENT_NEW_INVOICE) == []  # "5" matched 5, nothing re-announced
    assert notifier.announced_count == 2
    assert notifier.reminded_count == 0


async def test_failed_save_fires_nothing_and_is_retried_on_the_next_check():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [])
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(8)]})
    original = notifier._store.async_save
    calls = {"n": 0}

    async def flaky(data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        await original(data)

    notifier._store.async_save = flaky
    with pytest.raises(OSError):
        await notifier._async_check()
    # The marker never reached disk, so the event must NOT have been delivered:
    # a retry/reload would otherwise announce the same invoice a second time.
    assert _events(hass, EVENT_NEW_INVOICE) == []
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["announced"] == []
    assert 8 not in notifier._announced

    # Next check: persisted first, then delivered - exactly once.
    await notifier._async_check()
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["announced"] == [8]
    assert [e["invoice_id"] for e in _events(hass, EVENT_NEW_INVOICE)] == [8]
    await notifier._async_check()
    assert len(_events(hass, EVENT_NEW_INVOICE)) == 1


async def test_failed_save_of_a_reminder_marker_delivers_nothing_and_retries():
    dt_util.NOW_OVERRIDE = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)  # catch-up path
    hass = HomeAssistant()
    coordinator = _coordinator([_inv(1, due="2026-09-30T00:00:00")])
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    original = notifier._store.async_save
    calls = {"n": 0}

    async def flaky(data):
        calls["n"] += 1
        if calls["n"] == 2:  # the save guarding the reminder event
            raise OSError("disk full")
        await original(data)

    notifier._store.async_save = flaky
    with pytest.raises(OSError):
        await notifier.async_setup()
    # Marker never reached disk -> the event must not have been delivered.
    assert _events(hass, EVENT_INVOICE_DUE_REMINDER) == []
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["reminded"] == []
    assert 1 not in notifier._reminded

    notifier._store.async_save = original
    await notifier._async_check()
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["reminded"] == [1]
    assert [e["invoice_id"] for e in _events(hass, EVENT_INVOICE_DUE_REMINDER)] == [1]
    await notifier._async_check()
    assert len(_events(hass, EVENT_INVOICE_DUE_REMINDER)) == 1


async def test_plant_id_is_captured_at_construction():
    hass = HomeAssistant()
    entry = _entry()
    notifier = VafabMiljoInvoiceNotifier(hass, entry, _coordinator([_inv(1)]))
    entry.data["plant_id"] = "p-changed-by-reconfigure"  # mutated before this instance saves
    await notifier.async_setup()
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["plant_id"] == "p1"


async def test_pending_marker_save_is_retried_even_when_the_next_poll_fails():
    # A marker whose save failed is retried on the next check even while the
    # invoice endpoint is down.
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(8)])
    notifier._reminded.add(8)
    notifier._mark_dirty()
    assert notifier._dirty is True
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices=None)  # endpoint down
    await notifier._async_check()
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["reminded"] == [8]
    assert notifier._dirty is False


async def test_change_made_during_an_in_flight_save_stays_pending():
    import asyncio

    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [])
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(1)]})
    original = notifier._store.async_save
    gate = asyncio.Event()

    async def slow(data):
        await gate.wait()
        await original(data)

    notifier._store.async_save = slow
    first = asyncio.ensure_future(notifier._async_check())  # announces 1, blocks in save
    await asyncio.sleep(0)
    notifier._announced.add(2)
    notifier._mark_dirty()  # a second change lands while the first save is in flight
    gate.set()
    await first
    assert notifier._dirty is True  # the first save must not have cleared it
    notifier._store.async_save = original
    await notifier._async_check()
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["announced"] == [1, 2]
    assert notifier._dirty is False


async def test_event_payload_uses_address_captured_at_construction():
    hass = HomeAssistant()
    entry = _entry()
    notifier = VafabMiljoInvoiceNotifier(hass, entry, _coordinator([]))
    entry.data["address"] = "Nygatan 2"
    assert notifier._event_data({"id": 1})["address"] == "Testgatan 1"


async def test_failed_reminder_time_save_rolls_back():
    hass = HomeAssistant()
    notifier, _ = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])

    async def boom(data):
        raise OSError("disk full")

    notifier._store.async_save = boom
    with pytest.raises(OSError):
        await notifier.async_set_reminder_time(time(7, 0))
    assert notifier.reminder_time == time(18, 0)
    assert hass.scheduled_timers[0][1] == datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)


async def test_reconfigured_property_resets_persisted_state_but_keeps_reminder_time():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(1, status="Helt betald")])
    await notifier.async_set_reminder_time(time(7, 0))
    notifier.async_unload()
    # Same entry_id, different plant_id (reconfigure flow): old state must not carry over.
    entry = ConfigEntry(data={"address": "Nygatan 2", "city": "Teststad", "plant_id": "p2"})
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(9)]})
    fresh = VafabMiljoInvoiceNotifier(hass, entry, coordinator)
    await fresh.async_setup()
    assert fresh.reminder_time == time(7, 0)
    assert _events(hass, EVENT_NEW_INVOICE) == []  # re-baselined on the new property's history
    assert fresh.announced_count == 1
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["plant_id"] == "p2"


async def test_reconfigure_reset_is_persisted_even_if_the_new_property_has_no_snapshot_yet():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(1)])
    notifier.async_unload()
    entry = ConfigEntry(data={"address": "Nygatan 2", "city": "Teststad", "plant_id": "p2"})
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices=None)  # endpoint down
    fresh = VafabMiljoInvoiceNotifier(hass, entry, coordinator)
    await fresh.async_setup()
    stored = hass.data["_stores"]["vafabmiljo.test_entry.invoices"]
    assert stored["plant_id"] == "p2"
    assert stored["announced"] == [] and stored["invoices"] == [] and stored["seeded"] is False


async def test_store_lock_is_shared_per_entry_and_remove_waits_for_it():
    import asyncio

    hass = HomeAssistant()
    a = VafabMiljoInvoiceNotifier(hass, _entry(), _coordinator([]))
    b = VafabMiljoInvoiceNotifier(hass, _entry(), _coordinator([]))
    assert a._lock is b._lock
    await a.async_setup()
    async with a._lock:
        remove = asyncio.ensure_future(async_remove_invoice_store(hass, _entry()))
        await asyncio.sleep(0)
        assert not remove.done()  # blocked behind the in-flight holder
    await remove
    assert "vafabmiljo.test_entry.invoices" not in hass.data["_stores"]


async def test_cached_invoice_ids_are_normalised_on_load():
    hass = HomeAssistant()
    hass.data["_stores"] = {
        "vafabmiljo.test_entry.invoices": {
            "seeded": True,
            "plant_id": "p1",
            "announced": [5],
            "reminded": [5],
            "reminder_time": "18:00:00",
            "invoices": [
                {"id": "5", "invoiceExpirationDate": "2026-09-30T00:00:00", "paymentStatus": "Obetald"},
                {"id": None},
                "junk",
            ],
        }
    }
    coordinator = _coordinator(None)  # endpoint down: the cache is all we have
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    await notifier.async_setup()
    assert [inv["id"] for inv in notifier._last_invoices] == [5]
    # "5" matched the reminded marker 5, so no duplicate reminder was armed.
    assert hass.scheduled_timers == []
    assert notifier.pending_reminder_invoice_id is None


async def test_stale_timer_callback_does_not_orphan_the_replacement():
    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])
    stale_action, _ = hass.scheduled_timers[0]

    # A new invoice with a nearer due date replaces the armed timer.
    coordinator.data = VafabMiljoData(
        pickups=[], authenticated=True, invoices={"data": [_inv(2, due="2026-09-20T00:00:00"), _inv(1)]}
    )
    await notifier._async_check()
    assert notifier.pending_reminder_invoice_id == 2
    current_handle = notifier._unsub_timer

    # The old callback was already queued when its timer got cancelled.
    await stale_action(datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc))

    assert notifier._unsub_timer is current_handle  # replacement untouched
    assert notifier.pending_reminder_invoice_id == 2
    assert _events(hass, EVENT_INVOICE_DUE_REMINDER) == []


async def test_checks_are_serialised_so_a_concurrent_save_cannot_persist_a_rolled_back_marker():
    import asyncio

    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [])
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(8)]})
    original = notifier._store.async_save
    gate = asyncio.Event()
    started = asyncio.Event()

    async def failing(data):
        started.set()
        await gate.wait()
        raise OSError("disk full")

    notifier._store.async_save = failing
    first = asyncio.ensure_future(notifier._async_check())
    await started.wait()

    # A second check must not run (and must not persist 8) while the first
    # holds the work lock and is about to roll its marker back.
    second = asyncio.ensure_future(notifier._async_check())
    await asyncio.sleep(0)
    assert not second.done()

    # Swap the store back before releasing: the first save is already inside
    # `failing`, and the second check resumes the moment the lock is freed.
    notifier._store.async_save = original
    gate.set()
    with pytest.raises(OSError):
        await first
    await second

    # Exactly one delivery, and the marker on disk matches what was delivered.
    assert [e["invoice_id"] for e in _events(hass, EVENT_NEW_INVOICE)] == [8]
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["announced"] == [8]


async def test_failed_reminder_time_save_restores_the_previous_schedule():
    hass = HomeAssistant()
    notifier, _ = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])
    original = notifier._store.async_save

    async def boom(data):
        raise OSError("disk full")

    notifier._store.async_save = boom
    with pytest.raises(OSError):
        await notifier.async_set_reminder_time(time(7, 0))

    notifier._store.async_save = original
    assert notifier.reminder_time == time(18, 0)
    # The armed timer matches the restored value, not the rejected one.
    assert len(hass.scheduled_timers) == 1
    assert hass.scheduled_timers[0][1] == datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)


async def test_cancelled_save_leaves_the_invoice_retryable():
    import asyncio

    hass = HomeAssistant()
    notifier, coordinator = await _setup(hass, [])
    coordinator.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": [_inv(8)]})

    async def cancelled(data):
        raise asyncio.CancelledError

    notifier._store.async_save = cancelled
    with pytest.raises(asyncio.CancelledError):
        await notifier._async_check()
    # CancelledError is not an Exception: the marker must still be rolled back,
    # or the invoice would be suppressed forever without ever being announced.
    assert 8 not in notifier._announced
    assert _events(hass, EVENT_NEW_INVOICE) == []


async def test_cancelled_reminder_save_leaves_the_reminder_retryable():
    import asyncio

    dt_util.NOW_OVERRIDE = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)  # catch-up path
    hass = HomeAssistant()
    coordinator = _coordinator([_inv(1, due="2026-09-30T00:00:00")])
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    original = notifier._store.async_save
    calls = {"n": 0}

    async def cancelled(data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise asyncio.CancelledError
        await original(data)

    notifier._store.async_save = cancelled
    with pytest.raises(asyncio.CancelledError):
        await notifier.async_setup()
    assert 1 not in notifier._reminded
    assert _events(hass, EVENT_INVOICE_DUE_REMINDER) == []


@pytest.mark.parametrize("stored", [["not", "a", "mapping"], "junk", 42])
async def test_malformed_persisted_state_is_ignored_instead_of_aborting_setup(stored):
    hass = HomeAssistant()
    hass.data["_stores"] = {"vafabmiljo.test_entry.invoices": stored}
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), _coordinator([_inv(1)]))
    await notifier.async_setup()
    # Treated as no state at all: re-baselined, nothing announced.
    assert _events(hass, EVENT_NEW_INVOICE) == []
    assert notifier.announced_count == 1


async def test_malformed_persisted_reminder_time_falls_back_to_the_default():
    hass = HomeAssistant()
    hass.data["_stores"] = {
        "vafabmiljo.test_entry.invoices": {
            "seeded": True,
            "plant_id": "p1",
            "announced": [1],
            "reminded": [],
            "reminder_time": "not-a-time",
            "invoices": [],
        }
    }
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), _coordinator([_inv(1)]))
    await notifier.async_setup()
    assert notifier.reminder_time == time(18, 0)


async def test_unload_during_setup_does_not_attach_a_listener():
    import asyncio

    hass = HomeAssistant()
    coordinator = _coordinator([_inv(1)])
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), coordinator)
    gate = asyncio.Event()

    async def slow_load():
        await gate.wait()
        return None

    notifier._store.async_load = slow_load
    setup = asyncio.ensure_future(notifier.async_setup())
    await asyncio.sleep(0)
    notifier.async_unload()
    gate.set()
    await setup
    assert coordinator.listeners == []


async def test_reminder_time_is_refused_after_unload():
    hass = HomeAssistant()
    notifier, _ = await _setup(hass, [_inv(1)])
    before = dict(hass.data["_stores"]["vafabmiljo.test_entry.invoices"])
    notifier.async_unload()
    await notifier.async_set_reminder_time(time(7, 0))
    assert notifier.reminder_time == time(18, 0)
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"] == before


async def test_cancelled_reminder_time_save_restores_value_and_schedule():
    import asyncio

    hass = HomeAssistant()
    notifier, _ = await _setup(hass, [_inv(1, due="2026-09-30T00:00:00")])
    original = notifier._store.async_save

    async def cancelled(data):
        raise asyncio.CancelledError

    notifier._store.async_save = cancelled
    with pytest.raises(asyncio.CancelledError):
        await notifier.async_set_reminder_time(time(7, 0))
    notifier._store.async_save = original
    assert notifier.reminder_time == time(18, 0)
    assert hass.scheduled_timers[0][1] == datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("flag", ["false", "true", [0], 1, None])
async def test_only_a_real_true_counts_as_seeded(flag):
    hass = HomeAssistant()
    hass.data["_stores"] = {
        "vafabmiljo.test_entry.invoices": {
            "seeded": flag,
            "plant_id": "p1",
            "announced": [],
            "reminded": [],
            "reminder_time": "18:00:00",
            "invoices": [],
        }
    }
    notifier = VafabMiljoInvoiceNotifier(hass, _entry(), _coordinator([_inv(1), _inv(2)]))
    await notifier.async_setup()
    # A corrupt flag must fall back to baselining, never announce the history.
    assert _events(hass, EVENT_NEW_INVOICE) == []
    assert notifier.announced_count == 2
    assert hass.data["_stores"]["vafabmiljo.test_entry.invoices"]["seeded"] is True


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
