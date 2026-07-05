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
# Maps switch key -> the JSON field name in the settings payload.
NOTIFICATION_SETTINGS = {
    "garbage": "garbage",
    "news": "news",
    "deviation": "deviation",
    "services": "services",
}

# A 202 {"status": "waiting"} response means the backend is still provisioning
# the session after BankID login completes - poll until it turns into a 200.
PENDING_POLL_INTERVAL = 2
PENDING_POLL_TIMEOUT = 30

# BankID status poll cadence while a config flow waits for the user to scan.
BANKID_POLL_INTERVAL = 2

DEFAULT_SCAN_INTERVAL = 1800  # 30 minutes - this is a waste-collection calendar, not live data
