"""VafabMiljö notification-preference switches.

The current values come from GET /settings on every refresh (the device's
own settings, as the app shows them); POST /settings changes them. Until the
first refresh has them - or if that endpoint fails - the entity falls back to
its own last command, restored across restarts.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
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
    _attr_assumed_state = True

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry, key: str, field: str) -> None:
        self._coordinator = coordinator
        self._field = field
        self._attr_translation_key = f"notify_{key}"
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_notify_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_PLANT_ID])},
            name=f"{entry.data[CONF_ADDRESS]}, {entry.data[CONF_CITY]}",
            manufacturer="VafabMiljö",
        )
        self._attr_is_on = True  # matches the backend's own default for a new device

    @property
    def is_on(self) -> bool | None:
        value = (self._coordinator.data.settings or {}).get(self._field)
        return value if isinstance(value, bool) else self._attr_is_on

    @property
    def available(self) -> bool:
        # the backend rejects settings changes while the BankID session is expired
        return not self._coordinator.data.session_expired

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))
        # only a real on/off: "unavailable" (saved while the BankID session was expired) must not turn into off
        if (last_state := await self.async_get_last_state()) is not None and last_state.state in (STATE_ON, STATE_OFF):
            self._attr_is_on = last_state.state == STATE_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._coordinator.client.update_settings({self._field: True})
        self._coordinator.async_apply_setting(self._field, True)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coordinator.client.update_settings({self._field: False})
        self._coordinator.async_apply_setting(self._field, False)
        self._attr_is_on = False
        self.async_write_ha_state()
