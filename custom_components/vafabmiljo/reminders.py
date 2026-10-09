"""Built-in notifications, configured per recipient (a notify service: a phone, a person's group, ...).

Each recipient picks which messages it gets and when:
- pickup reminder: the evening before (or the same morning) at its own time, listing the bins
- new invoice / invoice due tomorrow: sent when this entry fires its own invoice events (invoices.py)
- BankID login expired: once per expiry, when the backend starts rejecting the session

Off by default (no recipients), so it never doubles up with automations built on the events. Recipients
live in their own Store rather than in the entry options: an options change reloads the whole entry.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store

from .const import CONF_ADDRESS, DOMAIN, EVENT_INVOICE_DUE_REMINDER, EVENT_NEW_INVOICE
from .coordinator import VafabMiljoCoordinator

_LOGGER = logging.getLogger(__name__)

_TIME_RE = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
_TEXT = {
    "sv": {
        "pickup": "Tömning {when}: {bins}",
        "today": "idag",
        "tomorrow": "imorgon",
        "put_out": "Ställ ut kärlen.",
        "new_invoice": "Ny faktura: {amount} kr",
        "invoice_due": "Faktura förfaller imorgon: {amount} kr",
        "invoice": "{address}, förfaller {due}, OCR {ocr}",
        "expired": "VafabMiljö: inloggningen har gått ut",
        "expired_msg": "Fakturor och avgifter uppdateras inte. Logga in med BankID igen i VafabMiljö-panelen.",
    },
    "en": {
        "pickup": "Pickup {when}: {bins}",
        "today": "today",
        "tomorrow": "tomorrow",
        "put_out": "Put the bins out.",
        "new_invoice": "New invoice: {amount} kr",
        "invoice_due": "Invoice due tomorrow: {amount} kr",
        "invoice": "{address}, due {due}, OCR {ocr}",
        "expired": "VafabMiljö: login expired",
        "expired_msg": "Invoices and fees are no longer updated. Log in with BankID again in the VafabMiljö panel.",
    },
}
DEFAULT_RECIPIENT = {
    "pickup": True,
    "pickup_days_before": 1,
    "pickup_time": "18:00",
    "new_invoice": True,
    "invoice_due": True,
    "session_expired": True,
}


def clean_recipients(raw: Any) -> list[dict[str, Any]]:
    """Validate recipients from the panel (or storage): unknown keys dropped, bad values reset to defaults."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        service = item.get("service") if isinstance(item, dict) else None
        if not isinstance(service, str) or not service or service in seen:
            continue
        seen.add(service)
        rec = {"service": service}
        for key, default in DEFAULT_RECIPIENT.items():
            value = item.get(key, default)
            if key == "pickup_time":
                rec[key] = value if isinstance(value, str) and _TIME_RE.fullmatch(value) else default
            elif key == "pickup_days_before":
                rec[key] = value if value in (0, 1) and not isinstance(value, bool) else default
            else:
                rec[key] = value if isinstance(value, bool) else default
        out.append(rec)
    return out


def store_for(hass: HomeAssistant, entry: ConfigEntry) -> Store:
    return Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.notify")


class VafabMiljoNotifier:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: VafabMiljoCoordinator) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._store = store_for(hass, entry)
        self.recipients: list[dict[str, Any]] = []
        self._unsubs: list[Any] = []
        self._timers: list[Any] = []
        self._expired = False  # whether the current expiry was already announced

    async def async_setup(self) -> None:
        self.recipients = clean_recipients(await self._store.async_load())
        for event_type in (EVENT_NEW_INVOICE, EVENT_INVOICE_DUE_REMINDER):
            self._unsubs.append(self._hass.bus.async_listen(event_type, self._on_invoice_event))
        self._unsubs.append(self._coordinator.async_add_listener(self._on_update))
        self._schedule()
        self._on_update()  # the first refresh (before this listener existed) may already have found it expired

    @callback
    def _on_update(self) -> None:
        expired = bool(self._coordinator.data and self._coordinator.data.session_expired)
        if expired and not self._expired:
            t = self._text
            self._hass.async_create_task(self._send_all("session_expired", t["expired"], t["expired_msg"]))
        self._expired = expired

    async def _send_all(self, key: str, title: str, message: str) -> None:
        for rec in self.recipients:
            if rec[key]:
                await self._send(rec["service"], title, message)

    @callback
    def async_unload(self) -> None:
        for unsub in self._unsubs + self._timers:
            unsub()
        self._unsubs, self._timers = [], []

    async def async_set(self, recipients: Any) -> list[dict[str, Any]]:
        self.recipients = clean_recipients(recipients)
        await self._store.async_save(self.recipients)
        self._schedule()
        return self.recipients

    def _schedule(self) -> None:
        for unsub in self._timers:
            unsub()
        times = {r["pickup_time"] for r in self.recipients if r["pickup"]}
        self._timers = [
            async_track_time_change(self._hass, self._on_time, hour=int(t[:2]), minute=int(t[3:]), second=0)
            for t in sorted(times)
        ]

    async def _on_time(self, now: datetime) -> None:
        hhmm = f"{now.hour:02d}:{now.minute:02d}"
        for rec in self.recipients:
            if rec["pickup"] and rec["pickup_time"] == hhmm:
                if bins := self.bins_on(now.date() + timedelta(days=rec["pickup_days_before"])):
                    t = self._text
                    when = t["tomorrow"] if rec["pickup_days_before"] else t["today"]
                    await self._send(rec["service"], t["pickup"].format(when=when, bins=", ".join(bins)), t["put_out"])

    def bins_on(self, day: date) -> list[str]:
        pickups = self._coordinator.data.pickups
        bins = pickups[0].get("bins", []) if pickups else []
        return [b["type"] for b in bins if b.get("pickup_date") == day.isoformat()]

    async def _on_invoice_event(self, event: Event) -> None:
        data = event.data
        if data.get("entry_id") != self._entry.entry_id:
            return
        t = self._text
        key = "new_invoice" if event.event_type == EVENT_NEW_INVOICE else "invoice_due"
        title = t[key].format(amount=data.get("amount"))
        message = t["invoice"].format(
            address=self._entry.data[CONF_ADDRESS], due=data.get("due_date"), ocr=data.get("ocr_number")
        )
        await self._send_all(key, title, message)

    @property
    def _text(self) -> dict[str, str]:
        return _TEXT["sv" if str(self._hass.config.language).startswith("sv") else "en"]

    async def _send(self, service: str, title: str, message: str) -> None:
        # A recipient is a legacy notify action ("mobile_app_x") or a notify entity ("notify.x",
        # sent through notify.send_message). One broken recipient must not stop the others.
        if service.startswith("notify."):
            domain_service, data = "send_message", {"entity_id": service, "title": title, "message": message}
        else:
            domain_service, data = service, {"title": title, "message": message}
        try:
            await self._hass.services.async_call("notify", domain_service, data, blocking=True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("notify.%s failed: %s", service, err)


def notify_targets(hass: HomeAssistant) -> list[str]:
    """Legacy notify actions (minus the generic send_message, which needs a target) plus notify entities."""
    legacy = [s for s in hass.services.async_services().get("notify", {}) if s != "send_message"]
    return sorted(legacy) + sorted(hass.states.async_entity_ids("notify"))


def _notifier(hass: HomeAssistant, entry_id: str) -> VafabMiljoNotifier | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    coordinator = getattr(entry, "runtime_data", None) if entry and entry.domain == DOMAIN else None
    return getattr(coordinator, "reminders", None)


@websocket_api.websocket_command({vol.Required("type"): "vafabmiljo/notify/get", vol.Required("entry_id"): str})
@callback
def ws_get(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    notifier = _notifier(hass, msg["entry_id"])
    if notifier is None:
        connection.send_error(msg["id"], "not_found", "No loaded VafabMiljö entry with that id")
        return
    connection.send_result(
        msg["id"],
        {"recipients": notifier.recipients, "services": notify_targets(hass)},
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "vafabmiljo/notify/set", vol.Required("entry_id"): str, vol.Required("recipients"): list}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    notifier = _notifier(hass, msg["entry_id"])
    if notifier is None:
        connection.send_error(msg["id"], "not_found", "No loaded VafabMiljö entry with that id")
        return
    connection.send_result(msg["id"], {"recipients": await notifier.async_set(msg["recipients"])})


def async_setup_websocket(hass: HomeAssistant) -> None:
    if hass.data.get(f"{DOMAIN}_ws"):
        return
    hass.data[f"{DOMAIN}_ws"] = True
    from .login import COMMANDS as LOGIN_COMMANDS

    for command in (ws_get, ws_set, *LOGIN_COMMANDS):
        websocket_api.async_register_command(hass, command)
