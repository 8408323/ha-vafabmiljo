"""VafabMiljö time entities: the app's own reminder time, and a local-only one.

VafabMiljoReminderTimeEntity mirrors the app's own "Klockslag för
påminnelsenotiser" (30-minute increments) picker - optimistic/restore-on-
restart like switch.py, since there's no GET endpoint for current settings,
only POST /settings which just echoes back the patch's result.

VafabMiljoNotifyTimeEntity is unrelated to the app or BankID entirely: a
purely local time value for the user's own automations to trigger HA-side
notifications from (e.g. a `time` trigger with `at: time.xxx_notify_time`),
independent of - and possibly at a different time than - the app's own
reminder. This integration doesn't send any notification itself; the
per-bin-type "tomorrow" binary sensors (see binary_sensor.py) are the
condition, this is just the configurable time to check them at.
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
from .invoices import VafabMiljoInvoiceNotifier

DEFAULT_REMINDER_TIME = time(19, 0)  # matches the backend's own default for a new device
DEFAULT_NOTIFY_TIME = time(18, 0)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data[CONF_PLANT_ID])},
        name=f"{entry.data[CONF_ADDRESS]}, {entry.data[CONF_CITY]}",
        manufacturer="VafabMiljö",
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: VafabMiljoCoordinator = entry.runtime_data
    entities: list[TimeEntity] = [VafabMiljoNotifyTimeEntity(entry)]
    if coordinator.data.authenticated:
        entities.append(VafabMiljoReminderTimeEntity(coordinator, entry))
        if coordinator.invoice_notifier is not None:
            entities.append(VafabMiljoInvoiceReminderTimeEntity(entry, coordinator.invoice_notifier))
    async_add_entities(entities)


class VafabMiljoReminderTimeEntity(TimeEntity, RestoreEntity):
    """When to receive the app's own pickup-reminder notifications."""

    _attr_has_entity_name = True
    _attr_translation_key = "reminder_time"
    _attr_assumed_state = True
    _attr_should_poll = False

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_reminder_time"
        self._attr_device_info = _device_info(entry)
        self._attr_native_value = DEFAULT_REMINDER_TIME

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_native_value = time.fromisoformat(last_state.state)

    async def async_set_value(self, value: time) -> None:
        await self._coordinator.client.update_settings({REMINDER_TIME_FIELD: value.strftime("%H:%M")})
        self._attr_native_value = value
        self.async_write_ha_state()


class VafabMiljoNotifyTimeEntity(TimeEntity, RestoreEntity):
    """When to check the pickup-tomorrow binary sensors for your own HA automations.

    Purely local state - never sent to VafabMiljö, doesn't require BankID.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "notify_time"
    _attr_assumed_state = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_notify_time"
        self._attr_device_info = _device_info(entry)
        self._attr_native_value = DEFAULT_NOTIFY_TIME

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_native_value = time.fromisoformat(last_state.state)

    async def async_set_value(self, value: time) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()


class VafabMiljoInvoiceReminderTimeEntity(TimeEntity):
    """Time of day at which the day-before-due invoice reminder is delivered.

    The integration fires `vafabmiljo_invoice_due_reminder` at this time on the
    day before an unpaid invoice's due date.

    Purely local state, persisted by the invoice notifier itself (not
    RestoreEntity - the notifier needs the value before any entity exists,
    right at setup, to schedule the timer).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "invoice_reminder_time"
    _attr_should_poll = False  # only changes through its own set_value

    def __init__(self, entry: ConfigEntry, notifier: VafabMiljoInvoiceNotifier) -> None:
        self._notifier = notifier
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_invoice_reminder_time"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> time:
        return self._notifier.reminder_time

    async def async_set_value(self, value: time) -> None:
        try:
            await self._notifier.async_set_reminder_time(value)
        finally:
            # The notifier can persist the new time and still raise while
            # rescheduling; publish whatever it settled on either way, so the
            # entity never disagrees with storage.
            self.async_write_ha_state()
