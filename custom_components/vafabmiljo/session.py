"""The aiohttp session the VafabMiljö clients talk through.

Not Home Assistant's shared session: that one has a single cookie jar for every integration, and
aiohttp lets a cookie from the jar override the same cookie in the request's own Cookie header. The
jar keeps one vafab_session for the host - whichever response set it last - so a second entry, a
setup or reauth flow or a panel login would replace the entry's BankID session with its own, and the
next refresh was rejected as an expired login. VafabMiljoClient sends the cookie itself, so the
session it uses must not keep or add any (DummyCookieJar).
"""

from __future__ import annotations

from aiohttp import ClientSession, DummyCookieJar
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession


@callback
def async_create_session(hass: HomeAssistant) -> ClientSession:
    """A session without a cookie jar; created during entry setup it is closed when the entry unloads."""
    return async_create_clientsession(hass, cookie_jar=DummyCookieJar())
