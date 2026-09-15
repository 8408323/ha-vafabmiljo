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

import asyncio
import contextlib
import functools
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
    CONF_PLANT_ID,
    DEFAULT_INVOICE_REMINDER_TIME,
    DOMAIN,
    EVENT_INVOICE_DUE_REMINDER,
    EVENT_NEW_INVOICE,
    INVOICE_STORAGE_VERSION,
    PAID_STATUSES,
)
from .coordinator import VafabMiljoCoordinator, _as_invoice_id

_LOGGER = logging.getLogger(__name__)


def _store_key(entry: ConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}.invoices"


def _removed_store_keys(hass: HomeAssistant) -> set[str]:
    """Stores deleted by entry removal; entry_ids are never reused, so this only grows."""
    return hass.data.setdefault(f"{DOMAIN}_invoice_stores_removed", set())


def _store_lock(hass: HomeAssistant, key: str) -> asyncio.Lock:
    """One lock per store, shared across notifier instances of the same entry.

    A reload replaces the notifier while the old one may still be inside its
    post-event save; the replacement must not read the store (and re-announce)
    before that save has landed, and removal must not race it either.
    """
    locks: dict[str, asyncio.Lock] = hass.data.setdefault(f"{DOMAIN}_invoice_store_locks", {})
    return locks.setdefault(key, asyncio.Lock())


async def async_remove_invoice_store(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the per-entry persisted state when the entry itself is removed."""
    key = _store_key(entry)
    async with _store_lock(hass, key):
        # Marked before the delete and under the same lock, so a check still
        # queued behind it cannot write the state back afterwards.
        _removed_store_keys(hass).add(key)
        await Store(hass, INVOICE_STORAGE_VERSION, key).async_remove()


def _parse_date(value: Any) -> date | None:
    """'2026-08-31T00:00:00' (always midnight from this backend) -> date."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


_KEEP_FIELDS = ("id", "amount", "invoiceDate", "invoiceExpirationDate", "paymentStatus", "ocrNumber")


def _slim(invoice: dict[str, Any]) -> dict[str, Any]:
    """Only the fields this module uses - this list is persisted to storage."""
    return {k: invoice.get(k) for k in _KEEP_FIELDS}


def _load_ids(values: Any) -> set[int] | None:
    """Marker ids from storage, or None if the field is not a list of valid ids.

    Dropping a malformed entry silently would leave a *partial* marker set that
    still looks seeded, and the next snapshot would then announce every invoice
    the dropped entries covered.
    """
    if not isinstance(values, list):
        return None
    out: set[int] = set()
    for value in values:
        invoice_id = _as_invoice_id(value)
        if invoice_id is None:
            return None
        out.add(invoice_id)
    return out


def _load_invoices(values: Any) -> list[dict[str, Any]] | None:
    """Cached invoice rows from storage with ids normalised, or None if any row is malformed.

    Normalising matters so a stored "5" cannot miss a marker holding 5; rejecting
    the whole cache on a bad row matters because a silently shortened cache still
    looks authoritative to the reminder scheduler.
    """
    if not isinstance(values, list):
        return None
    out: list[dict[str, Any]] = []
    for inv in values:
        if not isinstance(inv, dict):
            return None
        invoice_id = _as_invoice_id(inv.get("id"))
        if invoice_id is None:
            return None
        out.append({**inv, "id": invoice_id})
    return out


def _is_paid(invoice: dict[str, Any]) -> bool:
    return str(invoice.get("paymentStatus") or "").strip().lower() in PAID_STATUSES


class VafabMiljoInvoiceNotifier:
    """Tracks which invoices have been announced/reminded and fires the events."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: VafabMiljoCoordinator) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._store: Store = Store(hass, INVOICE_STORAGE_VERSION, _store_key(entry))
        self._lock = _store_lock(hass, _store_key(entry))
        # Serialises every marker decision with the save that records it, so a
        # concurrent check can neither persist a marker another task is about
        # to roll back nor reschedule a timer from a value still being written.
        self._work_lock = asyncio.Lock()
        # Captured now: a reconfigure flow mutates entry.data before reloading,
        # and a save of *this* instance must keep labelling its state with the
        # property it actually belongs to.
        self._plant_id = entry.data.get(CONF_PLANT_ID)
        self._address = entry.data.get(CONF_ADDRESS)
        self._city = entry.data.get(CONF_CITY)
        # Generation counters: every marker change bumps _gen; a save records
        # the generation it wrote. A change made *while* a save is awaiting
        # therefore stays pending instead of being cleared by that save.
        self._gen = 0
        self._saved_gen = 0
        self._announced: set[int] = set()
        self._reminded: set[int] = set()
        self._reminder_time = time.fromisoformat(DEFAULT_INVOICE_REMINDER_TIME)
        self._unsub_timer = None
        # Bumped whenever a timer is armed or dropped; a callback that was
        # already queued when its timer got cancelled carries a stale token
        # and must not touch the replacement's state.
        self._timer_token = 0
        self._unsub_listener = None
        # False until the first-run baseline has been taken from a *valid*
        # invoice snapshot (see _async_check). Persisted store => already seeded.
        self._seeded = False
        self._last_invoices: list[dict[str, Any]] = []
        self._stored_invoices: list[dict[str, Any]] = []  # what the store currently holds
        # Set on unload. In-flight checks are deliberately *not* cancelled:
        # a check persists the marker and only then fires the event, so
        # cancelling it mid-save would abandon a write that may already have
        # landed. Instead the task runs to completion - rolling its marker back
        # if the save did not finish - and is then refused any new scheduling.
        self._unloaded = False
        self._unsub_started = None
        self.pending_reminder_invoice_id: int | None = None

    # -- lifecycle -------------------------------------------------------------

    async def async_setup(self) -> None:
        async with self._work_lock:
            await self._async_load()
        if self._unloaded:
            # Unloaded while the store read was in flight - attaching now would
            # leave a listener behind on a notifier nobody will unload again.
            return
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

    async def _async_load(self) -> None:
        async with self._lock:
            stored = await self._store.async_load()
        if not isinstance(stored, dict):
            # Corrupt or foreign-format state must not abort entry setup; treat
            # anything that is not a mapping as no state at all.
            if stored is not None:
                _LOGGER.warning("Ignoring malformed persisted invoice state (%s)", type(stored).__name__)
            stored = None
        if stored is not None and stored.get("plant_id") != self._plant_id:
            # Either reconfigured to another address (same entry_id) or a
            # truncated store with no binding at all: the old property's
            # announced/reminded/cached state must not carry over. Keep only
            # the user's reminder time.
            _LOGGER.debug("Bound property changed; resetting persisted invoice state")
            stored = {"reminder_time": stored.get("reminder_time")}
            # Persist the sanitized state right away rather than only with the
            # first valid snapshot - the old property's cached invoices (OCR
            # numbers included) must not linger on disk if that never comes.
            self._mark_dirty()
        if stored is not None:
            # An explicit flag, not the store's mere existence: changing the
            # reminder time also writes the store, possibly before the first
            # valid invoice snapshot ever arrived.
            # Only a real boolean True counts: bool("false") and bool([0]) are
            # both truthy, and a corrupt flag would skip the first-run baseline
            # and announce the whole invoice history as new.
            # Every persisted field must be wholly valid before "seeded" is
            # believed: a truncated or partially malformed store would
            # otherwise look baselined while holding incomplete markers, and
            # the next snapshot would announce the entire invoice history.
            announced = _load_ids(stored.get("announced"))
            reminded = _load_ids(stored.get("reminded"))
            # Cached invoice rows let a reminder still be scheduled (or caught
            # up) after a restart whose first poll fails.
            invoices = _load_invoices(stored.get("invoices"))
            self._seeded = (
                stored.get("seeded") is True and announced is not None and reminded is not None and invoices is not None
            )
            if self._seeded:
                self._announced = announced
                self._reminded = reminded
                self._last_invoices = invoices
                self._stored_invoices = list(invoices)
            # Otherwise nothing here is trustworthy: keeping a "reminded" entry
            # from an untrusted store would suppress a reminder no trusted
            # state says was ever delivered. Only the user's own reminder time
            # is carried over, below.
            if stored.get("reminder_time"):
                try:
                    self._reminder_time = time.fromisoformat(stored["reminder_time"])
                except (TypeError, ValueError):
                    _LOGGER.warning("Ignoring malformed persisted reminder time %r", stored["reminder_time"])
        if self._dirty and not self._unloaded:
            # Unloaded while the read was in flight: entry removal may already
            # have deleted this store, and writing now would resurrect it.
            await self._async_save()

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
    def _dirty(self) -> bool:
        return self._gen != self._saved_gen

    def _mark_dirty(self) -> None:
        self._gen += 1

    @property
    def announced_count(self) -> int:
        return len(self._announced)

    @property
    def reminded_count(self) -> int:
        return len(self._reminded)

    async def async_set_reminder_time(self, value: time) -> None:
        async with self._work_lock:
            if self._unloaded:
                # A queued entity call that got the lock after teardown; saving
                # here could recreate a store that entry removal just deleted.
                return
            previous = self._reminder_time
            self._reminder_time = value
            saved = False
            try:
                await self._async_save()
                saved = True
            finally:
                if not saved:
                    # Keep value and timer consistent: the entity would
                    # otherwise show the new time while a timer sits armed at
                    # the rejected one. `finally`, not `except Exception`, so
                    # cancellation restores it too. Best effort - the original
                    # error must not be masked.
                    self._reminder_time = previous
                    with contextlib.suppress(Exception):
                        await self._async_schedule_reminder()
            await self._async_schedule_reminder()
            await self._async_flush_pending()

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
            self._last_invoices = [_slim(inv) for inv in self._coordinator.data.invoice_items]
        return self._last_invoices

    async def _async_save(self) -> bool:
        """Persist the current state. False means the write was refused, not durable."""
        snapshot = list(self._last_invoices)
        gen = self._gen
        async with self._lock:
            if self._store.key in _removed_store_keys(self._hass):
                # Entry removal deleted this store while we waited for the
                # lock; writing now would resurrect it.
                return False
            await self._store.async_save(
                {
                    "plant_id": self._plant_id,
                    "seeded": self._seeded,
                    "announced": sorted(self._announced),
                    "reminded": sorted(self._reminded),
                    "reminder_time": self._reminder_time.isoformat(),
                    "invoices": snapshot,
                }
            )
        # Only after the write landed - a failed save must look unsaved so the
        # next check retries it.
        self._stored_invoices = snapshot
        self._saved_gen = max(self._saved_gen, gen)
        return True

    async def _async_check(self) -> None:
        async with self._work_lock:
            await self._async_check_locked()
            await self._async_flush_pending()

    async def _async_flush_pending(self) -> None:
        """Persist anything left unsaved before the work lock is released.

        Scheduling deliberately re-reads the snapshot (its catch-up branch has
        to, so a refresh landing during a write cannot deliver stale data), and
        that re-read can leave a newer invoice list in memory that no save has
        recorded. Flushing here keeps the persisted cache from going stale,
        which a restart with a failing poll would otherwise load and schedule
        from.
        """
        if self._unloaded:
            return
        if self._dirty or self._last_invoices != self._stored_invoices:
            await self._async_save()

    async def _async_check_locked(self) -> None:
        if self._unloaded:
            return
        if not self._has_snapshot():
            # A failed /services/invoices poll (or no data yet): nothing to
            # compare against. Still retry a save that failed earlier (a
            # delivered event must reach disk regardless of the endpoint),
            # and leave any already-scheduled reminder timer in place rather
            # than cancelling it and hoping the next poll lands before the due
            # date - but if there is no timer at all (fresh restart), schedule
            # from the persisted last-known list.
            flushed = self._dirty or self._last_invoices != self._stored_invoices
            if flushed:
                # Not just markers: a snapshot change (an invoice turning paid)
                # whose save failed must be retried too, or a restart would
                # reload stale data and could schedule a settled invoice.
                await self._async_save()
            if flushed or (self._unsub_timer is None and self._last_invoices):
                # A snapshot that only now reached disk may name a nearer
                # invoice than the armed timer, which was computed before it -
                # or no invoice at all, in which case the stale timer has to be
                # cancelled rather than left to fire.
                await self._async_schedule_reminder()
            return
        if not self._seeded:
            # First run: everything already on the account is history, not
            # news - announce only what shows up from here on. Taken from the
            # first *valid* snapshot, never from a failed poll (which would
            # baseline an empty set and announce the whole history next time).
            self._announced = {inv["id"] for inv in self._invoices()}
            self._seeded = True
            self._mark_dirty()
            await self._async_save()
            await self._async_schedule_reminder()
            return
        new = [inv for inv in self._invoices() if inv["id"] not in self._announced]
        if new:
            # Persist the markers BEFORE firing. An event that reached the bus
            # while its save failed would be announced again by the retry (a
            # failure during setup tears this notifier down and HA retries),
            # which is exactly the duplicate this module exists to prevent.
            # Nothing awaits between the successful save and the synchronous
            # fire, so the reverse window is not a practical concern.
            pending = {inv["id"] for inv in new}
            self._announced |= pending
            self._mark_dirty()
            delivered = False
            try:
                if not await self._async_save():
                    # The store is gone (entry removed): a removed entry must
                    # not announce anything, and the finally below releases the
                    # markers.
                    return
                # The backend lists newest first; announce oldest-first so a
                # burst of several new invoices arrives in chronological order.
                for inv in reversed(new):
                    self._hass.bus.async_fire(EVENT_NEW_INVOICE, self._event_data(inv))
                    _LOGGER.debug("Announced new invoice %s", inv["id"])
                delivered = True
            finally:
                if not delivered:
                    # Nothing went out, so nothing may stay marked - including
                    # when the save was interrupted by CancelledError during a
                    # reload, which an `except Exception` would let through and
                    # leave the invoice permanently suppressed.
                    self._announced -= pending
        elif self._dirty or self._last_invoices != self._stored_invoices:
            await self._async_save()
        await self._async_schedule_reminder()

    def _event_data(self, inv: dict[str, Any]) -> dict[str, Any]:
        due = _parse_date(inv.get("invoiceExpirationDate"))
        invoiced = _parse_date(inv.get("invoiceDate"))
        today = dt_util.now().date()
        return {
            "entry_id": self._entry.entry_id,
            "address": self._address,
            "city": self._city,
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
        self._timer_token += 1
        self.pending_reminder_invoice_id = None

    def _remind_at(self, due: date) -> datetime:
        """The local reminder moment for an invoice due on `due` (the day before)."""
        return dt_util.start_of_local_day(due - timedelta(days=1)) + timedelta(
            hours=self._reminder_time.hour, minutes=self._reminder_time.minute, seconds=self._reminder_time.second
        )

    def _invoice_by_id(self, invoice_id: int) -> dict[str, Any] | None:
        return next((inv for inv in self._invoices() if inv["id"] == invoice_id), None)

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
        remind_at = self._remind_at(due)
        if remind_at <= now:
            # Reminder moment already passed (HA was down, or the reminder time
            # was moved earlier) but the invoice is still not due - send it now
            # rather than silently skipping it, then look for the next one.
            self._reminded.add(inv["id"])
            self._mark_dirty()
            settled = False
            try:
                if not await self._async_save():
                    return
                # A coordinator refresh is not held by the work lock and can
                # replace the snapshot while that write is in flight, so the
                # candidate is re-read before it is announced: an invoice paid
                # (or reaching its due date) in the meantime must not produce a
                # "due tomorrow" reminder. Its marker stays either way - a
                # settled invoice needs no reminder later.
                # No fallback to the row captured before the write: if a valid
                # refreshed snapshot no longer lists this invoice, the account
                # does not have it any more. (With no usable snapshot,
                # _invoices() still serves the cached row, so this finds it.)
                latest = self._invoice_by_id(inv["id"])
                latest_due = _parse_date(latest.get("invoiceExpirationDate")) if latest is not None else None
                pending = (
                    latest is not None
                    and not _is_paid(latest)
                    and latest_due is not None
                    and latest_due > dt_util.now().date()
                )
                if pending and self._remind_at(latest_due) <= dt_util.now():
                    self._hass.bus.async_fire(EVENT_INVOICE_DUE_REMINDER, self._event_data(latest))
                    _LOGGER.debug("Sent due-date reminder for invoice %s", inv["id"])
                elif pending:
                    # The due date moved further out while the marker was being
                    # written, so its day-before moment has not arrived after
                    # all. Release the marker; the scheduling pass below arms a
                    # timer for the new date instead.
                    self._reminded.discard(inv["id"])
                    self._mark_dirty()
                    _LOGGER.debug("Invoice %s due date moved; reminder rescheduled", inv["id"])
                else:
                    _LOGGER.debug("Invoice %s settled while persisting; reminder skipped", inv["id"])
                settled = True
            finally:
                if not settled:
                    self._reminded.discard(inv["id"])
            await self._async_schedule_reminder()
            return
        self._timer_token += 1
        self.pending_reminder_invoice_id = inv["id"]
        self._unsub_timer = async_track_point_in_time(
            self._hass, functools.partial(self._async_on_timer, self._timer_token), remind_at
        )

    async def _async_on_timer(self, token: int, _now: datetime) -> None:
        async with self._work_lock:
            if token != self._timer_token:
                # Stale: this timer was cancelled and replaced after its
                # callback had already been queued (possibly while waiting for
                # this lock). Clearing the handle would orphan the replacement.
                return
            self._unsub_timer = None
            self.pending_reminder_invoice_id = None
            await self._async_schedule_reminder()
            await self._async_flush_pending()
