"""Tests for the integration's setup/unload entry points."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from vafabmiljo import _async_reload_entry, async_remove_entry, async_setup_entry, async_unload_entry
from vafabmiljo.const import CONF_DEVICE_BEARER, CONF_DEVICE_UUID, CONF_SESSION_COOKIE
from vafabmiljo.coordinator import VafabMiljoCoordinator


def _hass() -> HomeAssistant:
    hass = HomeAssistant()
    hass.data["test_session"] = object()
    hass.config_entries = AsyncMock()
    return hass


def _entry() -> ConfigEntry:
    return ConfigEntry(
        data={
            CONF_DEVICE_UUID: "dev1",
            CONF_DEVICE_BEARER: "bearer1",
            CONF_SESSION_COOKIE: "cookie1",
        }
    )


async def test_setup_entry_creates_coordinator_and_forwards_platforms(monkeypatch):
    from vafabmiljo.coordinator import VafabMiljoData

    async def _refresh(self):
        self.data = VafabMiljoData(pickups=[], authenticated=False)

    monkeypatch.setattr(VafabMiljoCoordinator, "async_config_entry_first_refresh", _refresh)
    hass = _hass()
    entry = _entry()

    result = await async_setup_entry(hass, entry)

    assert result is True
    assert isinstance(entry.runtime_data, VafabMiljoCoordinator)
    # anonymous entry: no BankID, no invoices, no notifier
    assert entry.runtime_data.invoice_notifier is None
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()
    assert len(entry._unload_callbacks) == 1


async def test_setup_entry_creates_notifier_for_authenticated_entry(monkeypatch):
    from vafabmiljo.coordinator import VafabMiljoData

    async def _refresh(self):
        self.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": []})

    monkeypatch.setattr(VafabMiljoCoordinator, "async_config_entry_first_refresh", _refresh)
    hass = _hass()
    entry = _entry()

    await async_setup_entry(hass, entry)

    notifier = entry.runtime_data.invoice_notifier
    assert notifier is not None
    # unload is wired through the entry's own hooks (update listener + notifier)
    assert len(entry._unload_callbacks) == 2
    assert entry._unload_callbacks[0] == notifier.async_unload


async def test_reload_entry_calls_hass_reload():
    hass = _hass()
    entry = _entry()

    await _async_reload_entry(hass, entry)

    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


async def test_unload_entry_delegates_to_hass():
    hass = _hass()
    hass.config_entries.async_unload_platforms.return_value = True
    entry = _entry()

    result = await async_unload_entry(hass, entry)

    assert result is True
    hass.config_entries.async_unload_platforms.assert_awaited_once()


async def test_setup_failure_after_notifier_tears_it_down(monkeypatch):
    from vafabmiljo.coordinator import VafabMiljoData

    async def _refresh(self):
        self.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": []})

    monkeypatch.setattr(VafabMiljoCoordinator, "async_config_entry_first_refresh", _refresh)
    hass = _hass()
    hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError("platform boom")
    entry = _entry()

    import pytest

    with pytest.raises(RuntimeError):
        await async_setup_entry(hass, entry)

    coordinator = entry.runtime_data
    assert coordinator.invoice_notifier is None
    assert coordinator._listeners == []  # notifier's listener was removed


async def test_notifier_setup_failure_tears_it_down(monkeypatch):
    from vafabmiljo.coordinator import VafabMiljoData
    from vafabmiljo.invoices import VafabMiljoInvoiceNotifier

    async def _refresh(self):
        self.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": []})

    monkeypatch.setattr(VafabMiljoCoordinator, "async_config_entry_first_refresh", _refresh)

    async def _boom(self):
        self._unsub_listener = self._coordinator.async_add_listener(self._handle_coordinator_update)
        raise OSError("store write failed")

    monkeypatch.setattr(VafabMiljoInvoiceNotifier, "async_setup", _boom)
    hass = _hass()
    entry = _entry()

    import pytest

    with pytest.raises(OSError):
        await async_setup_entry(hass, entry)

    assert entry.runtime_data.invoice_notifier is None
    assert entry.runtime_data._listeners == []


async def test_remove_entry_deletes_the_invoice_store():
    hass = _hass()
    hass.data["_stores"] = {"vafabmiljo.test_entry.invoices": {"announced": [1]}}
    entry = _entry()

    await async_remove_entry(hass, entry)

    assert hass.data["_stores"] == {}


async def test_download_service_is_registered_before_the_notifier_can_fire(monkeypatch):
    """An event fired by the notifier's first check may be acted on immediately."""
    from vafabmiljo.const import DOMAIN
    from vafabmiljo.coordinator import VafabMiljoData
    from vafabmiljo.invoices import VafabMiljoInvoiceNotifier

    async def _refresh(self):
        self.data = VafabMiljoData(pickups=[], authenticated=True, invoices={"data": []})

    monkeypatch.setattr(VafabMiljoCoordinator, "async_config_entry_first_refresh", _refresh)

    hass = _hass()
    seen: dict[str, bool] = {}
    original_setup = VafabMiljoInvoiceNotifier.async_setup

    async def _record(self):
        seen["service_registered"] = hass.services.has_service(DOMAIN, "download_invoice")
        await original_setup(self)

    monkeypatch.setattr(VafabMiljoInvoiceNotifier, "async_setup", _record)

    await async_setup_entry(hass, _entry())

    assert seen["service_registered"] is True
