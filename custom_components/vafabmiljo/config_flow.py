"""Config flow for the VafabMiljö integration.

Setup has two parts: pick your address (works anonymously, no login), then
optionally connect your account via BankID (QR shown in the HA UI) to also
get invoices and contract data. BankID progress uses HA's async_show_progress
with a real progress_task (required since HA Core 2024.8 - omitting it falls
back to a deprecated polling workaround that, on a modern HA instance, does
not reliably refresh the QR or ever re-enter the step once BankID confirms).
Each poll sleeps BANKID_POLL_INTERVAL first, then the flow manager
automatically re-invokes the *_bankid_wait step when that task completes.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .api import VafabMiljoAuthError, VafabMiljoClient, VafabMiljoError
from .const import (
    BANKID_POLL_INTERVAL,
    CONF_ADDRESS,
    CONF_CITY,
    CONF_DEVICE_BEARER,
    CONF_DEVICE_UUID,
    CONF_PLANT_ID,
    CONF_SCAN_INTERVAL,
    CONF_SESSION_COOKIE,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEVICE_AUTH_KEY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _qr_markdown(svg: str) -> str:
    # BankID's QR SVG draws only black modules with no background rect, which
    # renders as transparent (showing HA's own theme through it, dark or
    # light) unless we give it one ourselves.
    if "<svg" in svg and "<rect" not in svg:
        svg = svg.replace(">", '><rect width="100%" height="100%" fill="#ffffff"/>', 1)
    encoded = base64.b64encode(svg.encode()).decode()
    return f"![BankID QR code](data:image/svg+xml;base64,{encoded})"


def _is_authenticated(status: dict[str, Any]) -> bool:
    return status.get("status") == "authenticated successfully"


class VafabMiljoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for VafabMiljö."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> VafabMiljoOptionsFlow:
        return VafabMiljoOptionsFlow(config_entry)

    def __init__(self) -> None:
        self._device_uuid: str = ""
        self._device_bearer: str = ""
        self._client: VafabMiljoClient | None = None
        self._matches: list[dict[str, Any]] = []
        self._selected: dict[str, Any] = {}
        self._qr_svg: str = ""
        self._bankid_task: asyncio.Task[dict[str, Any]] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._device_uuid = str(uuid.uuid4()).replace("-", "")
            self._device_bearer = DEVICE_AUTH_KEY
            session = async_get_clientsession(self.hass)
            self._client = VafabMiljoClient(session, self._device_uuid, self._device_bearer)
            try:
                await self._client.register(model="Home Assistant", os_version="n/a")
                self._matches = (await self._client.search_addresses(user_input["query"].strip()))[:25]
            except VafabMiljoError:
                errors["base"] = "cannot_connect"
            else:
                if not self._matches:
                    errors["base"] = "no_matches"
                else:
                    return await self.async_step_address()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("query"): str}),
            errors=errors,
        )

    async def async_step_address(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._selected = next(a for a in self._matches if a["plant_id"] == user_input[CONF_PLANT_ID])
            # Keyed on the address, not the (freshly generated, always-unique)
            # device_uuid, so adding the same address twice is what gets blocked -
            # different addresses/properties are meant to coexist as separate entries.
            await self.async_set_unique_id(self._selected["plant_id"])
            self._abort_if_unique_id_configured()
            return await self.async_step_bankid_start()
        options = [{"value": a["plant_id"], "label": f"{a['address']}, {a['city']}"} for a in self._matches]
        schema = vol.Schema({vol.Required(CONF_PLANT_ID): SelectSelector(SelectSelectorConfig(options=options))})
        return self.async_show_form(step_id="address", data_schema=schema)

    async def async_step_bankid_start(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            assert self._client is not None
            await self._client.set_address(self._selected["plant_id"])
            if not user_input.get("enable_bankid", True):
                return self._create_entry()
            auth = await self._client.start_bankid_auth()
            self._qr_svg = auth.get("qr", "")
            return await self.async_step_bankid_wait()
        schema = vol.Schema({vol.Optional("enable_bankid", default=True): bool})
        return self.async_show_form(step_id="bankid_start", data_schema=schema)

    async def async_step_bankid_wait(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_bankid_wait(
            step_id="bankid_wait",
            failure_step_id="bankid_failed",
            success_step_id="finish",
            catch=VafabMiljoError,
        )

    async def _poll_bankid_after_delay(self) -> dict[str, Any]:
        assert self._client is not None
        await asyncio.sleep(BANKID_POLL_INTERVAL)
        return await self._client.poll_bankid_status()

    async def _async_bankid_wait(
        self, *, step_id: str, failure_step_id: str, success_step_id: str, catch: type[Exception]
    ) -> ConfigFlowResult:
        # Modern HA re-invokes this step automatically when progress_task
        # completes (no progress_task is deprecated since HA Core 2024.8 and,
        # on top of no longer refreshing the QR reliably, can get stuck
        # showing progress forever without ever calling this step again).
        if self._bankid_task is None:
            self._bankid_task = self.hass.async_create_task(self._poll_bankid_after_delay())
            return self.async_show_progress(
                step_id=step_id,
                progress_action="waiting_for_bankid",
                description_placeholders={"qr_code": _qr_markdown(self._qr_svg)},
                progress_task=self._bankid_task,
            )
        task, self._bankid_task = self._bankid_task, None
        try:
            status = task.result()
        except catch:
            return self.async_show_progress_done(next_step_id=failure_step_id)
        if _is_authenticated(status):
            return self.async_show_progress_done(next_step_id=success_step_id)
        if status.get("qr"):
            self._qr_svg = status["qr"]
        self._bankid_task = self.hass.async_create_task(self._poll_bankid_after_delay())
        return self.async_show_progress(
            step_id=step_id,
            progress_action="waiting_for_bankid",
            description_placeholders={"qr_code": _qr_markdown(self._qr_svg)},
            progress_task=self._bankid_task,
        )

    async def async_step_bankid_failed(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="bankid_start",
            data_schema=vol.Schema({vol.Optional("enable_bankid", default=True): bool}),
            errors={"base": "cannot_connect"},
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self._create_entry()

    def _create_entry(self) -> ConfigFlowResult:
        assert self._client is not None
        return self.async_create_entry(
            title=f"{self._selected['address']}, {self._selected['city']}",
            data={
                CONF_DEVICE_UUID: self._device_uuid,
                CONF_DEVICE_BEARER: self._device_bearer,
                CONF_SESSION_COOKIE: self._client.session_cookie,
                CONF_ADDRESS: self._selected["address"],
                CONF_CITY: self._selected["city"],
                CONF_PLANT_ID: self._selected["plant_id"],
            },
        )

    # -- Reauth: the BankID session (vafab_session cookie) expired ------------

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        if self._client is None:
            session = async_get_clientsession(self.hass)
            self._client = VafabMiljoClient(
                session,
                entry.data[CONF_DEVICE_UUID],
                entry.data[CONF_DEVICE_BEARER],
            )
        if user_input is not None:
            auth = await self._client.start_bankid_auth()
            self._qr_svg = auth.get("qr", "")
            return await self.async_step_reauth_bankid_wait()
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({}))

    async def async_step_reauth_bankid_wait(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_bankid_wait(
            step_id="reauth_bankid_wait",
            failure_step_id="reauth_confirm",
            success_step_id="reauth_finish",
            catch=VafabMiljoAuthError,
        )

    async def async_step_reauth_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._client is not None
        entry = self._get_reauth_entry()
        return self.async_update_reload_and_abort(
            entry,
            data_updates={CONF_SESSION_COOKIE: self._client.session_cookie},
            reason="reauth_successful",
        )

    # -- Reconfigure: change the bound address without removing the entry -----

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if self._client is None:
            session = async_get_clientsession(self.hass)
            self._client = VafabMiljoClient(
                session,
                entry.data[CONF_DEVICE_UUID],
                entry.data[CONF_DEVICE_BEARER],
                entry.data.get(CONF_SESSION_COOKIE),
            )
        if user_input is not None:
            try:
                self._matches = (await self._client.search_addresses(user_input["query"].strip()))[:25]
            except VafabMiljoError:
                errors["base"] = "cannot_connect"
            else:
                if not self._matches:
                    errors["base"] = "no_matches"
                else:
                    return await self.async_step_reconfigure_address()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required("query"): str}),
            errors=errors,
        )

    async def async_step_reconfigure_address(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._client is not None
        if user_input is not None:
            selected = next(a for a in self._matches if a["plant_id"] == user_input[CONF_PLANT_ID])
            await self.async_set_unique_id(selected["plant_id"])
            # A different entry already at this address blocks the switch; this
            # entry's own current unique_id is ignored while reconfiguring it.
            self._abort_if_unique_id_configured()
            await self._client.set_address(selected["plant_id"])
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data_updates={
                    CONF_ADDRESS: selected["address"],
                    CONF_CITY: selected["city"],
                    CONF_PLANT_ID: selected["plant_id"],
                },
                reason="reconfigure_successful",
            )
        options = [{"value": a["plant_id"], "label": f"{a['address']}, {a['city']}"} for a in self._matches]
        schema = vol.Schema({vol.Required(CONF_PLANT_ID): SelectSelector(SelectSelectorConfig(options=options))})
        return self.async_show_form(step_id="reconfigure_address", data_schema=schema)


class VafabMiljoOptionsFlow(OptionsFlow):
    """Let the user override how often the coordinator polls."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self._entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        schema = vol.Schema(
            {vol.Optional(CONF_SCAN_INTERVAL, default=current): vol.All(vol.Coerce(int), vol.Range(min=5))}
        )
        return self.async_show_form(step_id="init", data_schema=schema)
