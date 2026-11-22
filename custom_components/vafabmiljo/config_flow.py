"""Config flow for the VafabMiljö integration.

Setup only picks your address (works anonymously, no login) - that's enough for the pickup
schedule. The BankID login to Mina sidor, which adds invoices, fees and the property, is done in
the VafabMiljö panel (Settings -> Account), where the animated BankID QR and the "BankID on this
device" link can update live; a config-flow dialog can't refresh a QR, and BankID rejects a stale
one. A reauth flow therefore only points to the panel.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from urllib.parse import quote

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .api import VafabMiljoClient, VafabMiljoError
from .const import (
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
from .session import async_create_session

_LOGGER = logging.getLogger(__name__)


def bankid_autostart_url(token: str) -> str:
    """Open the BankID app on this phone/tablet (BankID's universal link, what their docs say to use on mobile).

    redirect=null: BankID returns to nothing when done, the user switches back to HA (Android
    usually goes back by itself). The login is polled server-side the whole time, so that's enough.
    """
    return f"https://app.bankid.com/?autostarttoken={quote(token, safe='')}&redirect=null"


def bankid_autostart_desktop_url(token: str) -> str:
    """The same for BankID on a computer, which only answers to the bankid:/// scheme."""
    return f"bankid:///?autostarttoken={quote(token, safe='')}&redirect=null"


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

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._device_uuid = str(uuid.uuid4()).replace("-", "")
            self._device_bearer = DEVICE_AUTH_KEY
            session = async_create_session(self.hass)
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
            assert self._client is not None
            await self._client.set_address(self._selected["plant_id"])
            return self._create_entry()
        options = [{"value": a["plant_id"], "label": f"{a['address']}, {a['city']}"} for a in self._matches]
        schema = vol.Schema({vol.Required(CONF_PLANT_ID): SelectSelector(SelectSelectorConfig(options=options))})
        return self.async_show_form(step_id="address", data_schema=schema)

    def _create_entry(self) -> ConfigFlowResult:
        assert self._client is not None
        return self.async_create_entry(
            title=f"{self._selected['address']}, {self._selected['city']}",
            data={
                CONF_DEVICE_UUID: self._device_uuid,
                CONF_DEVICE_BEARER: self._device_bearer,
                CONF_ADDRESS: self._selected["address"],
                CONF_CITY: self._selected["city"],
                CONF_PLANT_ID: self._selected["plant_id"],
            },
        )

    # -- Reauth: the Mina sidor login ran out - it is renewed in the panel -----

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_abort(reason="reauth_use_panel")
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({}))

    # -- Reconfigure: change the bound address without removing the entry -----

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if self._client is None:
            session = async_create_session(self.hass)
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
