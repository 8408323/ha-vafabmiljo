"""VafabMiljö BankID connectivity sensor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, CONF_CITY, CONF_PLANT_ID, CONF_SESSION_COOKIE, DOMAIN
from .coordinator import VafabMiljoCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: VafabMiljoCoordinator = entry.runtime_data
    # A session_cookie having ever been set means BankID was configured for this
    # entry at some point - show connectivity even if the session has since
    # expired (that's exactly what this entity is for).
    if entry.data.get(CONF_SESSION_COOKIE):
        async_add_entities([VafabMiljoConnectedBinarySensor(coordinator, entry)])


class VafabMiljoConnectedBinarySensor(CoordinatorEntity[VafabMiljoCoordinator], BinarySensorEntity):
    """Whether the BankID session is currently active."""

    _attr_has_entity_name = True
    _attr_translation_key = "bankid_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_bankid_connected"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_PLANT_ID])},
            name=f"{entry.data[CONF_ADDRESS]}, {entry.data[CONF_CITY]}",
            manufacturer="VafabMiljö",
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.authenticated
