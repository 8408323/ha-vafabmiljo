"""Tests for the VafabMiljö reminder-time entity."""

from __future__ import annotations

from datetime import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.config_entries import ConfigEntry
from vafabmiljo.coordinator import VafabMiljoData
from vafabmiljo.time import (
    DEFAULT_NOTIFY_TIME,
    DEFAULT_REMINDER_TIME,
    VafabMiljoInvoiceReminderTimeEntity,
    VafabMiljoNotifyTimeEntity,
    VafabMiljoReminderTimeEntity,
    async_setup_entry,
)


def _entry() -> ConfigEntry:
    return ConfigEntry(data={"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"})


def _coordinator(authenticated: bool, notifier=None) -> Mock:
    coordinator = Mock()
    coordinator.data = VafabMiljoData(pickups=[], authenticated=authenticated)
    coordinator.client = AsyncMock()
    coordinator.invoice_notifier = notifier
    return coordinator


async def test_setup_adds_only_notify_time_when_not_authenticated():
    entry = _entry()
    entry.runtime_data = _coordinator(authenticated=False)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert len(added) == 1
    assert isinstance(added[0], VafabMiljoNotifyTimeEntity)


async def test_setup_adds_both_entities_when_authenticated():
    entry = _entry()
    entry.runtime_data = _coordinator(authenticated=True)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert len(added) == 2
    assert isinstance(added[0], VafabMiljoNotifyTimeEntity)
    assert isinstance(added[1], VafabMiljoReminderTimeEntity)


async def test_setup_adds_invoice_reminder_time_when_notifier_present():
    entry = _entry()
    notifier = Mock(reminder_time=time(18, 0))
    entry.runtime_data = _coordinator(authenticated=True, notifier=notifier)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert len(added) == 3
    assert isinstance(added[2], VafabMiljoInvoiceReminderTimeEntity)
    assert added[2].native_value == time(18, 0)


async def test_invoice_reminder_time_delegates_to_notifier():
    notifier = Mock(reminder_time=None)
    notifier.async_set_reminder_time = AsyncMock()
    entity = VafabMiljoInvoiceReminderTimeEntity(_entry(), notifier)
    entity.async_write_ha_state = Mock()
    assert entity.native_value == time(18, 0)  # default while the notifier has none

    await entity.async_set_value(time(9, 15))

    notifier.async_set_reminder_time.assert_awaited_once_with(time(9, 15))
    entity.async_write_ha_state.assert_called_once()


def test_defaults_to_1900():
    coordinator = _coordinator(authenticated=True)
    entity = VafabMiljoReminderTimeEntity(coordinator, _entry())
    assert entity.native_value == DEFAULT_REMINDER_TIME == time(19, 0)


async def test_set_value_calls_update_settings_and_updates_state():
    coordinator = _coordinator(authenticated=True)
    entity = VafabMiljoReminderTimeEntity(coordinator, _entry())
    entity.async_write_ha_state = Mock()

    await entity.async_set_value(time(20, 30))

    coordinator.client.update_settings.assert_awaited_with({"time": "20:30"})
    assert entity.native_value == time(20, 30)


async def test_restores_last_state_on_add_to_hass():
    coordinator = _coordinator(authenticated=True)
    entity = VafabMiljoReminderTimeEntity(coordinator, _entry())
    entity.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="07:00"))

    await entity.async_added_to_hass()

    assert entity.native_value == time(7, 0)


def test_notify_time_defaults_to_1800():
    entity = VafabMiljoNotifyTimeEntity(_entry())
    assert entity.native_value == DEFAULT_NOTIFY_TIME == time(18, 0)


async def test_notify_time_set_value_is_purely_local():
    entity = VafabMiljoNotifyTimeEntity(_entry())
    entity.async_write_ha_state = Mock()

    await entity.async_set_value(time(20, 15))

    assert entity.native_value == time(20, 15)
    entity.async_write_ha_state.assert_called_once()


async def test_notify_time_restores_last_state_on_add_to_hass():
    entity = VafabMiljoNotifyTimeEntity(_entry())
    entity.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="06:30"))

    await entity.async_added_to_hass()

    assert entity.native_value == time(6, 30)
