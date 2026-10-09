"""Tests for the pickup calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import Mock

from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util
from vafabmiljo.calendar import VafabMiljoPickupCalendar, async_setup_entry
from vafabmiljo.coordinator import VafabMiljoData

TODAY = dt_util.now().date()


def _calendar(bins: list[dict]) -> VafabMiljoPickupCalendar:
    entry = ConfigEntry(data={"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"})
    coordinator = Mock()
    coordinator.data = VafabMiljoData(pickups=[{"bins": bins}] if bins else [])
    entry.runtime_data = coordinator
    return VafabMiljoPickupCalendar(coordinator, entry)


def _bin(kind: str, days: int) -> dict:
    return {"type": kind, "pickup_date": (TODAY + timedelta(days=days)).isoformat()}


async def test_setup_adds_one_calendar():
    entry = ConfigEntry(data={"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1"})
    entry.runtime_data = Mock(data=VafabMiljoData())
    added = []
    await async_setup_entry(None, entry, added.extend)
    assert len(added) == 1 and added[0]._attr_unique_id == "p1_pickups"


def test_bins_on_the_same_day_share_one_event_and_the_next_one_is_current():
    cal = _calendar([_bin("Plast och papper", 10), _bin("Restavfall", 3), _bin("Matavfall", 3), _bin("Gammal", -1)])
    assert cal.event.summary == "Restavfall, Matavfall"
    assert cal.event.start == TODAY + timedelta(days=3)
    assert cal.event.end == TODAY + timedelta(days=4)


def test_no_pickups_means_no_event():
    assert _calendar([]).event is None


async def test_get_events_returns_only_the_requested_window():
    cal = _calendar([_bin("Restavfall", 3), _bin("Plast och papper", 10)])
    start = datetime.combine(TODAY, datetime.min.time())
    events = await cal.async_get_events(None, start, start + timedelta(days=7))
    assert [e.summary for e in events] == ["Restavfall"]


def test_today_comes_from_home_assistants_timezone(monkeypatch):
    # 00:30 on the 19th in Stockholm is still the 18th in UTC: the 18th's pickup must already be over
    from datetime import timezone

    monkeypatch.setattr(dt_util, "NOW_OVERRIDE", datetime(2026, 10, 19, 0, 30, tzinfo=timezone(timedelta(hours=2))))
    cal = _calendar(
        [{"type": "Restavfall", "pickup_date": "2026-10-18"}, {"type": "Matavfall", "pickup_date": "2026-10-19"}]
    )
    assert cal.event.summary == "Matavfall"
