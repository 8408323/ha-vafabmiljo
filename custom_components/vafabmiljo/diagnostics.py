"""Diagnostics for the VafabMiljö integration.

Downloadable config-entry diagnostics for troubleshooting. The device bearer and
BankID session cookie are credentials; the address/city/plant_id identify the
user's home. All of that is redacted - only non-identifying structure (counts,
bin type names) is exposed.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS, CONF_CITY, CONF_DEVICE_BEARER, CONF_PLANT_ID, CONF_SESSION_COOKIE
from .coordinator import VafabMiljoCoordinator

TO_REDACT = {
    CONF_DEVICE_BEARER,
    CONF_SESSION_COOKIE,
    CONF_ADDRESS,
    CONF_CITY,
    CONF_PLANT_ID,
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator: VafabMiljoCoordinator = entry.runtime_data
    data = coordinator.data
    bin_types = sorted({b["type"] for p in data.pickups for b in p.get("bins", [])})
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "authenticated": data.authenticated,
        "bin_types": bin_types,
        "invoice_count": len((data.invoices or {}).get("data", [])),
        "sanitation_contract_count": len((data.sanitation or {}).get("contracts", [])),
    }
