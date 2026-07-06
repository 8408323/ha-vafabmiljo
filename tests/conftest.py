"""Pytest configuration - make the vafabmiljo integration importable without the full HA stack.

The `homeassistant` PyPI mirror available in this dev environment is frozen at a
version that predates several APIs this integration uses (`entry.runtime_data`,
`async_show_progress_done`, modern `ConfigFlowResult`). Rather than write against
a HA version we can't actually run, this stubs the minimal set of HA symbols the
integration imports, mirroring the approach used in ha-plejd's conftest.py.
"""

from __future__ import annotations

import enum
import os
import re
import sys
import types
from typing import Any, Generic, TypeVar

_CC = os.path.join(os.path.dirname(__file__), "..", "custom_components")
sys.path.insert(0, os.path.abspath(_CC))

_T = TypeVar("_T")


def _install_stub_homeassistant() -> None:
    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    # -- homeassistant.const --------------------------------------------------
    const = types.ModuleType("homeassistant.const")

    class Platform(str, enum.Enum):
        SENSOR = "sensor"
        SWITCH = "switch"

    class EntityCategory(str, enum.Enum):
        DIAGNOSTIC = "diagnostic"
        CONFIG = "config"

    const.Platform = Platform
    const.EntityCategory = EntityCategory
    sys.modules["homeassistant.const"] = const

    # -- homeassistant.core ----------------------------------------------------
    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        def __init__(self) -> None:
            self.data: dict[str, Any] = {}

    def callback(func):
        return func

    core.HomeAssistant = HomeAssistant
    core.callback = callback
    sys.modules["homeassistant.core"] = core

    # -- homeassistant.exceptions ------------------------------------------------
    exceptions = types.ModuleType("homeassistant.exceptions")

    class ConfigEntryAuthFailed(Exception):
        pass

    class HomeAssistantError(Exception):
        pass

    exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    exceptions.HomeAssistantError = HomeAssistantError
    sys.modules["homeassistant.exceptions"] = exceptions

    # -- homeassistant.config_entries -------------------------------------------
    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:
        def __init__(self, data: dict[str, Any] | None = None, options: dict[str, Any] | None = None) -> None:
            self.data = data or {}
            self.options = options or {}
            self.entry_id = "test_entry"
            self.runtime_data: Any = None

    class FlowResultType(str, enum.Enum):
        FORM = "form"
        CREATE_ENTRY = "create_entry"
        ABORT = "abort"
        SHOW_PROGRESS = "show_progress"
        SHOW_PROGRESS_DONE = "show_progress_done"

    ConfigFlowResult = dict

    class _FlowBase:
        def __init__(self) -> None:
            self.hass: HomeAssistant | None = None
            self.context: dict[str, Any] = {}
            self.flow_id = "test_flow"
            self._reauth_entry: ConfigEntry | None = None
            self._unique_id: str | None = None

        async def async_set_unique_id(self, unique_id: str) -> None:
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            return None

        def _get_reauth_entry(self) -> ConfigEntry:
            assert self._reauth_entry is not None
            return self._reauth_entry

        def async_show_form(self, *, step_id, data_schema=None, errors=None, description_placeholders=None):
            return {
                "type": FlowResultType.FORM,
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
                "description_placeholders": description_placeholders,
            }

        def async_create_entry(self, *, title, data):
            return {"type": FlowResultType.CREATE_ENTRY, "title": title, "data": data}

        def async_abort(self, *, reason):
            return {"type": FlowResultType.ABORT, "reason": reason}

        def async_show_progress(self, *, step_id, progress_action, description_placeholders=None, progress_task=None):
            return {
                "type": FlowResultType.SHOW_PROGRESS,
                "step_id": step_id,
                "progress_action": progress_action,
                "description_placeholders": description_placeholders,
            }

        def async_show_progress_done(self, *, next_step_id):
            return {"type": FlowResultType.SHOW_PROGRESS_DONE, "next_step_id": next_step_id}

        def async_update_reload_and_abort(self, entry: ConfigEntry, *, data_updates=None, reason: str):
            if data_updates:
                entry.data.update(data_updates)
            return {"type": FlowResultType.ABORT, "reason": reason}

    class ConfigFlow(_FlowBase):
        def __init_subclass__(cls, *, domain: str | None = None, **kwargs) -> None:
            super().__init_subclass__(**kwargs)
            cls.domain = domain

    class OptionsFlow(_FlowBase):
        pass

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlow = ConfigFlow
    config_entries.ConfigFlowResult = ConfigFlowResult
    config_entries.OptionsFlow = OptionsFlow
    config_entries.FlowResultType = FlowResultType
    sys.modules["homeassistant.config_entries"] = config_entries

    # -- homeassistant.helpers.* -------------------------------------------------
    helpers = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")

    def async_get_clientsession(hass):
        return hass.data["test_session"]

    aiohttp_client.async_get_clientsession = async_get_clientsession
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client

    selector_mod = types.ModuleType("homeassistant.helpers.selector")

    class SelectSelectorConfig:
        def __init__(self, options=None, multiple=False) -> None:
            self.options = options or []
            self.multiple = multiple

    class SelectSelector:
        def __init__(self, config: SelectSelectorConfig) -> None:
            self.config = config

        def __call__(self, value):
            # Real HA selectors are voluptuous-callable validators; for tests we
            # just pass the value through rather than re-validating against options.
            return value

    selector_mod.SelectSelector = SelectSelector
    selector_mod.SelectSelectorConfig = SelectSelectorConfig
    sys.modules["homeassistant.helpers.selector"] = selector_mod

    device_registry = types.ModuleType("homeassistant.helpers.device_registry")

    class DeviceInfo(dict):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)

    device_registry.DeviceInfo = DeviceInfo
    sys.modules["homeassistant.helpers.device_registry"] = device_registry

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator(Generic[_T]):
        def __init__(self, hass, logger, *, name: str, update_interval=None) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data: _T | None = None
            self._listeners: list = []

        async def _async_update_data(self) -> _T:  # pragma: no cover - overridden by subclasses
            raise NotImplementedError

        async def async_config_entry_first_refresh(self) -> None:
            self.data = await self._async_update_data()

        async def async_refresh(self) -> None:
            self.data = await self._async_update_data()

        def async_add_listener(self, update_callback):
            self._listeners.append(update_callback)

            def _remove() -> None:
                self._listeners.remove(update_callback)

            return _remove

    class CoordinatorEntity(Generic[_T]):
        def __init__(self, coordinator: DataUpdateCoordinator) -> None:
            self.coordinator = coordinator

    update_coordinator.UpdateFailed = UpdateFailed
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

    restore_state = types.ModuleType("homeassistant.helpers.restore_state")

    class RestoreEntity:
        async def async_added_to_hass(self) -> None:
            return None

        async def async_get_last_state(self):
            return None

    restore_state.RestoreEntity = RestoreEntity
    sys.modules["homeassistant.helpers.restore_state"] = restore_state

    util = types.ModuleType("homeassistant.util")

    def slugify(value: str) -> str:
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9]+", "_", value)
        return value.strip("_")

    util.slugify = slugify
    sys.modules["homeassistant.util"] = util

    # -- homeassistant.components.* ----------------------------------------------
    components = types.ModuleType("homeassistant.components")
    sys.modules["homeassistant.components"] = components

    sensor_mod = types.ModuleType("homeassistant.components.sensor")

    class SensorDeviceClass(str, enum.Enum):
        DATE = "date"
        MONETARY = "monetary"

    class SensorEntity:
        pass

    sensor_mod.SensorDeviceClass = SensorDeviceClass
    sensor_mod.SensorEntity = SensorEntity
    sys.modules["homeassistant.components.sensor"] = sensor_mod

    switch_mod = types.ModuleType("homeassistant.components.switch")

    class SwitchEntity:
        _attr_is_on: bool | None = None

        @property
        def is_on(self) -> bool | None:
            return self._attr_is_on

    switch_mod.SwitchEntity = SwitchEntity
    sys.modules["homeassistant.components.switch"] = switch_mod

    diagnostics_mod = types.ModuleType("homeassistant.components.diagnostics")
    REDACTED = "**REDACTED**"

    def async_redact_data(data, to_redact):
        if isinstance(data, dict):
            return {k: (REDACTED if k in to_redact else async_redact_data(v, to_redact)) for k, v in data.items()}
        if isinstance(data, list):
            return [async_redact_data(v, to_redact) for v in data]
        return data

    diagnostics_mod.async_redact_data = async_redact_data
    sys.modules["homeassistant.components.diagnostics"] = diagnostics_mod


try:
    import homeassistant.config_entries  # noqa: F401
except ImportError:
    _install_stub_homeassistant()
