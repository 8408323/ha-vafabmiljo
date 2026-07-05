"""The VafabMiljö integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VafabMiljoClient
from .const import CONF_DEVICE_BEARER, CONF_DEVICE_UUID, CONF_SESSION_COOKIE
from .coordinator import VafabMiljoCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = VafabMiljoClient(
        session,
        entry.data[CONF_DEVICE_UUID],
        entry.data[CONF_DEVICE_BEARER],
        entry.data.get(CONF_SESSION_COOKIE),
    )
    coordinator = VafabMiljoCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
