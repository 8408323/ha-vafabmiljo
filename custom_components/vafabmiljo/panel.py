"""Serve the dashboard (frontend/ built to www/) as a sidebar panel."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

WWW = Path(__file__).parent / "www"
URL = "/vafabmiljo_static"
KEY = "vafabmiljo_panel"


async def async_register_panel(hass: HomeAssistant) -> None:
    # Once per HA run, however many addresses are set up: the panel itself switches between them.
    if hass.data.get(KEY) or not (WWW / "panel.js").exists():
        return
    hass.data[KEY] = True
    await hass.http.async_register_static_paths([StaticPathConfig(URL, str(WWW), cache_headers=False)])
    v = int((WWW / "panel.js").stat().st_mtime)  # cache-bust on each release
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="vafabmiljo-panel",
        frontend_url_path="vafabmiljo",
        module_url=f"{URL}/panel.js?v={v}",
        sidebar_title="VafabMiljö",
        sidebar_icon="mdi:trash-can-outline",
        require_admin=False,
        config={},
    )
