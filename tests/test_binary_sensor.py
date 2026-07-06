"""Tests for the VafabMiljö BankID connectivity binary sensor."""

from __future__ import annotations

from unittest.mock import Mock

from homeassistant.config_entries import ConfigEntry
from vafabmiljo.binary_sensor import VafabMiljoConnectedBinarySensor, async_setup_entry
from vafabmiljo.coordinator import VafabMiljoData


def _entry(**data) -> ConfigEntry:
    return ConfigEntry(data={"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1", **data})


def _coordinator(authenticated: bool) -> Mock:
    coordinator = Mock()
    coordinator.data = VafabMiljoData(pickups=[], authenticated=authenticated)
    return coordinator


async def test_setup_skips_entity_without_session_cookie():
    entry = _entry()
    entry.runtime_data = _coordinator(authenticated=False)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert added == []


async def test_setup_adds_entity_when_session_cookie_was_ever_set():
    entry = _entry(session_cookie="abc123")
    entry.runtime_data = _coordinator(authenticated=True)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert len(added) == 1
    assert isinstance(added[0], VafabMiljoConnectedBinarySensor)


def test_is_on_reflects_current_authenticated_state():
    entry = _entry(session_cookie="abc123")
    sensor_on = VafabMiljoConnectedBinarySensor(_coordinator(authenticated=True), entry)
    assert sensor_on.is_on is True

    sensor_off = VafabMiljoConnectedBinarySensor(_coordinator(authenticated=False), entry)
    assert sensor_off.is_on is False
