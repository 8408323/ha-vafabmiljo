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
   next-pickup-date sensors, per-bin-type "X tomorrow" binary sensors, and a
   Notification time entity - none of this needs BankID.
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

## HA-side notifications, dashboard, and automations

This integration doesn't send any notification or control anything itself - the
per-bin-type binary sensors ("Matavfall tomorrow", etc.) and the **Notification time**
entity are just the building blocks. The Notification time is entirely local to HA,
independent of BankID and of the app's own "Reminder time" - use it (or the binary
sensors directly) as the trigger for your own automations: a phone notification, a light
turning a color as a visual cue, whatever you want. See [`examples/`](examples/) for a
starter dashboard and a couple of automations, including exactly that light-cue idea.

## Known limitations

- Address search is server-side (`?address=<query>`) - the backend currently throws a SQL
  error if that parameter is missing entirely (it tries to join against every address
  nationwide and overflows a prepared-statement placeholder limit), so a search always
  needs at least one real character typed.
- BankID sessions expire after a period of inactivity; when that happens the integration
  will ask you to reauthenticate via HA's usual reauth flow (needs another QR scan).
- The BankID QR shown during setup is a single snapshot and doesn't visually rotate while
  waiting for you to scan it - HA has no supported way to update a progress step's displayed
  content mid-task without risking [a core bug](https://github.com/home-assistant/core/issues/95749)
  where the flow advances before it should. Scan it before the underlying BankID session
  itself expires (a few minutes).
- On at least one real account, `/services/invoices` never leaves the backend's 202
  "waiting" state for this integration's client, even though the official app works fine
  for the same account from another device - the **Latest invoice** sensor will show
  "Unknown" if you hit this. It's not fatal (see below) but the root cause is unconfirmed;
  a `keep_alive()` call was tried as a candidate fix and empirically ruled out. The rest
  of the integration is unaffected either way - every authenticated endpoint fails
  independently, so one being stuck doesn't take down invoices, sanitation, orders, etc.,
  let alone the pickup-schedule sensors that don't need login at all.
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
