"""Tests for the VafabMiljö download_invoice service action."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from vafabmiljo.api import VafabMiljoError
from vafabmiljo.const import DOMAIN
from vafabmiljo.services import SERVICE_DOWNLOAD_INVOICE, async_setup_services


def _entry(coordinator=None):
    entry = Mock()
    entry.runtime_data = coordinator
    return entry


def _coordinator(pdf_bytes: bytes | Exception):
    coordinator = Mock()
    coordinator.client = Mock()
    if isinstance(pdf_bytes, Exception):
        coordinator.client.download_invoice = AsyncMock(side_effect=pdf_bytes)
    else:
        coordinator.client.download_invoice = AsyncMock(return_value=pdf_bytes)
    return coordinator


def _hass_with_entries(entries) -> HomeAssistant:
    hass = HomeAssistant()
    hass.config_entries = Mock()
    hass.config_entries.async_entries = Mock(return_value=entries)
    return hass


async def test_service_registered_once():
    hass = _hass_with_entries([])
    async_setup_services(hass)
    first_handler = hass.services._handlers[(DOMAIN, SERVICE_DOWNLOAD_INVOICE)]
    async_setup_services(hass)
    assert hass.services._handlers[(DOMAIN, SERVICE_DOWNLOAD_INVOICE)] is first_handler


def _path_from_result(result: dict, tmp_path) -> Path:
    assert result["path"].startswith("/local/vafabmiljo/")
    assert result["path"].endswith(".pdf")
    assert result["expires_in_minutes"] == 10.0
    filename = result["path"].removeprefix("/local/vafabmiljo/")
    return Path(tmp_path) / "www" / "vafabmiljo" / filename


async def test_download_invoice_writes_file_and_returns_path(tmp_path):
    coordinator = _coordinator(b"%PDF-1.4 fake")
    hass = _hass_with_entries([_entry(coordinator)])
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    async_setup_services(hass)

    result = await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD_INVOICE, {"invoice_id": 123}, return_response=True)

    written = _path_from_result(result, tmp_path)
    assert written.read_bytes() == b"%PDF-1.4 fake"


async def test_download_invoice_filename_is_not_the_predictable_invoice_id(tmp_path):
    coordinator = _coordinator(b"%PDF-1.4 fake")
    hass = _hass_with_entries([_entry(coordinator)])
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    async_setup_services(hass)

    result = await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD_INVOICE, {"invoice_id": 123}, return_response=True)

    assert "123" not in result["path"]


async def test_download_invoice_schedules_cleanup_that_deletes_the_file(tmp_path):
    coordinator = _coordinator(b"%PDF-1.4 fake")
    hass = _hass_with_entries([_entry(coordinator)])
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    async_setup_services(hass)

    result = await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD_INVOICE, {"invoice_id": 123}, return_response=True)
    written = _path_from_result(result, tmp_path)
    assert written.exists()

    assert len(hass.scheduled_jobs) == 1
    await hass.scheduled_jobs[0](None)

    assert not written.exists()


async def test_download_invoice_skips_entries_without_coordinator(tmp_path):
    coordinator = _coordinator(b"%PDF-1.4 fake")
    hass = _hass_with_entries([_entry(None), _entry(coordinator)])
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    async_setup_services(hass)

    result = await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD_INVOICE, {"invoice_id": 5}, return_response=True)

    written = _path_from_result(result, tmp_path)
    assert written.read_bytes() == b"%PDF-1.4 fake"


async def test_download_invoice_tries_next_entry_on_error(tmp_path):
    failing = _coordinator(VafabMiljoError("not this account"))
    working = _coordinator(b"%PDF-1.4 fake")
    hass = _hass_with_entries([_entry(failing), _entry(working)])
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    async_setup_services(hass)

    result = await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD_INVOICE, {"invoice_id": 7}, return_response=True)

    written = _path_from_result(result, tmp_path)
    assert written.read_bytes() == b"%PDF-1.4 fake"


async def test_download_invoice_raises_when_no_entry_has_it():
    failing = _coordinator(VafabMiljoError("nope"))
    hass = _hass_with_entries([_entry(failing)])
    async_setup_services(hass)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD_INVOICE, {"invoice_id": 9}, return_response=True)


async def test_service_call_directly_via_service_call_object():
    hass = _hass_with_entries([])
    async_setup_services(hass)
    handler = hass.services._handlers[(DOMAIN, SERVICE_DOWNLOAD_INVOICE)]
    with pytest.raises(HomeAssistantError):
        await handler(ServiceCall({"invoice_id": 1}))
