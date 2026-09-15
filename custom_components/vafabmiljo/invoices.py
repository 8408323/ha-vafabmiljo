"""New-invoice detection and due-date reminders, delivered as HA events.

Why events and not a state trigger on the Latest invoice sensor: a state
trigger on `invoice_count` fires whenever the attribute *appears*, which
happens every time the entity comes back from unavailable - each HA restart,
each integration reload, each poll where the invoices endpoint hiccups. That
is exactly what produced repeated "new invoice" notifications for the same
invoice. Here the set of invoice ids already announced is persisted in HA's
storage, so an invoice is announced once in its lifetime, no matter how many
restarts happen in between, and the very first run seeds that set with
everything already on the account instead of announcing old history.

The due-date reminder works the same way: one `vafabmiljo_invoice_due_reminder`
event per unpaid invoice, the day before it is due, at the local "Invoice
reminder time" entity's time - scheduled with a precise point-in-time timer
rather than tied to the 30-minute poll cadence.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ADDRESS,
    CONF_CITY,
    DEFAULT_INVOICE_REMINDER_TIME,
    DOMAIN,
    EVENT_INVOICE_DUE_REMINDER,
    EVENT_NEW_INVOICE,
    INVOICE_STORAGE_VERSION,
    PAID_STATUSES,
)
from .coordinator import VafabMiljoCoordinator

_LOGGER = logging.getLogger(__name__)


def _store_key(entry: ConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}.invoices"


async def async_remove_invoice_store(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the per-entry persisted state when the entry itself is removed."""
    await Store(hass, INVOICE_STORAGE_VERSION, _store_key(entry)).async_remove()


def _parse_date(value: Any) -> date | None:
    """'2026-08-31T00:00:00' (always midnight from this backend) -> date."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _is_paid(invoice: dict[str, Any]) -> bool:
    return str(invoice.get("paymentStatus") or "").strip().lower() in PAID_STATUSES


class VafabMiljoInvoiceNotifier:
    """Tracks which invoices have been announced/reminded and fires the events."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: VafabMiljoCoordinator) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._store: Store = Store(hass, INVOICE_STORAGE_VERSION, _store_key(entry))
        self._announced: set[int] = set()
        self._reminded: set[int] = set()
        self._reminder_time = time.fromisoformat(DEFAULT_INVOICE_REMINDER_TIME)
        self._unsub_timer = None
        self._unsub_listener = None
        # False until the first-run baseline has been taken from a *valid*
        # invoice snapshot (see _async_check). Persisted store => already seeded.
        self._seeded = False
        self._last_invoices: list[dict[str, Any]] = []
        # Set on unload. In-flight checks are deliberately *not* cancelled: the
        # only suspension point in a check sits between firing an event and
        # persisting it, and cancelling there would forget a delivered event
        # (= the double notification this module exists to prevent). Instead a
        # stale task finishes its save and is then refused any new scheduling.
        self._unloaded = False
        self._unsub_started = None
        self.pending_reminder_invoice_id: int | None = None

    # -- lifecycle -------------------------------------------------------------

    async def async_setup(self) -> None:
        stored = await self._store.async_load()
        if stored is not None:
            # An explicit flag, not the store's mere existence: changing the
            # reminder time also writes the store, possibly before the first
            # valid invoice snapshot ever arrived.
            self._seeded = bool(stored.get("seeded", False))
            self._announced = set(stored.get("announced", []))
            self._reminded = set(stored.get("reminded", []))
            if stored.get("reminder_time"):
                self._reminder_time = time.fromisoformat(stored["reminder_time"])
        self._unsub_listener = self._coordinator.async_add_listener(self._handle_coordinator_update)
        # During a cold HA start this entry may be set up before the automation
        # integration has its event listeners in place; an event fired now would
        # be persisted as delivered yet reach nobody. Nothing is checked - not
        # the first pass, not a coordinator refresh - until HA is fully running
        # (CoreState.running, the same state automations wait for; note
        # hass.is_running is already True in CoreState.starting). A reload of
        # an already-running HA checks immediately.
        if self._ha_running:
            await self._async_check()
        else:
            self._unsub_started = async_at_started(self._hass, self._handle_started)

    @property
    def _ha_running(self) -> bool:
        return self._hass.state is CoreState.running

    @callback
    def _handle_started(self, _hass: HomeAssistant) -> None:
        self._unsub_started = None
        self._hass.async_create_task(self._async_check())

    @callback
    def async_unload(self) -> None:
        self._unloaded = True
        self._cancel_timer()
        if self._unsub_started is not None:
            self._unsub_started()
            self._unsub_started = None
        if self._unsub_listener is not None:
            self._unsub_listener()
            self._unsub_listener = None

    @property
    def reminder_time(self) -> time:
        return self._reminder_time

    @property
    def announced_count(self) -> int:
        return len(self._announced)

    @property
    def reminded_count(self) -> int:
        return len(self._reminded)

    async def async_set_reminder_time(self, value: time) -> None:
        self._reminder_time = value
        await self._async_save()
        await self._async_schedule_reminder()

    # -- internals -------------------------------------------------------------

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self._ha_running:
            # Still booting: the async_at_started hook will run the check once
            # automations can actually hear the events.
            return
        self._hass.async_create_task(self._async_check())

    def _has_snapshot(self) -> bool:
        data = self._coordinator.data
        return data is not None and data.has_invoice_snapshot

    def _invoices(self) -> list[dict[str, Any]]:
        """Invoice items from the latest valid snapshot.

        A failed poll leaves the coordinator with invoices=None; the last good
        list is kept so a reminder timer that fires during such a gap still
        knows which invoice it was scheduled for.
        """
        if self._has_snapshot():
            self._last_invoices = self._coordinator.data.invoice_items
        return self._last_invoices

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "seeded": self._seeded,
                "announced": sorted(self._announced),
                "reminded": sorted(self._reminded),
                "reminder_time": self._reminder_time.isoformat(),
            }
        )

    async def _async_check(self) -> None:
        if self._unloaded or not self._has_snapshot():
            # A failed /services/invoices poll (or no data yet): nothing to
            # compare against. Leave any already-scheduled reminder timer in
            # place rather than cancelling it and hoping the next poll lands
            # before the due date.
            return
        if not self._seeded:
            # First run: everything already on the account is history, not
            # news - announce only what shows up from here on. Taken from the
            # first *valid* snapshot, never from a failed poll (which would
            # baseline an empty set and announce the whole history next time).
            self._announced = {inv["id"] for inv in self._invoices()}
            self._seeded = True
            await self._async_save()
            await self._async_schedule_reminder()
            return
        new = [inv for inv in self._invoices() if inv["id"] not in self._announced]
        # The backend lists newest first; announce oldest-first so a burst of
        # several new invoices arrives in chronological order.
        for inv in reversed(new):
            self._hass.bus.async_fire(EVENT_NEW_INVOICE, self._event_data(inv))
            self._announced.add(inv["id"])
            _LOGGER.debug("Announced new invoice %s", inv["id"])
        if new:
            await self._async_save()
        await self._async_schedule_reminder()

    def _event_data(self, inv: dict[str, Any]) -> dict[str, Any]:
        due = _parse_date(inv.get("invoiceExpirationDate"))
        invoiced = _parse_date(inv.get("invoiceDate"))
        today = dt_util.now().date()
        return {
            "entry_id": self._entry.entry_id,
            "address": self._entry.data.get(CONF_ADDRESS),
            "city": self._entry.data.get(CONF_CITY),
            "invoice_id": inv["id"],
            "amount": inv.get("amount"),
            "invoice_date": invoiced.isoformat() if invoiced else None,
            "due_date": due.isoformat() if due else None,
            "days_until_due": (due - today).days if due else None,
            "payment_status": inv.get("paymentStatus"),
            "ocr_number": inv.get("ocrNumber"),
        }

    def _cancel_timer(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None
        self.pending_reminder_invoice_id = None

    def _next_reminder_candidate(self, today: date) -> tuple[dict[str, Any], date] | None:
        """The unpaid, not-yet-reminded invoice with the nearest due date still strictly ahead.

        An invoice due *today* is excluded: its reminder moment (the day before)
        has passed, and a "due tomorrow" reminder on the due date itself would
        be wrong - the README promises catch-up only while the invoice is not
        yet due.
        """
        best: tuple[dict[str, Any], date] | None = None
        for inv in self._invoices():
            due = _parse_date(inv.get("invoiceExpirationDate"))
            if due is None or inv["id"] in self._reminded or _is_paid(inv) or due <= today:
                continue
            if best is None or due < best[1]:
                best = (inv, due)
        return best

    async def _async_schedule_reminder(self) -> None:
        self._cancel_timer()
        if self._unloaded:
            return
        now = dt_util.now()
        candidate = self._next_reminder_candidate(now.date())
        if candidate is None:
            return
        inv, due = candidate
        remind_at = dt_util.start_of_local_day(due - timedelta(days=1)) + timedelta(
            hours=self._reminder_time.hour, minutes=self._reminder_time.minute, seconds=self._reminder_time.second
        )
        if remind_at <= now:
            # Reminder moment already passed (HA was down, or the reminder time
            # was moved earlier) but the invoice is still not due - send it now
            # rather than silently skipping it, then look for the next one.
            self._hass.bus.async_fire(EVENT_INVOICE_DUE_REMINDER, self._event_data(inv))
            self._reminded.add(inv["id"])
            _LOGGER.debug("Sent due-date reminder for invoice %s", inv["id"])
            await self._async_save()
            await self._async_schedule_reminder()
            return
        self.pending_reminder_invoice_id = inv["id"]
        self._unsub_timer = async_track_point_in_time(self._hass, self._async_on_timer, remind_at)

    async def _async_on_timer(self, _now: datetime) -> None:
        self._unsub_timer = None
        self.pending_reminder_invoice_id = None
        await self._async_schedule_reminder()
