# ha-vafabmiljo

Home Assistant custom integration for [VafabMiljö](https://vafabmiljo.se) — Swedish
municipal waste collection covering the Västerås/Köping/Arboga area: pickup calendar,
invoices (with PDF download), waste-contract fees, and notification preferences.

> **Status**: Working — anonymous pickup calendar + BankID account data (invoices,
> contracts, notifications) implemented and live-tested against a real account.

Reverse-engineered from the official Android app (`se.vafab.app`) - none of this API is
publicly documented. See the endpoint catalog in the codebase comments (`api.py`) for
what was captured and what wasn't.

## Support

If you find this integration useful, you can buy me a coffee ☕

[![Buy me a coffee](https://img.buymeacoffee.com/button-api/?text=Buy+me+a+coffee&emoji=&slug=jhara&button_colour=FFDD00&font_colour=000000&font_family=Cookie&outline_colour=000000&coffee_colour=ffffff)](https://www.buymeacoffee.com/jhara)

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=8408323&repository=ha-vafabmiljo&category=integration)

Not (yet) in the HACS default store, so add it as a custom repository:

1. In HACS, go to **Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/8408323/ha-vafabmiljo` as an **Integration**.
3. Search for **VafabMiljö** and click **Download**.
4. Restart Home Assistant.

The integration ships its own brand icon (`custom_components/vafabmiljo/brand/`), so it
shows up correctly in HA's UI (HA 2026.3+, served locally - no
[home-assistant/brands](https://github.com/home-assistant/brands) submission needed for
that anymore).

### Manual

1. Copy `custom_components/vafabmiljo/` to your HA `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**, search for **VafabMiljö**.
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

## Features

- Next-pickup-date sensor per bin type (e.g. Restavfall, Matavfall, Plast och papper),
  usable with no login at all
- Per-bin-type "pickup tomorrow" binary sensors and a local Notification time entity, as
  building blocks for your own HA-side reminders/automations (separate from the app's own
  push notifications)
- BankID login for account data: invoices (with a full history attribute and a
  `download_invoice` service action for the PDF), waste-contract fees, property details,
  and available order/complaint types
- Notification-preference switches and reminder-time entity, mirroring the app's own
  settings
- Diagnostics download and a "BankID connected" sensor

## Authentication

Account data uses **Swedish BankID** (same as the app). During setup, a QR code is shown
in the HA config flow - scan it with the BankID app on your phone. It's a live snapshot,
not a rotating one (HA has no supported way to update it mid-task without risking [a core
bug](https://github.com/home-assistant/core/issues/95749)), and expires in about
25-30 seconds if unscanned - if that happens, just submit the form again for a fresh one.

BankID sessions expire after a period of inactivity; when that happens the integration
triggers HA's usual reauth flow (needs another QR scan).

## HA-side notifications, dashboard, and automations

This integration doesn't send any notification or control anything itself - the
per-bin-type binary sensors ("Matavfall tomorrow", etc.) and the **Notification time**
entity are just the building blocks. The Notification time is entirely local to HA,
independent of BankID and of the app's own "Reminder time" - use it (or the binary
sensors directly) as the trigger for your own automations: a phone notification, a light
turning a color as a visual cue, whatever you want. See [`examples/`](examples/) for a
starter dashboard and a couple of automations, including exactly that light-cue idea.

## Services

Call these from **Developer Tools → Actions** or in automations.

| Service | What it does |
|---------|---------------|
| `vafabmiljo.download_invoice` | Fetches one invoice as a PDF (`invoice_id` from the **Latest invoice** sensor's `invoices` attribute) and saves it to `/config/www/vafabmiljo/`, returning the local URL |

## Known limitations

- Address search is server-side (`?address=<query>`) - the backend currently throws a SQL
  error if that parameter is missing entirely (it tries to join against every address
  nationwide and overflows a prepared-statement placeholder limit), so a search always
  needs at least one real character typed.
- Order/complaint *submission* isn't implemented - only their read-only "available
  actions" templates were ever captured, never an actual submit call, so we won't guess
  at that wire format. The "Available orders"/"Available complaints" sensors just report
  what request types exist, not anything you can act on yet.
- Customer/contact details (which include your personal number) are deliberately not
  exposed as entities.
- Account data (properties, invoices, contracts, etc.) genuinely requires BankID - it's
  not enough to just know an address. Confirmed directly against the backend: those
  endpoints return 403 without a BankID session, even with a validly bound address.

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

## Contributing

Pull requests are welcome. Please open an issue first to discuss what you'd like to change.

## License

MIT
