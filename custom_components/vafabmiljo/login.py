"""The Mina sidor BankID login, started from the panel (Settings).

One login at a time per entry, polled in the background; the panel asks for its status every couple
of seconds to show the animated QR and the "BankID on this device" link. On success the Mina sidor
credentials are saved to the entry and the entry reloads, which brings in the account entities
(invoices, fees, ...). See minasidor.py for the login itself.
"""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import VafabMiljoError
from .config_flow import bankid_autostart_desktop_url, bankid_autostart_url
from .const import (
    BANKID_POLL_INTERVAL,
    BANKID_POLL_TIMEOUT,
    CONF_MS_ACCESS,
    CONF_MS_REFRESH,
    CONF_MS_REFRESH_EXPIRES,
    CONF_SESSION_COOKIE,
    DOMAIN,
)
from .minasidor import MinaSidorLogin, MinaSidorLoginError, qr_image

KEY = f"{DOMAIN}_logins"


class PanelLogin:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        # its own cookie jar: Criipto keeps the BankID order in cookies, and nothing else may share them
        self._login = MinaSidorLogin(async_create_clientsession(hass, cookie_jar=CookieJar()))
        self.status = "waiting"  # waiting / done / failed
        self.hint: str | None = None
        self.task: asyncio.Task | None = None

    async def async_start(self) -> None:
        await self._login.start()
        self.task = self._hass.async_create_background_task(self._poll(), f"{DOMAIN} Mina sidor login")

    async def _poll(self) -> None:
        deadline = asyncio.get_running_loop().time() + BANKID_POLL_TIMEOUT
        try:
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(BANKID_POLL_INTERVAL)
                if await self._login.poll():
                    self._save()
                    return
            self.status, self.hint = "failed", "timeout"
        except MinaSidorLoginError as err:
            self.status, self.hint = "failed", err.hint
        except VafabMiljoError as err:
            self.status, self.hint = "failed", str(err)

    def _save(self) -> None:
        creds = self._login.credentials
        assert creds is not None
        data = {
            **self._entry.data,
            CONF_MS_REFRESH: creds.refresh_cookie,
            CONF_MS_REFRESH_EXPIRES: creds.refresh_expires,
            CONF_MS_ACCESS: creds.access_token,
        }
        data.pop(CONF_SESSION_COOKIE, None)  # the app's own login is no longer used
        # the entry's update listener reloads it with the new login
        self._hass.config_entries.async_update_entry(self._entry, data=data)
        self.status = "done"
        # a pending reauth flow (started when the login ran out) is answered now
        flows = self._hass.config_entries.flow.async_progress_by_handler(
            DOMAIN, match_context={"source": "reauth", "entry_id": self._entry.entry_id}
        )
        for flow in flows:
            self._hass.config_entries.flow.async_abort(flow["flow_id"])

    def cancel(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()

    def as_dict(self) -> dict[str, Any]:
        token = self._login.autostart_token
        waiting = self.status == "waiting"
        return {
            "status": self.status,
            "hint": self.hint,
            "qr": qr_image(self._login.qr) if self._login.qr and waiting else None,
            # open the BankID app on the same device: the panel uses the universal link on a phone or
            # tablet and the bankid:/// scheme on a computer
            "autostart": bankid_autostart_url(token) if token and waiting else None,
            "autostart_desktop": bankid_autostart_desktop_url(token) if token and waiting else None,
        }


def _entry(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> ConfigEntry | None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "No VafabMiljö entry with that id")
        return None
    return entry


@websocket_api.websocket_command({vol.Required("type"): "vafabmiljo/login/start", vol.Required("entry_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_start(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    if (entry := _entry(hass, connection, msg)) is None:
        return
    logins: dict[str, PanelLogin] = hass.data.setdefault(KEY, {})
    # one start at a time per entry: a double click must not leave an orphan login polling (which could
    # later overwrite the cookie) because both awaited the backend before either was stored
    async with hass.data.setdefault(f"{KEY}_locks", {}).setdefault(entry.entry_id, asyncio.Lock()):
        if old := logins.pop(entry.entry_id, None):
            old.cancel()
        login = PanelLogin(hass, entry)
        try:
            await login.async_start()
        except VafabMiljoError as err:
            connection.send_error(msg["id"], "cannot_connect", str(err))
            return
        logins[entry.entry_id] = login
    connection.send_result(msg["id"], login.as_dict())


@websocket_api.websocket_command({vol.Required("type"): "vafabmiljo/login/status", vol.Required("entry_id"): str})
@websocket_api.require_admin
@callback
def ws_status(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    login = hass.data.get(KEY, {}).get(msg["entry_id"])
    connection.send_result(msg["id"], login.as_dict() if login else {"status": "none"})


@websocket_api.websocket_command({vol.Required("type"): "vafabmiljo/login/cancel", vol.Required("entry_id"): str})
@websocket_api.require_admin
@callback
def ws_cancel(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    if login := hass.data.get(KEY, {}).pop(msg["entry_id"], None):
        login.cancel()
    connection.send_result(msg["id"], {"ok": True})


@callback
def async_cancel_login(hass: HomeAssistant, entry_id: str) -> None:
    """Stop a running panel login of an entry that is being unloaded or removed.

    A finished one is kept: a successful login reloads the entry itself, and the panel still has
    to read "done" afterwards.
    """
    logins = hass.data.get(KEY, {})
    if (login := logins.get(entry_id)) is not None and login.status == "waiting":
        login.cancel()
        del logins[entry_id]


COMMANDS = (ws_start, ws_status, ws_cancel)
