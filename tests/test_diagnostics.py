"""Tests for VafabMiljö config entry diagnostics."""

from __future__ import annotations

from unittest.mock import Mock

from homeassistant.config_entries import ConfigEntry
from vafabmiljo.coordinator import VafabMiljoData
from vafabmiljo.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacts_identifying_data():
    entry = ConfigEntry(
        data={
            "device_uuid": "dev1",
            "device_bearer": "secret-bearer",
            "session_cookie": "secret-cookie",
            "address": "Testgatan 1",
            "city": "Teststad",
            "plant_id": "opaque-blob",
        }
    )
    coordinator = Mock()
    coordinator.data = VafabMiljoData(
        pickups=[{"bins": [{"type": "Restavfall"}, {"type": "Matavfall"}]}],
        authenticated=True,
        invoices={"data": [{"item": {"amount": 1}}, {"item": {"amount": 2}}]},
        sanitation={"contracts": [{"id": 1}]},
    )
    entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass=None, entry=entry)

    assert result["entry_data"]["device_bearer"] == "**REDACTED**"
    assert result["entry_data"]["session_cookie"] == "**REDACTED**"
    assert result["entry_data"]["address"] == "**REDACTED**"
    assert result["entry_data"]["city"] == "**REDACTED**"
    assert result["entry_data"]["plant_id"] == "**REDACTED**"
    assert result["entry_data"]["device_uuid"] == "dev1"  # not identifying on its own
    assert result["authenticated"] is True
    assert result["bin_types"] == ["Matavfall", "Restavfall"]
    assert result["invoice_count"] == 2
    assert result["sanitation_contract_count"] == 1
