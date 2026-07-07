"""Tests for the VafabMiljö binary sensors."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import Mock

from homeassistant.config_entries import ConfigEntry
from vafabmiljo.binary_sensor import (
    VafabMiljoConnectedBinarySensor,
    VafabMiljoPickupTomorrowBinarySensor,
    async_setup_entry,
)
from vafabmiljo.coordinator import VafabMiljoData

TOMORROW = date.today() + timedelta(days=1)
TODAY = date.today()


def _entry(**data) -> ConfigEntry:
    return ConfigEntry(data={"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1", **data})


def _coordinator(authenticated: bool, pickups: list | None = None) -> Mock:
    coordinator = Mock()
    coordinator.data = VafabMiljoData(pickups=pickups or [], authenticated=authenticated)
    return coordinator


async def test_setup_skips_connected_sensor_without_session_cookie():
    entry = _entry()
    entry.runtime_data = _coordinator(authenticated=False)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert added == []


async def test_setup_adds_connected_sensor_when_session_cookie_was_ever_set():
    entry = _entry(session_cookie="abc123")
    entry.runtime_data = _coordinator(authenticated=True)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert len(added) == 1
    assert isinstance(added[0], VafabMiljoConnectedBinarySensor)


async def test_setup_adds_one_pickup_tomorrow_sensor_per_bin_type():
    entry = _entry()
    pickups = [{"bins": [{"type": "Matavfall", "pickup_date": TOMORROW.isoformat()}]}]
    entry.runtime_data = _coordinator(authenticated=False, pickups=pickups)
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)
    assert len(added) == 1
    assert isinstance(added[0], VafabMiljoPickupTomorrowBinarySensor)


def test_is_on_reflects_current_authenticated_state():
    entry = _entry(session_cookie="abc123")
    sensor_on = VafabMiljoConnectedBinarySensor(_coordinator(authenticated=True), entry)
    assert sensor_on.is_on is True

    sensor_off = VafabMiljoConnectedBinarySensor(_coordinator(authenticated=False), entry)
    assert sensor_off.is_on is False


def test_pickup_tomorrow_is_on_when_date_matches():
    entry = _entry()
    pickups = [{"bins": [{"type": "Matavfall", "pickup_date": TOMORROW.isoformat()}]}]
    sensor = VafabMiljoPickupTomorrowBinarySensor(
        _coordinator(authenticated=False, pickups=pickups), entry, "Matavfall"
    )
    assert sensor.is_on is True


def test_pickup_tomorrow_is_off_when_date_does_not_match():
    entry = _entry()
    pickups = [{"bins": [{"type": "Matavfall", "pickup_date": TODAY.isoformat()}]}]
    sensor = VafabMiljoPickupTomorrowBinarySensor(
        _coordinator(authenticated=False, pickups=pickups), entry, "Matavfall"
    )
    assert sensor.is_on is False


def test_pickup_tomorrow_is_off_when_bin_type_missing():
    entry = _entry()
    pickups = [{"bins": [{"type": "Restavfall", "pickup_date": TOMORROW.isoformat()}]}]
    sensor = VafabMiljoPickupTomorrowBinarySensor(
        _coordinator(authenticated=False, pickups=pickups), entry, "Matavfall"
    )
    assert sensor.is_on is False


def test_pickup_tomorrow_is_off_when_no_pickups_at_all():
    entry = _entry()
    sensor = VafabMiljoPickupTomorrowBinarySensor(_coordinator(authenticated=False, pickups=[]), entry, "Matavfall")
    assert sensor.is_on is False
