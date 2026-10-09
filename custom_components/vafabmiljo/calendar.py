"""Pickup calendar: one all-day event per upcoming pickup date, listing the bins collected that day.

The backend only exposes each bin type's *next* pickup, so the calendar shows
those dates and nothing further ahead - no guessing at the recurrence.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_PLANT_ID
from .coordinator import VafabMiljoCoordinator
from .sensor import _current_bins, _device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([VafabMiljoPickupCalendar(entry.runtime_data, entry)])


class VafabMiljoPickupCalendar(CoordinatorEntity[VafabMiljoCoordinator], CalendarEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "pickups"

    def __init__(self, coordinator: VafabMiljoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_PLANT_ID]}_pickups"
        self._attr_device_info = _device_info(entry)

    def _events(self) -> list[CalendarEvent]:
        by_day: dict[date, list[str]] = {}
        for bin_info in _current_bins(self.coordinator):
            by_day.setdefault(date.fromisoformat(bin_info["pickup_date"]), []).append(bin_info["type"])
        return [
            CalendarEvent(start=day, end=day + timedelta(days=1), summary=", ".join(types))
            for day, types in sorted(by_day.items())
        ]

    @property
    def event(self) -> CalendarEvent | None:
        today = dt_util.now().date()  # HA's timezone, not the host's
        return next((e for e in self._events() if e.start >= today), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        # all-day events run from local midnight to local midnight; compare as datetimes so a window
        # like 10:00-12:00 on a pickup day still overlaps that day's event
        return [
            e
            for e in self._events()
            if dt_util.start_of_local_day(e.start) < end_date and dt_util.start_of_local_day(e.end) > start_date
        ]
