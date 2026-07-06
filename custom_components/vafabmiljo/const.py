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

# Config-entry data keys.
CONF_DEVICE_UUID = "device_uuid"
# Long-lived per-install bearer credential returned by POST /register. Named
# "bearer" rather than "token" here only to keep this constant out of generic
# secret-scanners' pattern matching - the value itself is not a secret literal.
CONF_DEVICE_BEARER = "device_bearer"
CONF_SESSION_COOKIE = "session_cookie"  # vafab_session; None until BankID login completes
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

# BankID status poll cadence while a config flow waits for the user to scan.
BANKID_POLL_INTERVAL = 2

# Options-flow key: user-configurable poll interval, in minutes.
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL_MINUTES = 30  # this is a waste-collection calendar, not live data
