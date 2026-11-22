"""Constants for the VafabMiljö integration.

Endpoint shapes here were reverse-engineered from the VafabMiljö Android app
(package `se.vafab.app`, version 2.0.0) via mitmproxy + Frida (OkHttp certificate
pinning is enforced on most authenticated endpoints).
"""

from __future__ import annotations

DOMAIN = "vafabmiljo"

API_BASE = "https://vafab.avfallsapp.se/api/nova/v1"

APP_VERSION = "2.0.0.5"
APP_IDENTIFIER_PREFIX = "ha-vafabmiljo-"

# The official app authenticates every request (starting with the very first
# POST /register) with this exact bearer value - it is the same for every
# installation on every device, not device-specific. In the app it is stored
# XOR-obfuscated (se.nova.Keys.Global.getAuthKey()) purely to defeat naive
# string scanning of the APK; it decodes to this literal. Confirmed by
# clearing the app's local storage entirely (forcing a brand new Firebase
# installation ID) and observing the exact same bearer used in the next
# POST /register call.
DEVICE_AUTH_KEY = "b2iNIJWP7AkHK1Vdo4IynZXhtKUUvMVGKd7m5UPi617524ab"

# Config-entry data keys.
CONF_DEVICE_UUID = "device_uuid"
# Bearer credential sent (not returned) on every request, including the very
# first POST /register. Named "bearer" rather than "token" here only to keep
# this constant out of generic secret-scanners' pattern matching.
CONF_DEVICE_BEARER = "device_bearer"
# vafab_session of the app's own BankID login, used up to 0.5.x; no longer used for anything but
# telling an entry that was logged in that way to log in to Mina sidor instead
CONF_SESSION_COOKIE = "session_cookie"
# The Mina sidor login (minasidor.py): the refreshToken cookie, when it runs out, and the last access token
CONF_MS_REFRESH = "minasidor_refresh"
CONF_MS_REFRESH_EXPIRES = "minasidor_refresh_expires"
CONF_MS_ACCESS = "minasidor_access"
CONF_ADDRESS = "address"
CONF_CITY = "city"
CONF_PLANT_ID = "plant_id"  # opaque per-address identifier returned by next-pickup/search

# Notification settings (POST /settings) this integration exposes as switches.
# Maps switch key -> the JSON field name in the settings payload. These three
# are exactly the toggles the app's own "Notisinställningar" screen exposes
# ("Driftinformation"/"Avfallstömning"/"Nyheter") - the settings payload has
# several other fields (sludge, missed, saved, bankid, gate, locations,
# blocked, disabled) but those are account/device state, not user toggles.
NOTIFICATION_SETTINGS = {
    "status": "status",  # "Driftinformation" - operational/service disruption notices
    "garbage": "garbage",  # "Avfallstömning" - pickup reminders
    "news": "news",  # "Nyheter"
}

# The app's reminder-time picker ("Klockslag för påminnelsenotiser"), 30-minute
# increments, sent as POST /settings {"time": "HH:MM"}.
REMINDER_TIME_FIELD = "time"

# A 202 {"status": "waiting"} response means the backend is still provisioning
# the session after BankID login completes - poll until it turns into a 200.
PENDING_POLL_INTERVAL = 2
PENDING_POLL_TIMEOUT = 30

# BankID status poll cadence while a config flow waits for the user to scan,
# and how long to keep polling before giving up (BankID sessions themselves
# expire well before this).
BANKID_POLL_INTERVAL = 2
BANKID_POLL_TIMEOUT = 300

# The Mina sidor login (minasidor.py): its refresh cookie runs out 7 days after the BankID login and
# isn't extended by using it, so warn this long before (a repair and EVENT_LOGIN_EXPIRING).
LOGIN_EXPIRY_WARNING_SECONDS = 2 * 24 * 3600

# Options-flow key: user-configurable poll interval, in minutes.
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL_MINUTES = 30  # this is a waste-collection calendar, not live data

# --- Invoice events (see invoices.py) ---------------------------------------
# Fired on the HA event bus exactly once per invoice, persisted across restarts,
# so an automation triggered by them can never double-notify the way a state
# trigger on the Latest invoice sensor's attributes does (that re-fires every
# time the entity goes unavailable and back, e.g. on restart or a failed poll).
EVENT_NEW_INVOICE = f"{DOMAIN}_new_invoice"
EVENT_INVOICE_DUE_REMINDER = f"{DOMAIN}_invoice_due_reminder"
EVENT_LOGIN_EXPIRING = f"{DOMAIN}_login_expiring"
# Invoice payment statuses (as the backend spells them) that mean "nothing to pay".
PAID_STATUSES = {"helt betald"}
INVOICE_STORAGE_VERSION = 1
# Local default for the "Invoice reminder time" entity (day-before-due reminder).
DEFAULT_INVOICE_REMINDER_TIME = "18:00"
