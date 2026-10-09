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

  return (
    <div className={`page ${narrow ? "narrow" : ""}`}>
      <header>
        <div className="brand"><h1>{t.title}</h1>
          {list.length > 1 ? (
            <div className="seg">{list.map((x) => (
              <button key={x.id} className={x.id === a?.id ? "on" : ""} onClick={() => { setSel(x.id); localStorage.setItem("vm_addr", x.id); }}>{x.name}</button>
            ))}</div>
          ) : a && <span className="chip">{a.name}</span>}
        </div>
        <nav className="tabs">
          {TABS.map((x) => <button key={x} className={tab === x ? "on" : ""} onClick={() => go(x)}>{t[`tab_${x}`]}</button>)}
        </nav>
      </header>
      {!a ? <div className="card">{hass.entities ? t.none : t.loading}</div> : (
        <>
          {tab === "overview" && <Overview {...ctx} a={a} />}
          {tab === "invoices" && <Invoices {...ctx} a={a} />}
          {tab === "settings" && <Settings {...ctx} a={a} lang={lang} setLang={setLang} />}
        </>
      )}
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
            <div className="label">{t.next}</div>
            <div className="big">{next[0]?.when ?? "–"} <small>{next[0]?.sub}</small></div>
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
                <div className="muted"><Status inv={inv} t={t} /> · {inv.invoice_date ? day(inv.invoice_date).toLocaleDateString(locale) : ""}</div>
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

  return (
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
  );
}

/* ---------------- Settings ---------------- */
function Settings({ a, hass, t, lang, setLang }: Ctx & { a: Addr; lang: string | null; setLang: (x: string | null) => void }) {
  return (
    <div className="settings-grid">
      {/* keyed by entry: switching address starts fresh, so one address's list can't be saved to another */}
      <Account key={`acc-${a.entryId}`} a={a} hass={hass} t={t} />
      <Recipients key={`rec-${a.entryId}`} a={a} hass={hass} t={t} />
      <div className="card">
        <h2>{t.language}</h2>
        <label className="row">
          <span>{t.language}</span>
          <select value={lang ?? ""} onChange={(e) => setLang(e.target.value || null)}>
            <option value="">{t.lang_auto}</option>
            {Object.entries(LANGS).map(([code, [, , name]]) => <option key={code} value={code}>{name}</option>)}
          </select>
        </label>
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

/* ---------------- BankID login ---------------- */
type Login = { status: "waiting" | "done" | "failed" | "none"; qr?: string | null; autostart?: string | null };

function Account({ a, hass, t }: { a: Addr; hass: any; t: T }) {
  const [login, setLogin] = useState<Login | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const admin = hass.user?.is_admin !== false;
  // The "BankID connected" sensor exists once BankID was ever set up and is off while the backend rejects
  // the session; unavailable/unknown only means a refresh failed (e.g. the backend is down), not an expiry.
  const connected = a.bankid?.state === "on";
  const [cls, text] = !a.bankid ? ["", t.bankid_none] : connected ? ["pos", t.bankid_ok]
    : a.bankid.state === "off" ? ["warn", t.bankid_expired] : ["", t.bankid_unknown];

  const send = (type: string) => hass.connection.sendMessagePromise({ type, entry_id: a.entryId });
  useEffect(() => {
    if (login?.status !== "waiting") return;
    const id = setInterval(() => send("vafabmiljo/login/status").then(setLogin).catch(() => undefined), 2000);
    return () => clearInterval(id);
  }, [login?.status]);
  const start = async () => {
    setErr(null);
    try { setLogin(await send("vafabmiljo/login/start")); } catch (e: any) { setErr(e?.message ?? String(e)); }
  };
  const close = () => { if (login?.status === "waiting") send("vafabmiljo/login/cancel").catch(() => undefined); setLogin(null); };

  return (
    <div className="card">
      <h2>{t.account}</h2>
      <div className={`muted ${cls}`} style={{ margin: "6px 0" }}>{text}</div>
      {err && <div className="neg">{err}</div>}
      {admin ? <button className="btn primary" disabled={!a.entryId} onClick={start}>{connected ? t.relogin : t.login}</button>
        : <div className="muted">{t.admin_only}</div>}
      {login && (
        <div className="modal-bg" onPointerDown={(e) => e.target === e.currentTarget && close()}>
          <div className="modal card login" role="dialog" aria-modal="true" aria-label={t.login}>
            <h2>{t.login}</h2>
            {login.status === "waiting" && <>
              <div className="muted">{t.scan_qr}</div>
              {login.qr && <img className="qr" src={login.qr} alt="BankID QR" />}
              {login.autostart && <a className="btn" href={login.autostart}>{t.open_on_device}</a>}
            </>}
            {login.status === "done" && <div className="pos">✓ {t.login_done}</div>}
            {(login.status === "failed" || login.status === "none") && <div className="neg">{t.login_failed}</div>}
            <div className="modal-actions">
              <span style={{ flex: 1 }} />
              {login.status === "failed" && <button className="btn" onClick={start}>{t.relogin}</button>}
              <button className="btn" onClick={close}>{login.status === "done" ? "OK" : t.cancel}</button>
            </div>
          </div>
        </div>
      )}
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
