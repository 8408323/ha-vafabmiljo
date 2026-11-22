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
3. Everything account-related (invoices with PDFs, fees, property, autogiro) appears once
   you log in to VafabMiljö **Mina sidor** with BankID, which you do from the **VafabMiljö**
   panel in the sidebar - see [Authentication](#authentication).
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
- BankID login to Mina sidor for account data: invoices (with a full history attribute and a
  `download_invoice` service action for the PDF), fees per service, property details with
  autogiro, and available extra orders
- Notification-preference switches and reminder-time entity, mirroring the app's own
  settings
- `vafabmiljo_new_invoice` / `vafabmiljo_invoice_due_reminder` events, fired exactly once
  per invoice (persisted across restarts), plus a local **Invoice reminder time** entity
- Diagnostics download and a "BankID connected" sensor
- A **VafabMiljö sidebar panel**: an isometric house with your bins lined up at the road
  (the next pickup's bins glow, a refuse truck on pickup day), next-pickup list, invoices
  with PDF links and a per-year total, contract fees, and the notification switches/times.
  Language follows Home Assistant or can be set in the panel: Swedish, Norwegian, Danish,
  Finnish, Icelandic, English
- **BankID login from the panel**: scan the live QR or open BankID on the same phone. The
  header shows how long the login has left, and a banner with a **Log in again** button
  appears when it's about to run out
- **Notifications per recipient**, set up in the panel (Settings → Notifications from Home
  Assistant): pick a phone (or any notify service), whether it gets the pickup reminder
  (the evening before or the same morning, at its own time), new invoices and invoice-due
  reminders. Off until you add a recipient, so it never doubles up with your own
  automations on the events
- A **pickup calendar** entity (one all-day event per pickup date) for HA's calendar view

### Panel development

The panel is React + Vite in `frontend/`, built into `custom_components/vafabmiljo/www/`
(committed, so HACS installs work without Node). `npm run dev` serves a preview with mock
data (`?in=0` / `?in=1` shifts the pickups to today / tomorrow, `?due=2` makes only the third bin due, `?lang=en`); run
`npm run build` before committing frontend changes.

## Authentication

Account data comes from VafabMiljö's customer portal **Mina sidor** (minasidor.vafabmiljo.se),
with **Swedish BankID**. (Up to 0.5.x it came from the app's own API, which since November 2026
answers "No customer data" - the VafabMiljö app can't log in either. The pickup schedule and the
app's notification settings still come from the app API, without any login.) Log in from the panel:

1. Open **VafabMiljö** in the sidebar and click **Log in** in the banner, the login chip in the
   header, or **Settings → Account (Mina sidor)**.
2. A dialog shows a live QR code. Scan it with the BankID app on another device. **On a phone or
   tablet**, tap **Open BankID on this device** instead: BankID opens on the same device, you
   approve there and switch back to Home Assistant (the app or the browser).
3. When BankID confirms, the dialog says you're logged in and the integration reloads with your
   invoices, fees and property. An unscanned QR is replaced by a new one by itself.

Only Home Assistant administrators can start a login. Setup itself doesn't log in, and Home
Assistant's reauthentication prompt points to the panel: a dialog can't keep an animated BankID
QR up to date.

The same-device link is BankID's universal link (`https://app.bankid.com/?autostarttoken=…&redirect=null`).
The panel uses `bankid:///` on a computer, which is what BankID for desktop answers to.
`redirect=null` means BankID doesn't send you anywhere afterwards. On Android it usually
goes back to Home Assistant by itself; on iPhone, switch back yourself.

**How long it lasts.** A Mina sidor login lasts **7 days** and can't be extended - that's
Mina sidor's own limit (its refresh cookie). Within those 7 days the integration renews the
15-minute access token by itself, also across restarts. Two days before the end it adds a
**Settings → Repairs** warning, the panel shows a banner, and the event
`vafabmiljo_login_expiring` is fired once (with `address` and `expires`), so you can send
yourself a phone reminder and log in again with two taps.

**When the login has run out.** The integration then:

- keeps the pickup sensors, calendar and pickup reminders working (they need no login),
- shows **Login expired** on the panel's Account card and turns the *BankID connected*
  sensor off,
- shows a **Log in again** banner at the top of the panel,
- adds a **Settings → Repairs** entry whose *Learn more* link opens the VafabMiljö panel; it
  disappears by itself once you've logged in again (or the integration is disabled),
- sends a one-time **"Login expired"** notification to every recipient that has it turned
  on (see below).

Log in again from the panel and everything comes back on the next refresh.

## HA-side notifications, dashboard, and automations

The simplest way is the panel: **Settings → Notifications from Home Assistant → Add
recipient**. Pick a phone (any `notify` service) and choose, per recipient, the pickup
reminder (the evening before or the same morning, at its own time), new invoices,
invoice-due reminders and login-expired alerts. Nothing is sent until you add a recipient.

If you prefer your own automations, the integration also provides the building blocks
(don't use both for the same message, or you'll get it twice):

- **Pickup reminders**: the per-bin-type binary sensors ("Matavfall tomorrow", etc.)
  and the **Notification time** entity (local to HA, independent of BankID and of the
  app's own "Reminder time").
- **New invoice**: the integration fires a `vafabmiljo_new_invoice` event on HA's event
  bus **exactly once per invoice**. The ids it has already announced are persisted in HA
  storage, so restarts, reloads and failed polls can't re-announce an old invoice, and
  the first run seeds that list with everything already on the account instead of
  announcing old history. Use an *event* trigger for this, not a state trigger on the
  Latest invoice sensor's attributes - a state trigger re-fires every time the entity
  comes back from unavailable, which is exactly how you end up pinged several times
  about the same invoice.
- **Invoice due tomorrow**: the day before an unpaid invoice is due, at the time set on
  the **Invoice reminder time** entity (default 18:00), the integration fires
  `vafabmiljo_invoice_due_reminder` - again once per invoice, persisted. Invoices the
  backend already reports as paid never get a reminder, and if HA was down at the
  reminder moment it is sent as soon as HA is back, as long as the invoice isn't due yet.

Both events carry `invoice_id`, `amount`, `invoice_date`, `due_date` (`YYYY-MM-DD`),
`days_until_due`, `payment_status`, `ocr_number`, `address`, `city` and `entry_id` in
`trigger.event.data`. They are fired for every configured address, so with more than one
property in HA, filter the trigger with `event_data:` on `address`/`city` (or `entry_id`) as
the examples do.

See [`examples/`](examples/) for a starter dashboard and automations covering all three,
including a light-cue idea and per-person `input_boolean` toggles so a household can
control who gets notified about what without touching automation YAML.

## Services

Call these from **Developer Tools → Actions** or in automations.

| Service | What it does |
|---------|---------------|
| `vafabmiljo.download_invoice` | Fetches one invoice as a PDF (`invoice_id` from the **Latest invoice** sensor's `invoices` attribute) and saves it to `/config/www/vafabmiljo/`, returning the local URL |

`www/` is served over plain HTTP with no authentication - anyone who has (or
guesses) the URL can fetch it, HA session or not. To limit that, the file is
saved under a random, unguessable name (not the invoice number) and deleted
automatically after 10 minutes, rather than kept around indefinitely at a
predictable path. Download it promptly; a second call to the service just
generates a fresh copy.

Wiring this to a dashboard button takes a script, not just a tap_action - a
Lovelace tile's `tap_action.data` isn't templated, so `invoice_id` has to be
resolved (e.g. "whichever invoice is latest") in a script instead, which the
tile then calls with no arguments. See [`examples/script.yaml`](examples/script.yaml)
and the tile in [`examples/dashboard.yaml`](examples/dashboard.yaml).

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
