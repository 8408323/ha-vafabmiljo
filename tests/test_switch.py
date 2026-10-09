"""Tests for VafabMiljö notification switches."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.config_entries import ConfigEntry
from vafabmiljo.const import NOTIFICATION_SETTINGS
from vafabmiljo.coordinator import VafabMiljoData
from vafabmiljo.switch import VafabMiljoNotificationSwitch, async_setup_entry


def _entry() -> ConfigEntry:
    return ConfigEntry(data={"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"})


def _coordinator(authenticated: bool) -> Mock:
    coordinator = Mock()
    coordinator.data = VafabMiljoData(pickups=[], authenticated=authenticated)
    coordinator.client = AsyncMock()
    return coordinator


async def test_setup_skips_switches_when_not_authenticated():
    entry = _entry()
    entry.runtime_data = _coordinator(authenticated=False)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert added == []


async def test_setup_adds_one_switch_per_notification_setting():
    entry = _entry()
    entry.runtime_data = _coordinator(authenticated=True)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert len(added) == len(NOTIFICATION_SETTINGS)


async def test_turn_on_calls_update_settings_and_updates_state():
    coordinator = _coordinator(authenticated=True)
    switch = VafabMiljoNotificationSwitch(coordinator, _entry(), "garbage", "garbage")
    switch.async_write_ha_state = Mock()

    await switch.async_turn_off()
    coordinator.client.update_settings.assert_awaited_with({"garbage": False})
    assert switch.is_on is False

    await switch.async_turn_on()
    coordinator.client.update_settings.assert_awaited_with({"garbage": True})
    assert switch.is_on is True


async def test_restores_last_state_on_add_to_hass():
    coordinator = _coordinator(authenticated=True)
    switch = VafabMiljoNotificationSwitch(coordinator, _entry(), "garbage", "garbage")
    switch.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="off"))

    await switch.async_added_to_hass()

    assert switch.is_on is False


async def test_unavailable_while_the_session_is_expired_and_follows_the_coordinator():
    coordinator = _coordinator(authenticated=True)
    entity = VafabMiljoNotificationSwitch(coordinator, _entry(), "garbage", "garbage")
    await entity.async_added_to_hass()
    listener = coordinator.async_add_listener.call_args.args[0]
    assert entity.available is True
    coordinator.data.session_expired = True
    assert entity.available is False
    listener()  # a coordinator update rewrites the state
    assert entity.state_writes == 1
