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
        )
