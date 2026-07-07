"""VafabMiljö service actions.

Currently just download_invoice - fetching a PDF isn't something any entity
type fits well (it's a one-shot action with a file result, not state), so
it's exposed as a service instead and left for the user's own dashboard/
automation to trigger and link to.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from pathlib import Path

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

from .api import VafabMiljoError
from .const import DOMAIN

SERVICE_DOWNLOAD_INVOICE = "download_invoice"

_DOWNLOAD_INVOICE_SCHEMA = vol.Schema(
    {
        # Coerce, not a bare int - a dashboard tap_action fills this via a
        # Jinja template (e.g. the latest invoice's id from the sensor
        # attribute), which always renders as a string. voluptuous's bare
        # `int` requires an actual int and rejects "4287069" outright;
        # Coerce(int) calls int() on it like the rest of the stack expects.
        vol.Required("invoice_id"): vol.Coerce(int),
    }
)

# www/ is served over HTTP with no authentication at all - the filename itself
# is the only thing standing between "you have an HA session" and "you have
# the link". A random token instead of the (small, guessable) invoice_id, plus
# deleting the file shortly after, keeps the exposure window and the set of
# guessable URLs small rather than leaving invoices sitting there permanently
# at a predictable path.
_FILE_RETENTION = timedelta(minutes=10)


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
            filename = f"{secrets.token_urlsafe(16)}.pdf"
            path = Path(hass.config.path("www", "vafabmiljo", filename))
            await hass.async_add_executor_job(_write_pdf, path, pdf_bytes)
            async_call_later(hass, _FILE_RETENTION, _make_cleanup_job(hass, path))
            return {
                "path": f"/local/vafabmiljo/{filename}",
                "expires_in_minutes": _FILE_RETENTION.total_seconds() / 60,
            }
        raise HomeAssistantError(f"No VafabMiljö account could provide invoice {invoice_id}")

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_INVOICE,
        _async_download_invoice,
        schema=_DOWNLOAD_INVOICE_SCHEMA,
        # OPTIONAL, not ONLY - a plain dashboard tap_action calls this without
        # requesting a response, which HA rejects outright for ONLY. The file
        # landing in www/ is the real result either way; the returned path is
        # just a bonus for scripting/automations that do ask for it.
        supports_response=SupportsResponse.OPTIONAL,
    )


def _make_cleanup_job(hass: HomeAssistant, path: Path):
    async def _cleanup(_now) -> None:
        await hass.async_add_executor_job(lambda: path.unlink(missing_ok=True))

    return _cleanup


def _write_pdf(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
