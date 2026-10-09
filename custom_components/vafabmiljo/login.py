"""BankID login started from the panel (Settings), instead of only during setup or a reauth flow.

One login at a time per entry, polled in the background; the panel asks for its status every
couple of seconds to show the rotating QR. On success the new session cookie is saved to the
entry and the entry reloads, which brings in the account entities (invoices, fees, ...).
"""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VafabMiljoClient, VafabMiljoError
from .config_flow import bankid_failure_hint, is_authenticated, qr_data_uri
from .const import (
    BANKID_POLL_INTERVAL,
    BANKID_POLL_TIMEOUT,
    CONF_DEVICE_BEARER,
    CONF_DEVICE_UUID,
    CONF_SESSION_COOKIE,
    DOMAIN,
)

KEY = f"{DOMAIN}_logins"


class PanelLogin:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        # a fresh client without the old cookie: the login must not ride on an expired session
        self._client = VafabMiljoClient(
            async_get_clientsession(hass), entry.data[CONF_DEVICE_UUID], entry.data[CONF_DEVICE_BEARER]
        )
        self.status = "waiting"  # waiting / done / failed
        self.hint: str | None = None
        self.qr = ""
        self.token: str | None = None
        self.task: asyncio.Task | None = None

    async def async_start(self) -> None:
        auth = await self._client.start_bankid_auth()
        self.qr, self.token = auth.get("qr") or "", auth.get("token")
        self.task = self._hass.async_create_background_task(self._poll(), f"{DOMAIN} BankID login")

    async def _poll(self) -> None:
        deadline = asyncio.get_running_loop().time() + BANKID_POLL_TIMEOUT
        try:
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(BANKID_POLL_INTERVAL)
                state = await self._client.poll_bankid_status()
                if is_authenticated(state):
                    self._hass.config_entries.async_update_entry(
                        self._entry, data={**self._entry.data, CONF_SESSION_COOKIE: self._client.session_cookie}
                    )
                    # the entry's update listener reloads it; a pending reauth flow (started when the
                    # session expired) is now answered, and finishing it later could overwrite this cookie
                    self.status = "done"
                    self._abort_reauth()
                    return
                if hint := bankid_failure_hint(state):
                    self.status, self.hint = "failed", hint
                    return
                if state.get("qr"):
                    self.qr = state["qr"]
            self.status, self.hint = "failed", "timeout"
        except VafabMiljoError as err:
            self.status, self.hint = "failed", str(err)

    def _abort_reauth(self) -> None:
        flows = self._hass.config_entries.flow.async_progress_by_handler(
            DOMAIN, match_context={"source": "reauth", "entry_id": self._entry.entry_id}
        )
        for flow in flows:
            self._hass.config_entries.flow.async_abort(flow["flow_id"])

    def cancel(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "hint": self.hint,
            "qr": qr_data_uri(self.qr) if self.qr and self.status == "waiting" else None,
            # opens the BankID app on the same device (phone/tablet)
            "autostart": f"bankid:///?autostarttoken={self.token}&redirect=null" if self.token else None,
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
    """Stop a panel login of an entry that is being unloaded or removed."""
    if login := hass.data.get(KEY, {}).pop(entry_id, None):
        login.cancel()


COMMANDS = (ws_start, ws_status, ws_cancel)
