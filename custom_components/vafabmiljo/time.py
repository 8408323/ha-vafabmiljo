"""VafabMiljö reminder-time entity.

Mirrors the app's own "Klockslag för påminnelsenotiser" (30-minute increments)
picker. Same optimistic/restore-on-restart pattern as switch.py - there's no
GET endpoint for the current settings, only POST /settings which just echoes
back the patch's result.
"""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_ADDRESS, CONF_CITY, CONF_PLANT_ID, DOMAIN, REMINDER_TIME_FIELD
from .coordinator import VafabMiljoCoordinator

DEFAULT_REMINDER_TIME = time(19, 0)  # matches the backend's own default for a new device


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: VafabMiljoCoordinator = entry.runtime_data
    if not coordinator.data.authenticated:
        return
    async_add_entities([VafabMiljoReminderTimeEntity(coordinator, entry)])


class VafabMiljoReminderTimeEntity(TimeEntity, RestoreEntity):
    """When to receive pickup-reminder notifications."""

    _attr_has_entity_name = True
    _attr_translation_key = "reminder_time"
    _attr_assumed_state = True

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_reminder_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_PLANT_ID])},
            name=f"{entry.data[CONF_ADDRESS]}, {entry.data[CONF_CITY]}",
            manufacturer="VafabMiljö",
        )
        self._attr_native_value = DEFAULT_REMINDER_TIME

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_native_value = time.fromisoformat(last_state.state)

    async def async_set_value(self, value: time) -> None:
        await self._coordinator.client.update_settings({REMINDER_TIME_FIELD: value.strftime("%H:%M")})
        self._attr_native_value = value
        self.async_write_ha_state()
