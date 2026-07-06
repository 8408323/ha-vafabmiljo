"""Tests for the integration's setup/unload entry points."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from vafabmiljo import async_setup_entry, async_unload_entry
from vafabmiljo.const import CONF_DEVICE_BEARER, CONF_DEVICE_UUID, CONF_SESSION_COOKIE
from vafabmiljo.coordinator import VafabMiljoCoordinator


def _hass() -> HomeAssistant:
    hass = HomeAssistant()
    hass.data["test_session"] = object()
    hass.config_entries = AsyncMock()
    return hass


def _entry() -> ConfigEntry:
    return ConfigEntry(
        data={
            CONF_DEVICE_UUID: "dev1",
            CONF_DEVICE_BEARER: "bearer1",
            CONF_SESSION_COOKIE: "cookie1",
        }
    )


async def test_setup_entry_creates_coordinator_and_forwards_platforms(monkeypatch):
    monkeypatch.setattr(VafabMiljoCoordinator, "async_config_entry_first_refresh", AsyncMock(return_value=None))
    hass = _hass()
    entry = _entry()

    result = await async_setup_entry(hass, entry)

    assert result is True
    assert isinstance(entry.runtime_data, VafabMiljoCoordinator)
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()


async def test_unload_entry_delegates_to_hass():
    hass = _hass()
    hass.config_entries.async_unload_platforms.return_value = True
    entry = _entry()

    result = await async_unload_entry(hass, entry)

    assert result is True
    hass.config_entries.async_unload_platforms.assert_awaited_once()
