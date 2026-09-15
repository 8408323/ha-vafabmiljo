"""The VafabMiljö integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VafabMiljoClient
from .const import CONF_DEVICE_BEARER, CONF_DEVICE_UUID, CONF_SESSION_COOKIE
from .coordinator import VafabMiljoCoordinator
from .invoices import VafabMiljoInvoiceNotifier, async_remove_invoice_store
from .services import async_setup_services

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH, Platform.TIME]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = VafabMiljoClient(
        session,
        entry.data[CONF_DEVICE_UUID],
        entry.data[CONF_DEVICE_BEARER],
        entry.data.get(CONF_SESSION_COOKIE),
    )
    coordinator = VafabMiljoCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    if coordinator.data.authenticated:
        # Event-based new-invoice / due-reminder delivery (see invoices.py).
        # Only for BankID-connected entries: an anonymous one never sees an
        # invoice, and the notifier's coordinator listener would otherwise keep
        # the cloud polling alive even with every entity disabled. Torn down via
        # the entry's own unload hooks, so a failure later in setup can't leak it.
        notifier = VafabMiljoInvoiceNotifier(hass, entry, coordinator)
        coordinator.invoice_notifier = notifier
        entry.async_on_unload(notifier.async_unload)
    try:
        if coordinator.invoice_notifier is not None:
            await coordinator.invoice_notifier.async_setup()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
        async_setup_services(hass)
    except BaseException:
        # HA only runs on_unload callbacks for its own ConfigEntry* exceptions;
        # on any other failure the notifier (listener + timer) would leak and a
        # retried setup would create a second one on the same store.
        if coordinator.invoice_notifier is not None:
            coordinator.invoice_notifier.async_unload()
            coordinator.invoice_notifier = None
        raise
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # The scan-interval option only takes effect on the coordinator at
    # construction time, so a change needs a full reload to apply.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # The invoice notifier is unloaded through entry.async_on_unload (see setup).
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the per-entry persisted invoice state when the entry is deleted."""
    await async_remove_invoice_store(hass, entry)
