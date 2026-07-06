"""Tests for the VafabMiljö reminder-time entity."""

from __future__ import annotations

from datetime import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.config_entries import ConfigEntry
from vafabmiljo.coordinator import VafabMiljoData
from vafabmiljo.time import DEFAULT_REMINDER_TIME, VafabMiljoReminderTimeEntity, async_setup_entry


def _entry() -> ConfigEntry:
    return ConfigEntry(data={"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"})


def _coordinator(authenticated: bool) -> Mock:
    coordinator = Mock()
    coordinator.data = VafabMiljoData(pickups=[], authenticated=authenticated)
    coordinator.client = AsyncMock()
    return coordinator


async def test_setup_skips_entity_when_not_authenticated():
    entry = _entry()
    entry.runtime_data = _coordinator(authenticated=False)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert added == []


async def test_setup_adds_entity_when_authenticated():
    entry = _entry()
    entry.runtime_data = _coordinator(authenticated=True)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert len(added) == 1
    assert isinstance(added[0], VafabMiljoReminderTimeEntity)


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
