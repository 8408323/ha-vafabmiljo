"""VafabMiljö notification-preference switches.

There's no GET endpoint for the current settings - only POST /settings, which
both applies a patch and echoes back the full resulting state. So these are
optimistic, restore-on-restart entities (same pattern used in ha-plejd for
device-side state with no read-back): we trust our own last command rather
than polling for ground truth.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_ADDRESS, CONF_CITY, CONF_PLANT_ID, DOMAIN, NOTIFICATION_SETTINGS
from .coordinator import VafabMiljoCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: VafabMiljoCoordinator = entry.runtime_data
    if not coordinator.data.authenticated:
        return
    async_add_entities(
        VafabMiljoNotificationSwitch(coordinator, entry, key, field) for key, field in NOTIFICATION_SETTINGS.items()
    )


class VafabMiljoNotificationSwitch(SwitchEntity, RestoreEntity):
    """One notification-type toggle (garbage pickup, news, ...)."""

    _attr_has_entity_name = True
    _attr_translation_key = "notification"
    _attr_assumed_state = True

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry, key: str, field: str) -> None:
        self._coordinator = coordinator
        self._field = field
        self._attr_translation_placeholders = {"kind": key}
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_notify_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_PLANT_ID])},
            name=f"{entry.data[CONF_ADDRESS]}, {entry.data[CONF_CITY]}",
            manufacturer="VafabMiljö",
        )
        self._attr_is_on = True  # matches the backend's own default for a new device

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._coordinator.client.update_settings({self._field: True})
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coordinator.client.update_settings({self._field: False})
        self._attr_is_on = False
        self.async_write_ha_state()
