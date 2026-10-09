import { useState } from "react";
import House, { SceneBin, binColor } from "./House";
import { T, pick } from "./i18n";

// Everything comes from the integration's own entities (entity registry + states), so the panel needs no
// backend API of its own and shows exactly what automations see.
type Ent = { entity_id: string; device_id?: string; platform: string; translation_key?: string };
type St = { entity_id: string; state: string; attributes: Record<string, any> };
type Invoice = { id: number; amount: number | null; invoice_date: string | null; due_date: string | null; payment_status: string | null };
type Addr = {
  id: string; name: string; pickups: St[]; invoice?: St; fees: St[]; property?: St; calendar?: St; switches: St[]; times: St[];
};
type Ctx = { hass: any; t: T; locale: string };

const TABS = ["overview", "invoices", "settings"] as const;
type Tab = (typeof TABS)[number];
const PAID = new Set(["helt betald"]);  // same as const.PAID_STATUSES

const fmt = (v: number | null | undefined, d = 0, u = "") =>
  v == null || Number.isNaN(v) ? "–" : `${v.toLocaleString("sv-SE", { minimumFractionDigits: d, maximumFractionDigits: d })}${u ? " " + u : ""}`;
const day = (iso: string) => new Date(iso.slice(0, 10) + "T00:00:00");
const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
const daysUntil = (iso: string) => Math.round((day(iso).getTime() - today().getTime()) / 864e5);

export function addresses(hass: any): Addr[] {
  const by: Record<string, Addr> = {};
  for (const e of Object.values((hass.entities ?? {}) as Record<string, Ent>)) {
    const s: St | undefined = hass.states[e.entity_id];
    if (e.platform !== "vafabmiljo" || !s || !e.device_id) continue;
    const a = (by[e.device_id] ??= {
      id: e.device_id, name: hass.devices?.[e.device_id]?.name_by_user || hass.devices?.[e.device_id]?.name || "VafabMiljö",
      pickups: [], fees: [], switches: [], times: [],
    });
    const domain = e.entity_id.split(".")[0];
    if (domain === "sensor" && s.attributes.device_class === "date") a.pickups.push(s);
    else if (e.translation_key === "latest_invoice") a.invoice = s;
    else if (e.translation_key === "property") a.property = s;
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
  const date = day(iso).toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });
  const rel = n === 0 ? t.today : n === 1 ? t.tomorrow : t.in_days.replace("{n}", String(n));
  return n <= 1 ? { when: rel[0].toUpperCase() + rel.slice(1), sub: date, days: n } : { when: date, sub: rel, days: n };
}

export default function App({ hass, narrow }: { hass: any; narrow: boolean }) {
  const { t, locale } = pick(hass.locale?.language ?? hass.language);
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem("vm_tab") as Tab) || "overview");
  const [sel, setSel] = useState<string | null>(() => localStorage.getItem("vm_addr"));
  const list = addresses(hass);
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
          {tab === "settings" && <Settings {...ctx} a={a} />}
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
  const scene: SceneBin[] = bins.map((b) => ({ ...b, next: b.days === first }));
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
        <div className="card scene"><House bins={scene} truck={now.length > 0} /></div>
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
function Settings({ a, hass, t }: Ctx & { a: Addr }) {
  return (
    <div className="settings-grid">
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
