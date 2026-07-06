# ha-vafabmiljo

A Home Assistant custom integration for [VafabMiljö](https://vafabmiljo.se) (Swedish
municipal waste collection - Västerås/Köping/Arboga area): next pickup dates per bin
type, invoices, waste-contract fees, and (read-only) available order/complaint types.

Reverse-engineered from the official Android app (`se.vafab.app`) - none of this API is
publicly documented. See the endpoint catalog in the codebase comments (`api.py`) for
what was captured and what wasn't.

## Installation

Not (yet) in the HACS default store - it has no brand icon in
[home-assistant/brands](https://github.com/home-assistant/brands), which HACS requires
for default-store listing. Add it as a HACS custom repository instead
(HACS → ⋮ → Custom repositories → this repo URL, category "Integration").

## Setup

1. Add the integration in HA (Settings → Devices & services → Add integration →
   VafabMiljö).
2. Search for and select your address. This works anonymously and immediately gives you
   next-pickup-date sensors.
3. Optionally connect your account via BankID (scan the QR shown in the setup dialog) to
   also get invoice, waste-contract, and notification-preference entities (matching the
   app's own "Driftinformation"/"Avfallstömning"/"Nyheter" toggles and reminder-time
   picker), plus a diagnostic "BankID connected" sensor.
4. Have more than one VafabMiljö property/address? Just repeat setup for each one - a
   second entry for a different address is fine. Adding the *same* address twice is
   blocked. Moved, or picked the wrong address? Reconfigure the entry (⋮ → Reconfigure)
   instead of removing and re-adding it - your BankID login carries over.
5. The poll interval (default 30 minutes) is configurable per entry (⋮ → Configure) if
   you want it faster or slower - this is a waste-collection calendar, not live data, so
   the default is usually fine.

Available in English and Swedish, matching HA's own language setting.

## Known limitations

- Address search downloads the backend's full nationwide address list once during setup
  (that's genuinely how the official app does it too - there's no server-side query
  filtering). Filtering happens locally.
- BankID sessions expire after a period of inactivity; when that happens the integration
  will ask you to reauthenticate via HA's usual reauth flow (needs another QR scan).
- Order/complaint *submission* isn't implemented - only their read-only "available
  actions" templates were ever captured, never an actual submit call, so we won't guess
  at that wire format. The "Available orders"/"Available complaints" sensors just report
  what request types exist, not anything you can act on yet.
- Customer/contact details (which include your personal number) are deliberately not
  exposed as entities.

## Development

Traffic was captured with mitmproxy over ADB (WiFi), with Frida bypassing OkHttp
certificate pinning on a rooted test device. Capture files are never committed (see
`.gitignore`) since they contain personal data.

The `homeassistant` PyPI package isn't a dependency here - tests stub the handful of HA
symbols the integration actually imports (see `tests/conftest.py`) rather than pulling in
the full HA test harness.

```bash
uv sync --dev
uv run pytest tests/ --cov=custom_components/vafabmiljo --cov-report=term-missing
uv run ruff check custom_components/ tests/
uv run ruff format custom_components/ tests/
```
