"""Tests for the per-recipient notifications (reminders.py)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant
from vafabmiljo.const import EVENT_INVOICE_DUE_REMINDER, EVENT_NEW_INVOICE
from vafabmiljo.coordinator import VafabMiljoData
from vafabmiljo.reminders import (
    VafabMiljoNotifier,
    async_setup_websocket,
    clean_recipients,
    ws_get,
    ws_set,
)

TODAY = date(2026, 10, 9)


def _setup(bins=None):
    hass = HomeAssistant()
    hass.services.async_call = AsyncMock()
    entry = ConfigEntry(data={"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"})
    coordinator = Mock(data=VafabMiljoData(pickups=[{"bins": bins or []}]))
    entry.runtime_data = coordinator
    notifier = VafabMiljoNotifier(hass, entry, coordinator)
    coordinator.reminders = notifier
    return hass, entry, notifier


def _sent(hass):
    return [(c.args[1], c.args[2]["title"]) for c in hass.services.async_call.await_args_list]


def test_clean_recipients_fills_defaults_and_drops_junk():
    out = clean_recipients(
        [
            {"service": "mobile_app_a", "pickup_time": "25:00", "pickup_days_before": True, "new_invoice": "yes"},
            {"service": "mobile_app_a"},  # duplicate
            {"service": ""},
            "junk",
            {"service": "mobile_app_b", "pickup": False, "pickup_days_before": 0, "pickup_time": "06:30", "x": 1},
        ]
    )
    assert out == [
        {
            "service": "mobile_app_a",
            "pickup": True,
            "pickup_days_before": 1,
            "pickup_time": "18:00",
            "new_invoice": True,
            "invoice_due": True,
            "session_expired": True,
        },
        {
            "service": "mobile_app_b",
            "pickup": False,
            "pickup_days_before": 0,
            "pickup_time": "06:30",
            "new_invoice": True,
            "invoice_due": True,
            "session_expired": True,
        },
    ]
    assert clean_recipients(None) == []


async def test_pickup_reminder_goes_to_the_recipients_due_at_that_time():
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    hass, _, notifier = _setup(
        [{"type": "Restavfall", "pickup_date": tomorrow}, {"type": "Matavfall", "pickup_date": tomorrow}]
    )
    await notifier.async_setup()
    await notifier.async_set(
        [
            {"service": "evening", "pickup_time": "18:00"},
            {"service": "also_evening", "pickup_time": "18:00"},
            {"service": "morning", "pickup_time": "06:30", "pickup_days_before": 0},
            {"service": "off", "pickup": False},
        ]
    )
    # one timer per distinct time, none for a recipient with pickup reminders off
    assert sorted(t[1] for t in hass.time_listeners) == [(6, 30, 0), (18, 0, 0)]

    await notifier._on_time(datetime(2026, 10, 9, 18, 0))
    assert _sent(hass) == [
        ("evening", "Tömning imorgon: Restavfall, Matavfall"),
        ("also_evening", "Tömning imorgon: Restavfall, Matavfall"),
    ]

    hass.services.async_call.reset_mock()
    await notifier._on_time(datetime(2026, 10, 10, 6, 30))  # pickup day morning
    assert _sent(hass) == [("morning", "Tömning idag: Restavfall, Matavfall")]

    hass.services.async_call.reset_mock()
    await notifier._on_time(datetime(2026, 10, 12, 18, 0))  # nothing tomorrow
    assert _sent(hass) == []


async def test_recipients_persist_and_rescheduling_drops_old_timers():
    hass, entry, notifier = _setup()
    await notifier.async_setup()
    await notifier.async_set([{"service": "a", "pickup_time": "07:00"}])
    await notifier.async_set([{"service": "a", "pickup_time": "19:15"}])
    assert [t[1] for t in hass.time_listeners] == [(19, 15, 0)]

    again = VafabMiljoNotifier(hass, entry, entry.runtime_data)
    await again.async_setup()
    assert again.recipients[0]["pickup_time"] == "19:15"

    again.async_unload()
    notifier.async_unload()
    assert hass.time_listeners == [] and hass.bus.listeners == []


async def test_invoice_events_only_for_this_entry_and_opted_in_recipients():
    hass, entry, notifier = _setup()
    hass.config.language = "en"
    await notifier.async_setup()
    await notifier.async_set([{"service": "a"}, {"service": "b", "new_invoice": False}])
    data = {"entry_id": entry.entry_id, "amount": 1243.0, "due_date": "2026-10-31", "ocr_number": "123"}

    await notifier._on_invoice_event(Event(EVENT_NEW_INVOICE, data))
    await notifier._on_invoice_event(Event(EVENT_INVOICE_DUE_REMINDER, data))
    await notifier._on_invoice_event(Event(EVENT_NEW_INVOICE, {**data, "entry_id": "other"}))

    assert _sent(hass) == [
        ("a", "New invoice: 1243.0 kr"),
        ("a", "Invoice due tomorrow: 1243.0 kr"),
        ("b", "Invoice due tomorrow: 1243.0 kr"),
    ]
    assert hass.services.async_call.await_args_list[0].args[2]["message"] == "Testgatan 1, due 2026-10-31, OCR 123"


async def test_a_failing_recipient_does_not_stop_the_others():
    hass, entry, notifier = _setup()
    hass.services.async_call = AsyncMock(side_effect=[Exception("gone"), None])
    await notifier.async_set([{"service": "broken"}, {"service": "ok"}])
    await notifier._on_invoice_event(Event(EVENT_NEW_INVOICE, {"entry_id": entry.entry_id}))
    assert hass.services.async_call.await_count == 2


async def test_websocket_get_and_set():
    hass, entry, notifier = _setup()
    hass.config_entries = SimpleNamespace(async_get_entry=lambda eid: entry if eid == entry.entry_id else None)
    hass.services.async_services = lambda: {"notify": {"mobile_app_b": None, "mobile_app_a": None}}
    conn = Mock()

    ws_get(hass, conn, {"id": 1, "entry_id": entry.entry_id})
    assert conn.send_result.call_args.args[1] == {"recipients": [], "services": ["mobile_app_a", "mobile_app_b"]}

    await ws_set(hass, conn, {"id": 2, "entry_id": entry.entry_id, "recipients": [{"service": "mobile_app_a"}]})
    assert conn.send_result.call_args.args[1]["recipients"][0]["service"] == "mobile_app_a"
    assert ws_set.admin is True and ws_get.admin is True

    ws_get(hass, conn, {"id": 3, "entry_id": "nope"})
    await ws_set(hass, conn, {"id": 4, "entry_id": "nope", "recipients": []})
    assert [c.args[1] for c in conn.send_error.call_args_list] == ["not_found", "not_found"]


def test_websocket_commands_register_once():
    websocket_api.registered.clear()
    hass = HomeAssistant()
    async_setup_websocket(hass)
    async_setup_websocket(hass)
    assert websocket_api.registered[:2] == [ws_get, ws_set] and len(websocket_api.registered) == 5


async def test_expired_login_is_announced_once_per_session_even_across_restarts():
    hass, entry, notifier = _setup()
    entry.data["session_cookie"] = "c1"
    await notifier.async_set([{"service": "a"}, {"service": "b", "session_expired": False}])
    data = notifier._coordinator.data

    async def poll(expired):
        data.session_expired = expired
        notifier._on_update()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    await poll(True)
    await poll(True)  # still the same rejected session
    await poll(False)
    # a restart while still expired: a new notifier reads the marker back
    again = VafabMiljoNotifier(hass, entry, notifier._coordinator)
    await again.async_setup()
    await asyncio.sleep(0)
    entry.data["session_cookie"] = "c2"  # logged in again, and that session expired too
    await poll(True)
    assert _sent(hass) == [("a", "VafabMiljö: inloggningen har gått ut")] * 2
    again.async_unload()


async def test_old_list_format_still_loads_and_listener_follows_the_recipients():
    hass, entry, notifier = _setup()
    off = {"pickup": False, "session_expired": False}
    await notifier._store.async_save([{"service": "a", **off}])  # first 0.4.0 format
    await notifier.async_setup()
    assert notifier.recipients[0]["service"] == "a"
    # nobody needs fresh data: no coordinator listener (it would keep polling alive)
    assert notifier._unsub_coordinator is None
    # pickup reminders alone need fresh pickup dates, so they keep the polling going
    await notifier.async_set([{"service": "a", "session_expired": False}])
    assert notifier._unsub_coordinator is not None
    await notifier.async_set([{"service": "a", **off}])
    assert notifier._unsub_coordinator is None


async def test_notify_entities_go_through_send_message_and_are_offered():
    hass, entry, notifier = _setup()
    await notifier.async_set([{"service": "notify.sofias_phone"}])
    await notifier._on_invoice_event(Event(EVENT_NEW_INVOICE, {"entry_id": entry.entry_id, "amount": 1}))
    call = hass.services.async_call.await_args
    assert call.args[:2] == ("notify", "send_message")
    assert call.args[2]["entity_id"] == "notify.sofias_phone"

    from vafabmiljo.reminders import notify_targets

    hass.services.async_services = lambda: {"notify": {"send_message": None, "mobile_app_a": None}}
    hass.entity_ids["notify"] = ["notify.sofias_phone"]
    assert notify_targets(hass) == ["mobile_app_a", "notify.sofias_phone"]


async def test_an_already_expired_session_is_announced_at_setup():
    hass, entry, notifier = _setup()
    entry.data["session_cookie"] = "c1"  # an expired session always has a (rejected) cookie
    await notifier._store.async_save([{"service": "a"}])
    notifier._coordinator.data.session_expired = True
    await notifier.async_setup()
    for _ in range(3):
        await asyncio.sleep(0)
    assert _sent(hass) == [("a", "VafabMiljö: inloggningen har gått ut")]
