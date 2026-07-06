"""Data coordinator for the VafabMiljö integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VafabMiljoAuthError, VafabMiljoClient, VafabMiljoError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

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
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
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

        try:
            invoices = await self.client.get_invoices()
            sanitation = await self.client.get_sanitation()
            properties = await self.client.get_properties()
            parameters = await self.client.get_parameters()
            orders = await self.client.get_orders() if parameters.get("ordersAvailable") else None
            complaints = await self.client.get_complaints() if parameters.get("complaintsAvailable") else None
        except VafabMiljoAuthError as err:
            # The BankID session expired - only the account-linked entities are
            # affected, the pickup schedule above still works without login.
            raise ConfigEntryAuthFailed("The VafabMiljö BankID session expired") from err
        except VafabMiljoError as err:
            raise UpdateFailed(f"Failed to fetch account data: {err}") from err

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
