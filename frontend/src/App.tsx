import { useEffect, useState } from "react";
import House, { SceneBin, binColor } from "./House";
import { LANGS, T, pick } from "./i18n";

// Everything comes from the integration's own entities (entity registry + states), so the panel shows exactly
// what automations see. Only the notification recipients have their own websocket API (reminders.py).
type Ent = { entity_id: string; device_id?: string; platform: string; translation_key?: string };
type St = { entity_id: string; state: string; attributes: Record<string, any> };
type Invoice = { id: number; amount: number | null; invoice_date: string | null; due_date: string | null; payment_status: string | null };
type Addr = {
  id: string; entryId?: string; name: string; pickups: St[]; invoice?: St; bankid?: St; fees: St[]; property?: St; calendar?: St; switches: St[]; times: St[];
};
type Ctx = { hass: any; t: T; locale: string };

const TABS = ["overview", "invoices", "settings"] as const;
type Theme = "auto" | "light" | "dark";
type Tab = (typeof TABS)[number];
const PAID = new Set(["helt betald"]);  // same as const.PAID_STATUSES

const fmt = (v: number | null | undefined, d = 0, u = "") =>
  v == null || Number.isNaN(v) ? "–" : `${v.toLocaleString("sv-SE", { minimumFractionDigits: d, maximumFractionDigits: d })}${u ? " " + u : ""}`;
const day = (iso: string) => new Date(iso.slice(0, 10) + "T00:00:00");
// "today" in Home Assistant's timezone, not the browser's (someone checking the panel while travelling);
// set from hass.config.time_zone on every render
let haTz: string | undefined;
const todayIso = () => new Date().toLocaleDateString("sv-SE", { timeZone: haTz });  // sv-SE formats as YYYY-MM-DD
const utc = (iso: string) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
const daysUntil = (iso: string) => Math.round((utc(iso) - utc(todayIso())) / 864e5);
const isPaid = (i: Invoice) => PAID.has(String(i.payment_status ?? "").trim().toLowerCase());

// "förfaller om 3 dagar" / "förföll 1 nov." for an unpaid invoice, the invoice date for a paid one
function dueText(i: Invoice, t: T, locale: string) {
  if (!i.due_date) return "";
  const n = daysUntil(i.due_date);
  if (isPaid(i) || n < 0) return isPaid(i) ? day(i.due_date).toLocaleDateString(locale) : t.due_was.replace("{date}", day(i.due_date).toLocaleDateString(locale, { day: "numeric", month: "short" }));
  return n === 0 ? t.due_today : n === 1 ? t.due_tomorrow : t.due_in.replace("{n}", String(n));
}

// The Mina sidor login lasts 7 days and can't be extended; the "BankID connected" sensor carries when it runs out.
type LoginState = "none" | "ok" | "expiring" | "expired" | "unknown";
type LoginInfo = { state: LoginState; days: number | null; until: string };
function loginInfo(a: Addr | undefined, locale: string): LoginInfo {
  const s = a?.bankid;
  if (!s) return { state: "none", days: null, until: "" };
  if (s.state === "off") return { state: "expired", days: null, until: "" };
  if (s.state !== "on") return { state: "unknown", days: null, until: "" };
  const iso: string | undefined = s.attributes.login_expires;
  if (!iso) return { state: "ok", days: null, until: "" };
  const at = new Date(iso);
  const days = Math.max(0, Math.floor((at.getTime() - Date.now()) / 864e5));
  const until = at.toLocaleString(locale, { weekday: "long", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  return { state: days < 2 ? "expiring" : "ok", days, until };
}
const leftText = (li: LoginInfo, t: T) =>
  li.days == null ? t.bankid_ok : li.days === 0 ? t.login_left_0 : li.days === 1 ? t.login_left_1 : t.login_left.replace("{n}", String(li.days));

type Entry = { entry_id: string; title: string; state: string };

// One address per *loaded* config entry (so an entry whose entities are all disabled still shows, and a
// disabled entry doesn't). entries is null until config_entries/get answered (or when it isn't allowed);
// then the addresses are derived from the entities' devices instead.
export function addresses(hass: any, entries: Entry[] | null): Addr[] {
  const by: Record<string, Addr> = {};
  const blank = (entryId: string | undefined, name: string): Addr =>
    ({ id: entryId ?? name, entryId, name, pickups: [], fees: [], switches: [], times: [] });
  for (const en of entries ?? []) if (en.state === "loaded") by[en.entry_id] = blank(en.entry_id, en.title);
  for (const e of Object.values((hass.entities ?? {}) as Record<string, Ent>)) {
    if (e.platform !== "vafabmiljo" || !e.device_id) continue;
    const s: St | undefined = hass.states[e.entity_id];
    const dev = hass.devices?.[e.device_id];
    const entryId: string | undefined = dev?.primary_config_entry ?? dev?.config_entries?.[0];
    if (entries && !(entryId && by[entryId])) continue;  // entry not loaded
    const a = entries ? by[entryId!] : (by[e.device_id] ??= blank(entryId, dev?.name_by_user || dev?.name || "VafabMiljö"));
    if (!entries) a.id = e.device_id;
    if (!s) continue;
    const domain = e.entity_id.split(".")[0];
    if (domain === "sensor" && s.attributes.device_class === "date") a.pickups.push(s);
    else if (e.translation_key === "latest_invoice") a.invoice = s;
    else if (e.translation_key === "property") a.property = s;
    else if (e.translation_key === "bankid_connected") a.bankid = s;
    else if (domain === "sensor" && "pickups_per_year" in s.attributes) a.fees.push(s);
    else if (domain === "calendar") a.calendar = s;
    else if (domain === "switch") a.switches.push(s);
    else if (domain === "time") a.times.push(s);
  }
  return Object.values(by).sort((a, b) => a.name.localeCompare(b.name));
}

// friendly names are "<device name> <entity name>"; the panel already says which address it shows
const short = (s: St, a: Addr) => {
  const n: string = s.attributes.friendly_name ?? s.entity_id;
  return n.startsWith(a.name + " ") ? n.slice(a.name.length + 1) : n;
};

function when(iso: string | undefined, { t, locale }: Ctx) {
  if (!iso || iso === "unknown" || iso === "unavailable") return { when: "–", sub: "", days: null };
  const n = daysUntil(iso);
  // the weekday spelled out, so "which day" is never in doubt
  const date = day(iso).toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "short" });
  const rel = n === 0 ? t.today : n === 1 ? t.tomorrow : t.in_days.replace("{n}", String(n));
  const cap = (x: string) => x[0].toUpperCase() + x.slice(1);
  return n <= 1 ? { when: cap(rel), sub: date, days: n } : { when: cap(date), sub: rel, days: n };
}

// The next pickup for the hero: when, and which bins (all bins sharing the earliest date)
function nextPickup(a: Addr, ctx: Ctx) {
  const bins = a.pickups.map((s) => ({ type: s.attributes.bin_type ?? short(s, a), ...when(s.state, ctx) }))
    .filter((b) => b.days != null).sort((x, y) => x.days! - y.days!);
  if (!bins.length) return null;
  const first = bins.filter((b) => b.days === bins[0].days);
  return { when: first[0].when, sub: first[0].sub, types: first.map((b) => b.type) };
}

// The panel's own mark: a leaf over a bin lid
function Logo() {
  return (
    <svg className="logo" viewBox="0 0 34 34" aria-hidden="true">
      <rect width="34" height="34" rx="10" fill="rgba(255,255,255,.14)" />
      <path d="M9 14h16l-1.6 12.2a2 2 0 0 1-2 1.8h-8.8a2 2 0 0 1-2-1.8z" fill="#fff" opacity=".92" />
      <rect x="7.5" y="11" width="19" height="3" rx="1.5" fill="#fff" />
      <path d="M17 9.5c0-3.6 2.6-5.6 6.4-5.5.2 3.8-1.9 6.2-5.6 6.2" fill="#7dffb8" />
      <path d="M14.5 17.5v7M19.5 17.5v7" stroke="#17694a" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export default function App({ hass, narrow }: { hass: any; narrow: boolean }) {
  const [lang, setLangState] = useState<string | null>(() => localStorage.getItem("vm_lang"));
  const setLang = (x: string | null) => { setLangState(x); x ? localStorage.setItem("vm_lang", x) : localStorage.removeItem("vm_lang"); };
  const { t, locale } = pick(hass.locale?.language ?? hass.language, lang);
  haTz = hass.config?.time_zone;
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem("vm_tab") as Tab) || "overview");
  const [sel, setSel] = useState<string | null>(() => localStorage.getItem("vm_addr"));
  const [entries, setEntries] = useState<Entry[] | null>(null);
  // refetched when the set of VafabMiljö states changes (an entry loaded, unloaded or reloaded)
  const stateKey = Object.keys(hass.states).filter((k) => hass.entities?.[k]?.platform === "vafabmiljo").length;
  useEffect(() => {
    hass.connection.sendMessagePromise({ type: "config_entries/get", domain: "vafabmiljo" })
      .then((r: Entry[]) => setEntries(r)).catch(() => setEntries(null));
  }, [stateKey]);
  const list = addresses(hass, entries);
  const a = list.find((x) => x.id === sel) ?? list[0];
  const ctx = { hass, t, locale };
  const go = (x: Tab) => { setTab(x); localStorage.setItem("vm_tab", x); };
  const lg = useLogin(a?.entryId, hass);
  const li = loginInfo(a, locale);
  const admin = hass.user?.is_admin !== false;
  // one login dialog for the whole panel: the header chip, the overview banner and Settings all open it
  const onLogin = admin && a?.entryId ? lg.start : undefined;
  // light / dark / auto, remembered per browser (like the language)
  const [theme, setThemeState] = useState<Theme>(() => {
    try { return (localStorage.getItem("vm_theme") as Theme) || "auto"; } catch { return "auto"; }
  });
  const setTheme = (x: Theme) => {
    setThemeState(x);
    try { x === "auto" ? localStorage.removeItem("vm_theme") : localStorage.setItem("vm_theme", x); } catch { /* private mode */ }
  };

  // its own light/dark look: "auto" follows Home Assistant's dark mode (or the system's when HA doesn't say)
  const sysDark = hass.themes?.darkMode ?? window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  const dark = theme === "auto" ? sysDark : theme === "dark";
  const nx = a ? nextPickup(a, ctx) : null;

  return (
    <div className={`page ${narrow ? "narrow" : ""} ${dark ? "dark" : ""}`}>
      <header className="hero">
        <div className="wrap">
          <div className="hero-top">
            <div className="brand"><Logo /><span className="brand-name">{t.title}<small>{t.tagline}</small></span></div>
            <div className="hero-actions">
              <nav className="tabs">
                {TABS.map((x) => <button key={x} className={tab === x ? "on" : ""} onClick={() => go(x)}>{t[`tab_${x}`]}</button>)}
              </nav>
              <button className="theme-btn" onClick={() => setTheme(dark ? "light" : "dark")}
                title={dark ? t.theme_light : t.theme_dark} aria-label={dark ? t.theme_light : t.theme_dark}>
                {dark ? "☀️" : "🌙"}
              </button>
            </div>
          </div>
          {a && <div className="hero-main">
            <div>
              <div className="hero-kicker">{t.next}</div>
              <div className="hero-title">{nx?.when ?? "–"}{nx && nx.types.length > 0 && <span className="types">{nx.types.join(" · ")}</span>}</div>
              {nx?.sub && <div className="hero-sub">{nx.sub}</div>}
            </div>
            <div className="hero-side">
              {list.length > 1 ? (
                <div className="seg">{list.map((x) => (
                  <button key={x.id} className={x.id === a.id ? "on" : ""} onClick={() => { setSel(x.id); localStorage.setItem("vm_addr", x.id); }}>{x.name}</button>
                ))}</div>
              ) : <span className="chip">📍 {a.name}</span>}
              <AccountChip li={li} t={t} onClick={() => (li.state === "ok" || !onLogin ? go("settings") : onLogin())} />
            </div>
          </div>}
        </div>
      </header>
      <main className="wrap">
        {!a ? <div className="card">{hass.entities ? t.none : t.loading}</div> : (
          <>
            <LoginBanner li={li} t={t} onLogin={onLogin} />
            {tab === "overview" && <Overview {...ctx} a={a} />}
            {tab === "invoices" && <Invoices {...ctx} a={a} />}
            {tab === "settings" && <Settings {...ctx} a={a} li={li} onLogin={onLogin} lang={lang} setLang={setLang} theme={theme} setTheme={setTheme} />}
          </>
        )}
      </main>
      {lg.login && <LoginModal lg={lg} t={t} />}
    </div>
  );
}

/* ---------------- Overview ---------------- */
function Overview({ a, ...ctx }: Ctx & { a: Addr }) {
  const { t, locale } = ctx;
  const bins = a.pickups.map((s) => ({ type: s.attributes.bin_type ?? short(s, a), ...when(s.state, ctx) }));
  const first = Math.min(...bins.map((b) => b.days ?? Infinity));
  // no known date at all (e.g. VafabMiljö unreachable): nothing is "next"
  const scene: SceneBin[] = bins.map((b) => ({ ...b, next: Number.isFinite(first) && b.days === first }));
  const next = scene.filter((b) => b.next);
  const tonight = scene.filter((b) => b.days === 1), now = scene.filter((b) => b.days === 0);
  const inv = a.invoice?.attributes.invoices?.[0] as Invoice | undefined;
  const autogiro = a.property?.attributes.autogiro === true;
  const sorted = [...scene].sort((x, y) => (x.days ?? 1e9) - (y.days ?? 1e9));

  return (
    <>
      <div className={`banner ${tonight.length || now.length ? "on" : ""}`}>
        {now.length ? `🚛 ${t.put_out_now}: ${now.map((b) => b.type).join(", ")}`
          : tonight.length ? `🗑️ ${t.put_out}: ${tonight.map((b) => b.type).join(", ")}` : `✅ ${t.nothing_tonight}`}
      </div>
      <div className="grid-overview">
        <div className="card scene">
          <House bins={scene} truck={now.length > 0} />
          {/* same left-to-right order as the bins in the drawing */}
          <div className="bin-tags">{scene.map((b) => (
            <div key={b.type} className={`bin-tag ${b.next ? "next" : ""}`}>
              <span className="swatch" style={{ background: binColor(b.type) }} />
              <div><div className="label">{b.type}</div><b>{b.when}</b> <span className="muted">{b.sub}</span></div>
            </div>
          ))}</div>
        </div>
        <div className="side">
          <div className="card">
            {/* the next pickup itself is the hero's headline; this card lists them all */}
            <h2 style={{ marginBottom: 8 }}>{t.upcoming}</h2>
            <table>
              <tbody>{sorted.map((b) => (
                <tr key={b.type} className={b.next ? "next" : ""}>
                  <td><span className="dot" style={{ background: binColor(b.type) }} />{b.type}</td>
                  <td className="r">{b.days != null && b.days <= 1 ? `${b.when}, ${b.sub}` : `${b.when}`}</td>
                  <td className="r muted">{b.days != null && b.days > 1 ? b.sub : ""}</td>
                </tr>
              ))}</tbody>
            </table>
            {a.calendar && <div className="muted foot-note">📅 {t.calendar_info}</div>}
          </div>
          {(inv || a.fees.length > 0) && (
            <div className="kpis">
              {inv && <div className="stat">
                <div className="label">{t.latest_invoice}</div>
                <div className="value">{fmt(inv.amount, 0, "kr")}</div>
                <div className="stat-sub">
                  <Status inv={inv} t={t} />
                  <span className="muted">{dueText(inv, t, locale)}</span>
                  {autogiro && <span className="pill accent">{t.autogiro}</span>}
                </div>
              </div>}
              {a.fees.length > 0 && <div className="stat">
                <div className="label">{t.annual_fee}</div>
                {a.fees.map((f) => (
                  <div key={f.entity_id} className="fee">
                    <span>{short(f, a)}</span>
                    <b>{fmt(Number(f.state), 0, f.attributes.unit_of_measurement)}</b>
                    {f.attributes.pickups_per_year && <span className="muted">{f.attributes.pickups_per_year} {t.per_year}</span>}
                  </div>
                ))}
                {a.fees.length > 1 && <div className="fee total">
                  <span>{t.total}</span>
                  <b>{fmt(a.fees.reduce((sum, f) => sum + (Number(f.state) || 0), 0), 0, a.fees[0].attributes.unit_of_measurement)}</b>
                </div>}
              </div>}
            </div>
          )}
          {a.property && a.property.state !== "unknown" && <div className="muted">{t.property}: {a.property.state}</div>}
        </div>
      </div>
    </>
  );
}

function Status({ inv, t }: { inv: Invoice; t: T }) {
  const paid = PAID.has(String(inv.payment_status ?? "").trim().toLowerCase());
  const overdue = !paid && inv.due_date != null && daysUntil(inv.due_date) < 0;
  return <span className={`pill ${paid ? "pos" : overdue ? "neg" : "warn"}`} title={inv.payment_status ?? ""}>
    {paid ? t.paid : overdue ? t.overdue : t.unpaid}
  </span>;
}

/* ---------------- Invoices ---------------- */
function Invoices({ a, hass, t, locale }: Ctx & { a: Addr }) {
  const [err, setErr] = useState<string | null>(null);
  const invoices: Invoice[] = a.invoice?.attributes.invoices ?? [];
  if (!a.invoice) return <div className="card">{t.no_invoices}</div>;
  const years: Record<string, number> = {};
  for (const i of invoices) if (i.invoice_date) years[i.invoice_date.slice(0, 4)] = (years[i.invoice_date.slice(0, 4)] ?? 0) + (i.amount ?? 0);
  const max = Math.max(1, ...Object.values(years));
  const d = (iso: string | null) => (iso ? day(iso).toLocaleDateString(locale) : "–");

  const open = async (id: number) => {
    // opened before the await so the popup blocker sees it as part of the click
    const w = window.open("", "_blank");
    try {
      const r = await hass.callService("vafabmiljo", "download_invoice", { invoice_id: id }, undefined, false, true);
      if (w) w.location.href = r.response.path; else window.location.href = r.response.path;
      setErr(null);
    } catch (e: any) { w?.close(); setErr(`${t.download_failed}: ${e?.message ?? e}`); }
  };

  const unpaid = invoices.filter((i) => !isPaid(i));
  const toPay = unpaid.reduce((sum, i) => sum + (i.amount ?? 0), 0);
  const nextDue = unpaid.filter((i) => i.due_date).sort((x, y) => x.due_date!.localeCompare(y.due_date!))[0];
  const autogiro = a.property?.attributes.autogiro;
  const thisYear = years[todayIso().slice(0, 4)] ?? 0;

  return (
    <>
    <div className="kpis">
      <div className="stat">
        <div className="label">{t.unpaid_total}</div>
        <div className={`value ${unpaid.length ? "" : "pos"}`}>{unpaid.length ? fmt(toPay, 0, "kr") : t.all_paid}</div>
        {unpaid.length > 0 && <div className="muted">{unpaid.length} × {t.unpaid.toLowerCase()}</div>}
      </div>
      <div className="stat">
        <div className="label">{t.next_due}</div>
        <div className="value">{nextDue ? d(nextDue.due_date) : "–"}</div>
        {nextDue && <div className="muted">{dueText(nextDue, t, locale)}</div>}
      </div>
      <div className="stat">
        <div className="label">{t.this_year}</div>
        <div className="value">{fmt(thisYear, 0, "kr")}</div>
      </div>
      {autogiro != null && <div className="stat">
        <div className="label">{t.payment}</div>
        <div className="value">{autogiro ? t.autogiro : t.by_invoice}</div>
      </div>}
    </div>
    <div className="grid-overview">
      <div className="card">
        <h2>{t.invoices}</h2>
        {err && <div className="neg">{err}</div>}
        <table className="money">
          <thead><tr><th>{t.date}</th><th>{t.due}</th><th>{t.amount}</th><th>{t.status}</th><th>{t.pdf}</th></tr></thead>
          <tbody>{invoices.map((i) => (
            <tr key={i.id}>
              <td>{d(i.invoice_date)}</td><td>{d(i.due_date)}</td><td>{fmt(i.amount, 2, "kr")}</td>
              <td><Status inv={i} t={t} /></td>
              <td><button className="link" onClick={() => open(i.id)}>{t.open}</button></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="card">
        <h2>{t.per_year_total}</h2>
        {Object.entries(years).sort(([x], [y]) => y.localeCompare(x)).map(([y, v]) => (
          <div key={y} className="year">
            <span>{y}</span><div className="meter"><div style={{ width: `${(100 * v) / max}%` }} /></div><b>{fmt(v, 0, "kr")}</b>
          </div>
        ))}
      </div>
    </div>
    </>
  );
}

/* ---------------- Settings ---------------- */
function Settings({ a, hass, t, li, onLogin, lang, setLang, theme, setTheme }:
  Ctx & { a: Addr; li: LoginInfo; onLogin?: () => void; lang: string | null; setLang: (x: string | null) => void;
    theme: Theme; setTheme: (x: Theme) => void }) {
  return (
    <div className="settings-grid">
      <Account li={li} t={t} onLogin={onLogin} />
      {/* keyed by entry: switching address starts fresh, so one address's list can't be saved to another */}
      <Recipients key={`rec-${a.entryId}`} a={a} hass={hass} t={t} />
      <div className="card">
        <h2>{t.appearance}</h2>
        <label className="row">
          <span>{t.language}</span>
          <select value={lang ?? ""} onChange={(e) => setLang(e.target.value || null)}>
            <option value="">{t.lang_auto}</option>
            {Object.entries(LANGS).map(([code, [, , name]]) => <option key={code} value={code}>{name}</option>)}
          </select>
        </label>
        <div className="row">
          <span>{t.theme}</span>
          <div className="seg">
            {(["auto", "light", "dark"] as const).map((x) => (
              <button key={x} className={theme === x ? "on" : ""} onClick={() => setTheme(x)}>
                {x === "auto" ? t.theme_auto : x === "light" ? `☀️ ${t.theme_light}` : `🌙 ${t.theme_dark}`}
              </button>
            ))}
          </div>
        </div>
        <div className="muted">{t.theme_info}</div>
      </div>
      {a.switches.length > 0 && <div className="card">
        <h2>{t.notifications}</h2>
        {a.switches.map((s) => (
          <label key={s.entity_id} className="row">
            <span>{short(s, a)}</span>
            <input type="checkbox" className="toggle" checked={s.state === "on"} disabled={s.state === "unavailable"}
              onChange={() => hass.callService("switch", s.state === "on" ? "turn_off" : "turn_on", { entity_id: s.entity_id })} />
          </label>
        ))}
      </div>}
      {a.times.length > 0 && <div className="card">
        <h2>{t.reminders}</h2>
        {a.times.map((s) => (
          <label key={s.entity_id} className="row">
            <span>{short(s, a)}</span>
            <input type="time" value={s.state.slice(0, 5)} disabled={s.state === "unavailable"}
              onChange={(e) => e.target.value && hass.callService("time", "set_value", { entity_id: s.entity_id, time: `${e.target.value}:00` })} />
          </label>
        ))}
      </div>}
    </div>
  );
}

/* ---------------- Mina sidor login (BankID) ---------------- */
type Login = { status: "waiting" | "done" | "failed" | "none"; hint?: string | null; qr?: string | null; autostart?: string | null; autostart_desktop?: string | null };
// BankID wants its universal link (https://app.bankid.com) on phones and tablets and bankid:/// on a computer.
// iPadOS reports itself as a Mac, so a touch screen on a "Mac" counts as a tablet.
const MOBILE = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);

type LoginCtl = { login: Login | null; err: string | null; start: () => void; close: () => void };
function useLogin(entryId: string | undefined, hass: any): LoginCtl {
  const [login, setLogin] = useState<Login | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const send = (type: string) => hass.connection.sendMessagePromise({ type, entry_id: entryId });
  useEffect(() => {
    if (login?.status !== "waiting") return;
    // the QR is animated (a new one every couple of seconds), so keep it fresh
    const id = setInterval(() => send("vafabmiljo/login/status").then(setLogin).catch(() => undefined), 1500);
    return () => clearInterval(id);
  }, [login?.status, entryId]);
  const start = async () => {
    setErr(null);
    setLogin({ status: "waiting" });
    try { setLogin(await send("vafabmiljo/login/start")); } catch (e: any) { setLogin({ status: "failed" }); setErr(e?.message ?? String(e)); }
  };
  const close = () => { if (login?.status === "waiting") send("vafabmiljo/login/cancel").catch(() => undefined); setLogin(null); setErr(null); };
  return { login, err, start, close };
}

function LoginModal({ lg, t }: { lg: LoginCtl; t: T }) {
  const { login, err, start, close } = lg;
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [login?.status]);
  if (!login) return null;
  const href = MOBILE ? login.autostart : login.autostart_desktop ?? login.autostart;
  // on a phone the same-device button comes first and is the primary one; the QR is for another device
  const open = href && <a className={MOBILE ? "btn primary wide" : "btn wide"} href={href}>{t.open_on_device}</a>;
  return (
    <div className="modal-bg" onPointerDown={(e) => e.target === e.currentTarget && close()}>
      <div className="modal card login" role="dialog" aria-modal="true" aria-label={t.login}>
        <div className="login-head"><span className="bankid-mark" aria-hidden="true">iD</span><h2>{t.login}</h2></div>
        <div className="muted">Mina sidor · VafabMiljö</div>
        {login.status === "waiting" && <>
          {MOBILE && open}
          <div className="qr-wrap">
            {login.qr ? <img className="qr" src={login.qr} alt="BankID QR" /> : <div className="qr skeleton" />}
          </div>
          <div className="muted">{t.scan_qr}</div>
          {!MOBILE && open}
        </>}
        {login.status === "done" && <div className="login-result pos">✓ {t.login_done}</div>}
        {(login.status === "failed" || login.status === "none") && <div className="login-result neg">{t.login_failed}</div>}
        {err && <div className="neg">{err}</div>}
        <div className="modal-actions">
          <span style={{ flex: 1 }} />
          {login.status === "failed" && <button className="btn" onClick={start}>{t.relogin}</button>}
          <button className={`btn ${login.status === "done" ? "primary" : ""}`} onClick={close}>{login.status === "done" ? "OK" : t.cancel}</button>
        </div>
      </div>
    </div>
  );
}

// Header chip: the login at a glance; clicking it logs in (or opens Settings when all is well).
function AccountChip({ li, t, onClick }: { li: LoginInfo; t: T; onClick: () => void }) {
  if (li.state === "unknown") return null;
  const cls = li.state === "ok" ? "ok" : li.state === "expiring" ? "warn" : "bad";
  const text = li.state === "ok" || li.state === "expiring" ? leftText(li, t) : li.state === "expired" ? t.relogin : t.login_out;
  return <button className={`acct ${cls}`} onClick={onClick} title={li.until ? t.login_valid_until.replace("{when}", li.until) : undefined}>
    <span className="acct-dot" />{text}
  </button>;
}

// Shown on every tab when the login needs attention: never done, run out, or running out within two days.
function LoginBanner({ li, t, onLogin }: { li: LoginInfo; t: T; onLogin?: () => void }) {
  if (li.state === "ok" || li.state === "unknown") return null;
  const text = li.state === "expiring" ? t.login_expiring.replace("{when}", li.until) : li.state === "expired" ? t.bankid_expired : t.login_needed;
  return (
    <div className={`banner action ${li.state === "expiring" ? "warn" : "bad"}`}>
      <span>{li.state === "expiring" ? "⏳" : "🔑"} {text}</span>
      {onLogin && <button className="btn primary" onClick={onLogin}>{li.state === "none" ? t.login : t.relogin}</button>}
    </div>
  );
}

function Account({ li, t, onLogin }: { li: LoginInfo; t: T; onLogin?: () => void }) {
  // The "BankID connected" sensor exists once a login was ever made and is off while it has run out;
  // unavailable/unknown only means a refresh failed (e.g. VafabMiljö is down), not an expiry.
  const [cls, text] = li.state === "none" ? ["", t.bankid_none] : li.state === "ok" || li.state === "expiring"
    ? [li.state === "ok" ? "pos" : "warn", t.bankid_ok] : li.state === "expired" ? ["warn", t.bankid_expired] : ["", t.bankid_unknown];
  return (
    <div className="card">
      <h2>{t.account}</h2>
      <div className={`muted ${cls}`} style={{ margin: "6px 0" }}>{text}</div>
      {li.until && <div className="muted">{t.login_valid_until.replace("{when}", li.until)}</div>}
      {onLogin ? <button className="btn primary" onClick={onLogin}>{li.state === "none" ? t.login : t.relogin}</button>
        : <div className="muted">{t.admin_only}</div>}
    </div>
  );
}

/* ---------------- Notification recipients ---------------- */
type Recipient = { service: string; pickup: boolean; pickup_days_before: 0 | 1; pickup_time: string; new_invoice: boolean; invoice_due: boolean; session_expired: boolean };
const NEW: Omit<Recipient, "service"> = { pickup: true, pickup_days_before: 1, pickup_time: "18:00", new_invoice: true, invoice_due: true, session_expired: true };

// "notify.x" entity -> its friendly name; "mobile_app_jonathans_iphone" -> the HA app's device name when we can find it
function serviceName(hass: any, service: string) {
  if (service.startsWith("notify.")) return hass.states[service]?.attributes?.friendly_name ?? service;
  const slug = service.replace(/^mobile_app_/, "");
  const dev = Object.values((hass.devices ?? {}) as Record<string, any>).find((d) => (d.name ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "_") === slug);
  const name = dev?.name_by_user || dev?.name || slug.replace(/_/g, " ");
  return name[0].toUpperCase() + name.slice(1);
}

function Recipients({ a, hass, t }: { a: Addr; hass: any; t: T }) {
  const [list, setList] = useState<Recipient[] | null>(null);
  const [services, setServices] = useState<string[]>([]);
  const [edit, setEdit] = useState<{ r: Recipient; index: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const admin = hass.user?.is_admin !== false;

  useEffect(() => {
    if (!a.entryId || !admin) return;  // the recipient list (people's phones) is admin-only
    hass.connection.sendMessagePromise({ type: "vafabmiljo/notify/get", entry_id: a.entryId })
      .then((r: any) => { setList(r.recipients); setServices(r.services); }).catch((e: any) => setErr(e?.message ?? String(e)));
  }, [a.entryId]);

  const save = async (next: Recipient[]) => {
    try {
      const r = await hass.connection.sendMessagePromise({ type: "vafabmiljo/notify/set", entry_id: a.entryId, recipients: next });
      setList(r.recipients); setEdit(null); setErr(null);
    } catch (e: any) { setErr(e?.message ?? String(e)); }
  };
  const summary = (r: Recipient) => [
    r.pickup && `${t.pickup_reminder}: ${(r.pickup_days_before ? t.evening_before : t.same_morning).toLowerCase()} ${t.at} ${r.pickup_time}`,
    r.new_invoice && t.new_invoice, r.invoice_due && t.invoice_due, r.session_expired && t.session_expired,
  ].filter(Boolean).join(" · ");

  return (
    <div className="card">
      <h2>{t.ha_notify}</h2>
      <div className="muted" style={{ margin: "4px 0 8px" }}>{t.ha_notify_info}</div>
      {err && <div className="neg">{err}</div>}
      {list?.length === 0 && <div className="muted">{t.no_recipients}</div>}
      {list?.map((r, i) => (
        <button key={r.service} className="row recipient" disabled={!admin} onClick={() => setEdit({ r, index: i })}>
          <span><b>{serviceName(hass, r.service)}</b><br /><span className="muted">{summary(r) || "–"}</span></span>
          <span className="muted">›</span>
        </button>
      ))}
      {admin ? list && (
        <button className="btn" disabled={!services.some((s) => !list.some((r) => r.service === s))}
          onClick={() => setEdit({ r: { service: services.find((s) => !list.some((r) => r.service === s))!, ...NEW }, index: -1 })}>
          + {t.add_recipient}
        </button>
      ) : <div className="muted">{t.admin_only}</div>}
      {edit && list && <RecipientModal t={t} hass={hass} init={edit.r} services={services.filter((s) => s === edit.r.service || !list.some((r) => r.service === s))}
        onClose={() => setEdit(null)}
        onSave={(r) => save(edit.index < 0 ? [...list, r] : list.map((x, i) => (i === edit.index ? r : x)))}
        onRemove={edit.index < 0 ? undefined : () => save(list.filter((_, i) => i !== edit.index))} />}
    </div>
  );
}

function RecipientModal({ t, hass, init, services, onClose, onSave, onRemove }:
  { t: T; hass: any; init: Recipient; services: string[]; onClose: () => void; onSave: (r: Recipient) => void; onRemove?: () => void }) {
  const [r, setR] = useState(init);
  const set = (p: Partial<Recipient>) => setR({ ...r, ...p });
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, []);
  return (
    <div className="modal-bg" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card" role="dialog" aria-modal="true" aria-label={t.recipient}>
        <h2>{t.recipient}</h2>
        <label className="row">
          <span>{t.recipient}</span>
          <select value={r.service} onChange={(e) => set({ service: e.target.value })}>
            {services.map((s) => <option key={s} value={s}>{serviceName(hass, s)}</option>)}
          </select>
        </label>
        <label className="row">
          <span>{t.pickup_reminder}</span>
          <input type="checkbox" className="toggle" checked={r.pickup} onChange={(e) => set({ pickup: e.target.checked })} />
        </label>
        {r.pickup && <div className="row sub">
          <div className="seg">
            {([1, 0] as const).map((d) => (
              <button key={d} className={r.pickup_days_before === d ? "on" : ""} onClick={() => set({ pickup_days_before: d })}>
                {d ? t.evening_before : t.same_morning}
              </button>
            ))}
          </div>
          <span>{t.at} <input type="time" value={r.pickup_time} onChange={(e) => e.target.value && set({ pickup_time: e.target.value })} /></span>
        </div>}
        <label className="row">
          <span>{t.new_invoice}</span>
          <input type="checkbox" className="toggle" checked={r.new_invoice} onChange={(e) => set({ new_invoice: e.target.checked })} />
        </label>
        <label className="row">
          <span>{t.invoice_due}</span>
          <input type="checkbox" className="toggle" checked={r.invoice_due} onChange={(e) => set({ invoice_due: e.target.checked })} />
        </label>
        <label className="row">
          <span>{t.session_expired}</span>
          <input type="checkbox" className="toggle" checked={r.session_expired} onChange={(e) => set({ session_expired: e.target.checked })} />
        </label>
        <div className="modal-actions">
          {onRemove && <button className="btn danger" onClick={onRemove}>{t.remove}</button>}
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={onClose}>{t.cancel}</button>
          <button className="btn primary" onClick={() => onSave(r)}>{t.save}</button>
        </div>
      </div>
    </div>
  );
}
