"""VafabMiljö sensor platform.

Entity set is decided once at setup time from whatever the first refresh
returned (bin types for the bound address, invoice/contract data if BankID is
connected). A genuinely new bin type appearing later needs a reload to show up
- acceptable for a waste-collection calendar that doesn't change shape often.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import CONF_ADDRESS, CONF_CITY, CONF_PLANT_ID, DOMAIN
from .coordinator import VafabMiljoCoordinator


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data[CONF_PLANT_ID])},
        name=f"{entry.data[CONF_ADDRESS]}, {entry.data[CONF_CITY]}",
        manufacturer="VafabMiljö",
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: VafabMiljoCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    for bin_info in _current_bins(coordinator):
        entities.append(VafabMiljoPickupSensor(coordinator, entry, bin_info["type"]))

    if coordinator.data.authenticated:
        entities.append(VafabMiljoInvoiceSensor(coordinator, entry))
        for contract in (coordinator.data.sanitation or {}).get("contracts", []):
            if contract.get("fee", {}).get("price"):
                entities.append(VafabMiljoContractFeeSensor(coordinator, entry, contract))
        if coordinator.data.properties:
            entities.append(VafabMiljoPropertySensor(coordinator, entry))
        if (coordinator.data.parameters or {}).get("ordersAvailable"):
            entities.append(VafabMiljoAvailableOrdersSensor(coordinator, entry))
        if (coordinator.data.parameters or {}).get("complaintsAvailable"):
            entities.append(VafabMiljoAvailableComplaintsSensor(coordinator, entry))

    async_add_entities(entities)


def _current_bins(coordinator: VafabMiljoCoordinator) -> list[dict[str, Any]]:
    if not coordinator.data.pickups:
        return []
    return coordinator.data.pickups[0].get("bins", [])


class VafabMiljoPickupSensor(CoordinatorEntity[VafabMiljoCoordinator], SensorEntity):
    """Next pickup date for one bin type (e.g. Restavfall, Matavfall)."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry, bin_type: str) -> None:
        super().__init__(coordinator)
        self._bin_type = bin_type
        self._attr_name = bin_type
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_pickup_{slugify(bin_type)}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> date | None:
        for bin_info in _current_bins(self.coordinator):
            if bin_info["type"] == self._bin_type:
                return date.fromisoformat(bin_info["pickup_date"])
        return None


class VafabMiljoInvoiceSensor(CoordinatorEntity[VafabMiljoCoordinator], SensorEntity):
    """The most recent invoice - amount as state, full list as an attribute."""

    _attr_has_entity_name = True
    _attr_translation_key = "latest_invoice"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "SEK"

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_latest_invoice"
        self._attr_device_info = _device_info(entry)

    @property
    def _invoices(self) -> list[dict[str, Any]]:
        return (self.coordinator.data.invoices or {}).get("data", [])

    @property
    def native_value(self) -> float | None:
        invoices = self._invoices
        return invoices[0]["item"]["amount"] if invoices else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        invoices = self._invoices
        if not invoices:
            return {}
        latest = invoices[0]["item"]
        return {
            "invoice_date": latest.get("invoiceDate"),
            "due_date": latest.get("invoiceExpirationDate"),
            "payment_status": latest.get("paymentStatus"),
            "ocr_number": latest.get("ocrNumber"),
            "invoice_count": len(invoices),
        }


class VafabMiljoContractFeeSensor(CoordinatorEntity[VafabMiljoCoordinator], SensorEntity):
    """A waste-collection contract's recurring fee (e.g. the fixed base charge)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry, contract: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._contract_id = contract["id"]
        self._attr_name = contract.get("description", "").strip() or f"Contract {contract['id']}"
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_contract_{contract['id']}_fee"
        self._attr_device_info = _device_info(entry)
        # A rate like "kr/år", not a plain currency amount - SensorDeviceClass.MONETARY
        # requires an ISO 4217 currency unit, which this isn't.
        self._attr_native_unit_of_measurement = contract.get("fee", {}).get("unit")

    def _contract(self) -> dict[str, Any] | None:
        contracts = (self.coordinator.data.sanitation or {}).get("contracts", [])
        return next((c for c in contracts if c["id"] == self._contract_id), None)

    @property
    def native_value(self) -> float | None:
        contract = self._contract()
        return contract["fee"]["price"] if contract else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        contract = self._contract()
        if not contract:
            return {}
        return {
            "type": contract.get("type"),
            "pickups_per_year": contract.get("pickupsPerYear"),
            "unit": contract.get("fee", {}).get("unit"),
        }


class VafabMiljoPropertySensor(CoordinatorEntity[VafabMiljoCoordinator], SensorEntity):
    """The property (fastighetsbeteckning) this account/address is registered under."""

    _attr_has_entity_name = True
    _attr_translation_key = "property"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_property"
        self._attr_device_info = _device_info(entry)

    @property
    def _current(self) -> dict[str, Any]:
        return (self.coordinator.data.properties or {}).get("current", {})

    @property
    def native_value(self) -> str | None:
        return self._current.get("designation")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        current = self._current
        if not current:
            return {}
        return {
            "zip": current.get("zip"),
            "services": current.get("services"),
            "environment": current.get("environment"),
        }


class VafabMiljoAvailableOrdersSensor(CoordinatorEntity[VafabMiljoCoordinator], SensorEntity):
    """How many order types (e.g. bin-size changes, extra pickups) are available to request.

    Informational only - the app's actual order *submission* endpoint was never
    captured, so this integration can't place orders, only report what's offered.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "available_orders"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_available_orders"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.available_orders)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"titles": [o.get("title") for o in self.coordinator.data.available_orders]}


class VafabMiljoAvailableComplaintsSensor(CoordinatorEntity[VafabMiljoCoordinator], SensorEntity):
    """How many complaint types (e.g. missed pickup) are available to file.

    Informational only - see VafabMiljoAvailableOrdersSensor for why submission
    isn't implemented.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "available_complaints"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_available_complaints"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.available_complaints)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"descriptions": [c.get("description") for c in self.coordinator.data.available_complaints]}
