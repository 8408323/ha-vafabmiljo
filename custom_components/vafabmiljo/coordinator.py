"""Data coordinator for the VafabMiljö integration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VafabMiljoAuthError, VafabMiljoClient, VafabMiljoError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class VafabMiljoData:
    """Everything the coordinator fetched on the last successful refresh."""

    pickups: list[dict[str, Any]] = field(default_factory=list)
    authenticated: bool = False
    invoices: dict[str, Any] | None = None
    sanitation: dict[str, Any] | None = None
    properties: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None
    orders: dict[str, Any] | None = None
    complaints: dict[str, Any] | None = None

    @property
    def current_property_id(self) -> int | None:
        return (self.properties or {}).get("current", {}).get("id")

    def _flatten_by_current_property(self, data: dict[str, Any] | None) -> list[dict[str, Any]]:
        # orders/complaints are keyed "<property_id>": {"<contract_id>": [...]}
        property_id = self.current_property_id
        if not data or property_id is None:
            return []
        by_contract = data.get(str(property_id), {})
        return [item for items in by_contract.values() for item in items]

    @property
    def available_orders(self) -> list[dict[str, Any]]:
        return self._flatten_by_current_property(self.orders)

    @property
    def available_complaints(self) -> list[dict[str, Any]]:
        return self._flatten_by_current_property(self.complaints)


class VafabMiljoCoordinator(DataUpdateCoordinator[VafabMiljoData]):
    """Polls the VafabMiljö backend for pickup schedule and (if logged in) account data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: VafabMiljoClient) -> None:
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> VafabMiljoData:
        try:
            pickups = await self.client.list_next_pickup()
        except VafabMiljoError as err:
            raise UpdateFailed(f"Failed to fetch the pickup schedule: {err}") from err

        if not self.client.session_cookie:
            return VafabMiljoData(pickups=pickups, authenticated=False)

        # The real app calls this periodically to extend the session. It does
        # *not* fix a stuck 202 "waiting" endpoint (tested directly against
        # the backend: still 202 twenty seconds after a successful call) -
        # keep it only for its own documented purpose, not as a workaround.
        try:
            await self.client.keep_alive()
        except VafabMiljoAuthError as err:
            raise ConfigEntryAuthFailed("The VafabMiljö BankID session expired") from err
        except VafabMiljoError as err:
            _LOGGER.warning("Failed to keep the BankID session alive: %s", err)

        invoices = await self._try_fetch("invoices", self.client.get_invoices)
        sanitation = await self._try_fetch("sanitation", self.client.get_sanitation)
        properties = await self._try_fetch("properties", self.client.get_properties)
        parameters = await self._try_fetch("parameters", self.client.get_parameters)
        orders = None
        complaints = None
        if parameters:
            if parameters.get("ordersAvailable"):
                orders = await self._try_fetch("orders", self.client.get_orders)
            if parameters.get("complaintsAvailable"):
                complaints = await self._try_fetch("complaints", self.client.get_complaints)

        return VafabMiljoData(
            pickups=pickups,
            authenticated=True,
            invoices=invoices,
            sanitation=sanitation,
            properties=properties,
            parameters=parameters,
            orders=orders,
            complaints=complaints,
        )

    async def _try_fetch(self, name: str, fetch: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any] | None:
        """Fetch one piece of account data, tolerating a stuck/failing endpoint.

        Each of these is independent account data, not required for the
        pickup-schedule sensors that work without login at all - one endpoint
        being persistently broken (e.g. an account whose /services/invoices
        never leaves the backend's 202 "waiting" state) shouldn't take down
        the whole integration.
        """
        try:
            return await fetch()
        except VafabMiljoAuthError as err:
            # The BankID session expired - this affects every authenticated
            # endpoint equally, so it's worth surfacing as a real reauth.
            raise ConfigEntryAuthFailed("The VafabMiljö BankID session expired") from err
        except VafabMiljoError as err:
            _LOGGER.warning("Failed to fetch %s: %s", name, err)
            return None
