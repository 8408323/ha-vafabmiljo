const en = {
  title: "VafabMiljö",
  tab_overview: "Overview", tab_invoices: "Invoices", tab_settings: "Settings",
  loading: "Loading…",
  none: "No VafabMiljö address set up yet. Add the integration under Settings → Devices & services.",
  next: "Next pickup", today: "today", tomorrow: "tomorrow", in_days: "in {n} days",
  put_out: "Put out tonight", put_out_now: "Pickup today – bins out by 06:00", nothing_tonight: "Nothing to put out tonight",
  bins: "Bins", latest_invoice: "Latest invoice", annual_fee: "Fees", per_year: "pickups/year",
  invoices: "Invoices", date: "Date", due: "Due", amount: "Amount", status: "Status", pdf: "PDF", open: "Open",
  per_year_total: "Invoiced per year", no_invoices: "Connect BankID in the integration to see invoices and fees.",
  download_failed: "Could not fetch the PDF",
  overdue: "Overdue", unpaid: "Unpaid", paid: "Paid",
  notifications: "VafabMiljö app notifications", reminders: "Reminder times",
  property: "Property", calendar: "Calendar", calendar_info: "Add the pickup calendar to HA's calendar view or a calendar card.",
  updated: "Updated",
};
export type T = typeof en;

const sv: T = {
  title: "VafabMiljö",
  tab_overview: "Översikt", tab_invoices: "Fakturor", tab_settings: "Inställningar",
  loading: "Laddar…",
  none: "Ingen VafabMiljö-adress är uppsatt än. Lägg till integrationen under Inställningar → Enheter och tjänster.",
  next: "Nästa tömning", today: "idag", tomorrow: "imorgon", in_days: "om {n} dagar",
  put_out: "Ställ ut ikväll", put_out_now: "Tömning idag – kärlen ut senast 06:00", nothing_tonight: "Inget att ställa ut ikväll",
  bins: "Kärl", latest_invoice: "Senaste faktura", annual_fee: "Avgifter", per_year: "tömningar/år",
  invoices: "Fakturor", date: "Datum", due: "Förfaller", amount: "Belopp", status: "Status", pdf: "PDF", open: "Öppna",
  per_year_total: "Fakturerat per år", no_invoices: "Anslut BankID i integrationen för att se fakturor och avgifter.",
  download_failed: "Kunde inte hämta PDF:en",
  overdue: "Förfallen", unpaid: "Obetald", paid: "Betald",
  notifications: "Notiser i VafabMiljö-appen", reminders: "Påminnelsetider",
  property: "Fastighet", calendar: "Kalender", calendar_info: "Lägg till tömningskalendern i HA:s kalendervy eller ett kalenderkort.",
  updated: "Uppdaterad",
};

export function pick(lang: string | undefined): { t: T; locale: string } {
  return lang?.startsWith("sv") ? { t: sv, locale: "sv-SE" } : { t: en, locale: lang || "en" };
}
