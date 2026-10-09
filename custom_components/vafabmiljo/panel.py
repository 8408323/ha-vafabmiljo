"""Serve the dashboard (frontend/ built to www/) as a sidebar panel."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

WWW = Path(__file__).parent / "www"
URL = "/vafabmiljo_static"
_LOGGER = logging.getLogger(__name__)
KEY = "vafabmiljo_panel"


async def async_register_panel(hass: HomeAssistant) -> None:
    # Once per HA run, however many addresses are set up: the panel itself switches between them.
    if hass.data.get(KEY) or not (WWW / "panel.js").exists():
        return
    # The panel is optional: a failure here (e.g. another panel already owns the URL) must not take
    # the entities down with it, and KEY is only set once it worked so a later setup can retry.
    try:
        if not hass.data.get(f"{KEY}_static"):
            await hass.http.async_register_static_paths([StaticPathConfig(URL, str(WWW), cache_headers=False)])
            hass.data[f"{KEY}_static"] = True  # static routes can't be registered twice
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
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Could not register the VafabMiljö panel; the integration works without it")
        return
    hass.data[KEY] = True
