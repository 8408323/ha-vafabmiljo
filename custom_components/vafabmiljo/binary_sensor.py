"""VafabMiljö BankID connectivity sensor and per-bin-type pickup-tomorrow sensors."""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import CONF_ADDRESS, CONF_CITY, CONF_PLANT_ID, CONF_SESSION_COOKIE, DOMAIN
from .coordinator import VafabMiljoCoordinator


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data[CONF_PLANT_ID])},
        name=f"{entry.data[CONF_ADDRESS]}, {entry.data[CONF_CITY]}",
        manufacturer="VafabMiljö",
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: VafabMiljoCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []

    # A session_cookie having ever been set means BankID was configured for this
    # entry at some point - show connectivity even if the session has since
    # expired (that's exactly what this entity is for).
    if entry.data.get(CONF_SESSION_COOKIE):
        entities.append(VafabMiljoConnectedBinarySensor(coordinator, entry))

    if coordinator.data.pickups:
        for bin_info in coordinator.data.pickups[0].get("bins", []):
            entities.append(VafabMiljoPickupTomorrowBinarySensor(coordinator, entry, bin_info["type"]))

    async_add_entities(entities)


class VafabMiljoConnectedBinarySensor(CoordinatorEntity[VafabMiljoCoordinator], BinarySensorEntity):
    """Whether the BankID session is currently active."""

    _attr_has_entity_name = True
    _attr_translation_key = "bankid_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_bankid_connected"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.authenticated


class VafabMiljoPickupTomorrowBinarySensor(CoordinatorEntity[VafabMiljoCoordinator], BinarySensorEntity):
    """Whether this bin type needs to go out tonight for tomorrow's pickup.

    Meant as a building block for the user's own automations - notifications,
    lighting cues, etc. - rather than something this integration sends itself.
    """

    _attr_has_entity_name = True
    # icons.json only covers translation_key-based entities; this one's name is
    # dynamic (the bin type itself), so the icon is set directly instead.
    _attr_icon = "mdi:calendar-alert-outline"

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry, bin_type: str) -> None:
        super().__init__(coordinator)
        self._bin_type = bin_type
        self._attr_name = f"{bin_type} tomorrow"
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_pickup_tomorrow_{slugify(bin_type)}"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data.pickups:
            return False
        tomorrow = date.today() + timedelta(days=1)
        for bin_info in self.coordinator.data.pickups[0].get("bins", []):
            if bin_info["type"] == self._bin_type:
                return date.fromisoformat(bin_info["pickup_date"]) == tomorrow
        return False
