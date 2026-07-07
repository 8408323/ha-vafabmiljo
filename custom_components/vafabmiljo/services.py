"""VafabMiljö service actions.

Currently just download_invoice - fetching a PDF isn't something any entity
type fits well (it's a one-shot action with a file result, not state), so
it's exposed as a service instead and left for the user's own dashboard/
automation to trigger and link to.
"""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from .api import VafabMiljoError
from .const import DOMAIN

SERVICE_DOWNLOAD_INVOICE = "download_invoice"

_DOWNLOAD_INVOICE_SCHEMA = vol.Schema({vol.Required("invoice_id"): int})


def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_DOWNLOAD_INVOICE):
        return

    async def _async_download_invoice(call: ServiceCall) -> ServiceResponse:
        invoice_id = call.data["invoice_id"]
        # Not tied to a specific config entry/device - each account's session
        # is scoped server-side, so trying every loaded entry until one of
        # them actually has this invoice is simpler than resolving a target
        # entity back to its config entry, and works the same for the common
        # single-account case.
        for entry in hass.config_entries.async_entries(DOMAIN):
            coordinator = entry.runtime_data
            if coordinator is None:
                continue
            try:
                pdf_bytes = await coordinator.client.download_invoice(invoice_id)
            except VafabMiljoError:
                continue
            path = Path(hass.config.path("www", "vafabmiljo", f"invoice_{invoice_id}.pdf"))
            await hass.async_add_executor_job(_write_pdf, path, pdf_bytes)
            return {"path": f"/local/vafabmiljo/invoice_{invoice_id}.pdf"}
        raise HomeAssistantError(f"No VafabMiljö account could provide invoice {invoice_id}")

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_INVOICE,
        _async_download_invoice,
        schema=_DOWNLOAD_INVOICE_SCHEMA,
        # OPTIONAL, not ONLY - a plain dashboard tap_action calls this without
        # requesting a response, which HA rejects outright for ONLY. The PDF
        # landing in www/ is the real result either way; the returned path is
        # just a bonus for scripting/automations that do ask for it.
        supports_response=SupportsResponse.OPTIONAL,
    )


def _write_pdf(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
