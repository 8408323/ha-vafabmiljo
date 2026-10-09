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
