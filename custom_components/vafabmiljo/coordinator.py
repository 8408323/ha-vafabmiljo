"""Data coordinator for the VafabMiljö integration."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import VafabMiljoAuthError, VafabMiljoClient, VafabMiljoError
from .const import (
    CONF_ADDRESS,
    CONF_SCAN_INTERVAL,
    CONF_SESSION_COOKIE,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    EVENT_LOGIN_EXPIRING,
    LOGIN_EXPIRY_WARNING_SECONDS,
)
from .minasidor import (
    MinaSidorClient,
    invoices_payload,
    pick_building,
    properties_payload,
    sanitation_payload,
)

_LOGGER = logging.getLogger(__name__)


_DECIMAL_RE = re.compile(r"[+-]?[0-9]+")


def _as_invoice_id(value: Any) -> int | None:
    """Backend invoice ids are ints; accept numeric strings, reject everything else (incl. bools).

    str.isdigit() is true for characters int() refuses, such as the superscript
    "\u00b2", so the conversion itself is the test - a malformed stored id must be
    rejected here, never raise (this also decodes persisted marker ids).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        # Plain ASCII decimals only. int() is too permissive on its own: it
        # reads "1_0" as 10 (a junk row could then shadow the real invoice 10)
        # and accepts full-width digits, while str.isdigit() is true for
        # characters int() refuses outright.
        if _DECIMAL_RE.fullmatch(value.strip()):
            try:
                return int(value)
            except ValueError:
                # CPython refuses to convert strings past sys.int_max_str_digits
                # (4300 by default), and this helper must never raise: it also
                # decodes ids read back from storage, during entry setup.
                return None
    return None


def bankid_issue_id(entry_id: str) -> str:
    return f"bankid_expired_{entry_id}"


def no_customer_issue_id(entry_id: str) -> str:
    # raised by 0.5.3 (app API without customer data); only ever deleted now
    return f"no_customer_{entry_id}"


def expiring_issue_id(entry_id: str) -> str:
    return f"login_expiring_{entry_id}"


@dataclass
class VafabMiljoData:
    """Everything the coordinator fetched on the last successful refresh."""

    pickups: list[dict[str, Any]] = field(default_factory=list)
    authenticated: bool = False
    # BankID configured, but the backend rejected the session: account data is missing until a new login
    session_expired: bool = False
    # When the Mina sidor login (its 7-day refresh cookie) runs out, epoch seconds; None without a login
    login_expires: float | None = None
    # This device's notification settings from GET /settings (None if not fetched)
    settings: dict[str, Any] | None = None
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
    def has_invoice_snapshot(self) -> bool:
        """Whether the last refresh got a usable invoice list.

        A failed poll leaves invoices=None. A list is usable when it is
        genuinely empty (a new account) or decodes to at least one invoice; a
        non-empty list of only junk rows is treated as *no* snapshot, so it can
        neither baseline an empty seed nor evict a cached good list.
        """
        if not isinstance(self.invoices, dict) or not isinstance(self.invoices.get("data"), list):
            return False
        return not self.invoices["data"] or bool(self._decode_invoice_items())

    @property
    def invoice_items(self) -> list[dict[str, Any]]:
        """Invoice items with an id - the one flattening the notifier and diagnostics share."""
        return self._decode_invoice_items() if self.has_invoice_snapshot else []

    def _decode_invoice_items(self) -> list[dict[str, Any]]:
        """Rows whose item has an integer id (numeric strings normalised), first occurrence per id."""
        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for inv in self.invoices["data"]:
            item = inv.get("item") if isinstance(inv, dict) else None
            if not isinstance(item, dict):
                continue
            invoice_id = _as_invoice_id(item.get("id"))
            if invoice_id is None or invoice_id in seen:
                continue
            seen.add(invoice_id)
            out.append({**item, "id": invoice_id})
        return out

    @property
    def available_orders(self) -> list[dict[str, Any]]:
        return self._flatten_by_current_property(self.orders)

    @property
    def available_complaints(self) -> list[dict[str, Any]]:
        return self._flatten_by_current_property(self.complaints)


class VafabMiljoCoordinator(DataUpdateCoordinator[VafabMiljoData]):
    """Polls the VafabMiljö backend for pickup schedule and (if logged in) account data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: VafabMiljoClient,
        minasidor: MinaSidorClient | None = None,
    ) -> None:
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
        )
        self.entry = entry
        self.client = client  # the app API, without login: pickups and notification settings
        self.minasidor = minasidor  # Mina sidor, with the BankID login: invoices, fees, property
        # Set by __init__ after the first refresh; None until then (and in tests
        # that build a coordinator directly).
        self.invoice_notifier: Any = None
        self.reminders: Any = None  # reminders.VafabMiljoNotifier, set by __init__
        self._expiry_announced = False  # EVENT_LOGIN_EXPIRING once per login, not every refresh

    async def _async_update_data(self) -> VafabMiljoData:
        try:
            pickups = await self.client.list_next_pickup()
        except VafabMiljoError as err:
            raise UpdateFailed(f"Failed to fetch the pickup schedule: {err}") from err

        try:
            # the app API without login: an auth error here says nothing about the Mina sidor login
            settings = await self.client.get_settings()
        except VafabMiljoError as err:
            _LOGGER.warning("Failed to fetch settings: %s", err)
            settings = None
        if not isinstance(settings, dict):
            settings = None

        if self.minasidor is None:
            if self.entry.data.get(CONF_SESSION_COOKIE):
                # logged in with the app's BankID before 0.6.0: account data needs the Mina sidor login now
                self._raise_login_issue()
            return VafabMiljoData(pickups=pickups, authenticated=False, settings=settings)

        try:
            data = await self._async_fetch_account(pickups)
        except VafabMiljoAuthError:
            # The pickup calendar needs no login, so keep it going instead of failing the whole
            # refresh (ConfigEntryAuthFailed would make every entity unavailable); raise a repair
            # that links to the panel, where the login is done, and let the notifier tell the user.
            self._raise_login_issue()
            ir.async_delete_issue(self.hass, DOMAIN, expiring_issue_id(self.entry.entry_id))
            return VafabMiljoData(
                pickups=pickups,
                authenticated=True,
                session_expired=True,
                settings=settings,
                login_expires=self.minasidor.refresh_expires,
            )
        ir.async_delete_issue(self.hass, DOMAIN, bankid_issue_id(self.entry.entry_id))
        self._check_login_expiry()
        data.settings = settings
        return data

    @callback
    def _raise_login_issue(self) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            bankid_issue_id(self.entry.entry_id),
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,  # account data has already stopped updating
            translation_key="bankid_expired",
            translation_placeholders={"address": self.entry.title},
            # the panel, where Settings -> Log in again fixes it; homeassistant:// navigates inside the
            # current frontend (a plain path opens a new tab, an external browser in the companion app)
            learn_more_url="homeassistant://vafabmiljo",
        )

    @callback
    def _check_login_expiry(self) -> None:
        """Warn (repair + event) when the 7-day Mina sidor login is about to run out."""
        assert self.minasidor is not None
        expires = self.minasidor.refresh_expires
        issue_id = expiring_issue_id(self.entry.entry_id)
        if expires - dt_util.utcnow().timestamp() > LOGIN_EXPIRY_WARNING_SECONDS:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        when = dt_util.as_local(dt_util.utc_from_timestamp(expires)).strftime("%Y-%m-%d %H:%M")
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="login_expiring",
            translation_placeholders={"address": self.entry.title, "expires": when},
            learn_more_url="homeassistant://vafabmiljo",
        )
        if not self._expiry_announced:
            self._expiry_announced = True
            self.hass.bus.async_fire(
                EVENT_LOGIN_EXPIRING,
                {"entry_id": self.entry.entry_id, "address": self.entry.title, "expires": when},
            )

    async def _async_fetch_account(self, pickups: list[dict[str, Any]]) -> VafabMiljoData:
        ms = self.minasidor
        assert ms is not None
        invoices = await self._try_fetch("invoices", ms.get_invoices)
        buildings = await self._try_fetch("buildings", ms.get_buildings)
        billing = await self._try_fetch("billing info", ms.get_billing_info)
        building = pick_building(buildings or [], self.entry.data.get(CONF_ADDRESS, ""))
        services = orders = None
        if building is not None:
            building_id = str(building.get("id"))
            services = await self._try_fetch("services", lambda: ms.get_services(building_id))
            orders = await self._try_fetch("extra orders", lambda: ms.get_extra_orders(building_id))
        return VafabMiljoData(
            pickups=pickups,
            authenticated=True,
            invoices=invoices_payload(invoices) if invoices is not None else None,
            sanitation=sanitation_payload(services) if services is not None else None,
            properties=properties_payload(building, billing if isinstance(billing, dict) else None),
            parameters={"ordersAvailable": bool(orders), "complaintsAvailable": False},
            orders={str(building.get("id")): {"extra": [_order_item(o) for o in orders]}}
            if building is not None and orders
            else None,
            login_expires=ms.refresh_expires,
        )

    @callback
    def async_apply_setting(self, field: str, value: Any) -> None:
        """Record a setting the backend just accepted, so entities don't flip back until the next refresh."""
        if self.data is not None and self.data.settings is not None:
            self.data.settings = {**self.data.settings, field: value}

    async def _try_fetch(self, name: str, fetch: Callable[[], Awaitable[Any]]) -> Any:
        """Fetch one piece of account data, tolerating a stuck/failing endpoint.

        Each of these is independent account data, not required for the
        pickup-schedule sensors that work without login at all - one endpoint
        being persistently broken (e.g. an account whose /services/invoices
        never leaves the backend's 202 "waiting" state) shouldn't take down
        the whole integration.
        """
        try:
            return await fetch()
        except VafabMiljoAuthError:
            # The BankID session expired - this affects every authenticated
            # endpoint equally, so it's handled once in _async_update_data.
            raise
        except VafabMiljoError as err:
            _LOGGER.warning("Failed to fetch %s: %s", name, err)
            return None


def _order_item(order: Any) -> dict[str, Any]:
    """One extra-service order Mina sidor offers, with the "title" the orders sensor lists."""
    if not isinstance(order, dict):
        return {"title": str(order)}
    title = order.get("name") or order.get("title") or order.get("description") or order.get("serviceName")
    return {**order, "title": title}
