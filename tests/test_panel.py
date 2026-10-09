"""Tests for the sidebar panel registration."""

from __future__ import annotations

from homeassistant.components import panel_custom
from homeassistant.core import HomeAssistant
from vafabmiljo import panel


async def test_registers_once_with_a_cache_busted_module_url(tmp_path, monkeypatch):
    (tmp_path / "panel.js").write_text("")
    monkeypatch.setattr(panel, "WWW", tmp_path)
    panel_custom.panels.clear()
    hass = HomeAssistant()

    await panel.async_register_panel(hass)
    await panel.async_register_panel(hass)  # a second address must not register it again

    assert len(panel_custom.panels) == 1
    assert panel_custom.panels[0]["frontend_url_path"] == "vafabmiljo"
    assert panel_custom.panels[0]["module_url"].startswith("/vafabmiljo_static/panel.js?v=")
    assert [p.path for p in hass.static_paths] == [str(tmp_path)]


async def test_skips_registration_when_the_frontend_is_not_built(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "WWW", tmp_path)
    panel_custom.panels.clear()
    await panel.async_register_panel(HomeAssistant())
    assert panel_custom.panels == []


async def test_a_failing_registration_does_not_break_setup_and_can_retry(tmp_path, monkeypatch, caplog):
    (tmp_path / "panel.js").write_text("")
    monkeypatch.setattr(panel, "WWW", tmp_path)
    panel_custom.panels.clear()
    calls = []

    async def _fail_once(hass, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ValueError("Overwriting panel vafabmiljo")
        panel_custom.panels.append(kwargs)

    monkeypatch.setattr(panel_custom, "async_register_panel", _fail_once)
    hass = HomeAssistant()

    await panel.async_register_panel(hass)  # logs, does not raise
    assert "Could not register the VafabMiljö panel" in caplog.text
    await panel.async_register_panel(hass)  # a later setup tries again; static path only once
    assert len(panel_custom.panels) == 1 and len(hass.static_paths) == 1
