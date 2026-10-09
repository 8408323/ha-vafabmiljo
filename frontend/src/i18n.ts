// Default follows the Home Assistant user's language; overridable per browser in the panel's Settings tab.
const en = {
  title: "VafabMiljö",
  tab_overview: "Overview", tab_invoices: "Invoices", tab_settings: "Settings",
  loading: "Loading…",
  none: "No VafabMiljö address set up yet. Add the integration under Settings → Devices & services.",
  next: "Next pickup", today: "today", tomorrow: "tomorrow", in_days: "in {n} days",
  put_out: "Put out tonight", put_out_now: "Pickup today – bins out by 06:00", nothing_tonight: "Nothing to put out tonight",
  latest_invoice: "Latest invoice", annual_fee: "Fees", per_year: "pickups/year",
  invoices: "Invoices", date: "Date", due: "Due", amount: "Amount", status: "Status", pdf: "PDF", open: "Open",
  per_year_total: "Invoiced per year", no_invoices: "Connect BankID in the integration to see invoices and fees.",
  download_failed: "Could not fetch the PDF",
  overdue: "Overdue", unpaid: "Unpaid", paid: "Paid",
  notifications: "VafabMiljö app notifications", reminders: "Reminder times",
  property: "Property", calendar_info: "Add the pickup calendar to HA's calendar view or a calendar card.",
  language: "Language", lang_auto: "Same as Home Assistant",
  ha_notify: "Notifications from Home Assistant",
  ha_notify_info: "Choose who gets which messages and when: a phone with the HA app, or any other notify service.",
  no_recipients: "No recipients yet.", add_recipient: "Add recipient", recipient: "Recipient",
  pickup_reminder: "Pickup reminder", evening_before: "The evening before", same_morning: "The same morning", at: "at",
  new_invoice: "New invoice", invoice_due: "Invoice due tomorrow",
  save: "Save", cancel: "Cancel", remove: "Remove", admin_only: "Only administrators can change this.",
};
export type T = typeof en;

const sv: T = {
  title: "VafabMiljö",
  tab_overview: "Översikt", tab_invoices: "Fakturor", tab_settings: "Inställningar",
  loading: "Laddar…",
  none: "Ingen VafabMiljö-adress är uppsatt än. Lägg till integrationen under Inställningar → Enheter och tjänster.",
  next: "Nästa tömning", today: "idag", tomorrow: "imorgon", in_days: "om {n} dagar",
  put_out: "Ställ ut ikväll", put_out_now: "Tömning idag – kärlen ut senast 06:00", nothing_tonight: "Inget att ställa ut ikväll",
  latest_invoice: "Senaste faktura", annual_fee: "Avgifter", per_year: "tömningar/år",
  invoices: "Fakturor", date: "Datum", due: "Förfaller", amount: "Belopp", status: "Status", pdf: "PDF", open: "Öppna",
  per_year_total: "Fakturerat per år", no_invoices: "Anslut BankID i integrationen för att se fakturor och avgifter.",
  download_failed: "Kunde inte hämta PDF:en",
  overdue: "Förfallen", unpaid: "Obetald", paid: "Betald",
  notifications: "Notiser i VafabMiljö-appen", reminders: "Påminnelsetider",
  property: "Fastighet", calendar_info: "Lägg till tömningskalendern i HA:s kalendervy eller ett kalenderkort.",
  language: "Språk", lang_auto: "Samma som Home Assistant",
  ha_notify: "Notiser från Home Assistant",
  ha_notify_info: "Välj vem som får vilka meddelanden och när: en telefon med HA-appen eller någon annan notify-tjänst.",
  no_recipients: "Inga mottagare än.", add_recipient: "Lägg till mottagare", recipient: "Mottagare",
  pickup_reminder: "Påminnelse om tömning", evening_before: "Kvällen före", same_morning: "Samma morgon", at: "kl.",
  new_invoice: "Ny faktura", invoice_due: "Faktura förfaller imorgon",
  save: "Spara", cancel: "Avbryt", remove: "Ta bort", admin_only: "Bara administratörer kan ändra detta.",
};

const nb: T = {
  title: "VafabMiljö",
  tab_overview: "Oversikt", tab_invoices: "Fakturaer", tab_settings: "Innstillinger",
  loading: "Laster…",
  none: "Ingen VafabMiljö-adresse er satt opp ennå. Legg til integrasjonen under Innstillinger → Enheter og tjenester.",
  next: "Neste tømming", today: "i dag", tomorrow: "i morgen", in_days: "om {n} dager",
  put_out: "Sett ut i kveld", put_out_now: "Tømming i dag – dunkene ut innen kl. 06.00", nothing_tonight: "Ingenting å sette ut i kveld",
  latest_invoice: "Siste faktura", annual_fee: "Gebyrer", per_year: "tømminger/år",
  invoices: "Fakturaer", date: "Dato", due: "Forfaller", amount: "Beløp", status: "Status", pdf: "PDF", open: "Åpne",
  per_year_total: "Fakturert per år", no_invoices: "Koble til BankID i integrasjonen for å se fakturaer og gebyrer.",
  download_failed: "Kunne ikke hente PDF-en",
  overdue: "Forfalt", unpaid: "Ubetalt", paid: "Betalt",
  notifications: "Varsler i VafabMiljö-appen", reminders: "Påminnelsestider",
  property: "Eiendom", calendar_info: "Legg til tømmekalenderen i HAs kalendervisning eller et kalenderkort.",
  language: "Språk", lang_auto: "Samme som Home Assistant",
  ha_notify: "Varsler fra Home Assistant",
  ha_notify_info: "Velg hvem som får hvilke meldinger og når: en telefon med HA-appen eller en annen notify-tjeneste.",
  no_recipients: "Ingen mottakere ennå.", add_recipient: "Legg til mottaker", recipient: "Mottaker",
  pickup_reminder: "Påminnelse om tømming", evening_before: "Kvelden før", same_morning: "Samme morgen", at: "kl.",
  new_invoice: "Ny faktura", invoice_due: "Faktura forfaller i morgen",
  save: "Lagre", cancel: "Avbryt", remove: "Fjern", admin_only: "Bare administratorer kan endre dette.",
};

const da: T = {
  title: "VafabMiljö",
  tab_overview: "Oversigt", tab_invoices: "Fakturaer", tab_settings: "Indstillinger",
  loading: "Indlæser…",
  none: "Ingen VafabMiljö-adresse er sat op endnu. Tilføj integrationen under Indstillinger → Enheder og tjenester.",
  next: "Næste tømning", today: "i dag", tomorrow: "i morgen", in_days: "om {n} dage",
  put_out: "Stil ud i aften", put_out_now: "Tømning i dag – spandene ud senest kl. 06.00", nothing_tonight: "Intet at stille ud i aften",
  latest_invoice: "Seneste faktura", annual_fee: "Gebyrer", per_year: "tømninger/år",
  invoices: "Fakturaer", date: "Dato", due: "Forfalder", amount: "Beløb", status: "Status", pdf: "PDF", open: "Åbn",
  per_year_total: "Faktureret pr. år", no_invoices: "Tilslut BankID i integrationen for at se fakturaer og gebyrer.",
  download_failed: "Kunne ikke hente PDF'en",
  overdue: "Forfalden", unpaid: "Ubetalt", paid: "Betalt",
  notifications: "Notifikationer i VafabMiljö-appen", reminders: "Påmindelsestider",
  property: "Ejendom", calendar_info: "Tilføj tømningskalenderen til HA's kalendervisning eller et kalenderkort.",
  language: "Sprog", lang_auto: "Samme som Home Assistant",
  ha_notify: "Notifikationer fra Home Assistant",
  ha_notify_info: "Vælg hvem der får hvilke beskeder og hvornår: en telefon med HA-appen eller en anden notify-tjeneste.",
  no_recipients: "Ingen modtagere endnu.", add_recipient: "Tilføj modtager", recipient: "Modtager",
  pickup_reminder: "Påmindelse om tømning", evening_before: "Aftenen før", same_morning: "Samme morgen", at: "kl.",
  new_invoice: "Ny faktura", invoice_due: "Faktura forfalder i morgen",
  save: "Gem", cancel: "Annuller", remove: "Fjern", admin_only: "Kun administratorer kan ændre dette.",
};

const fi: T = {
  title: "VafabMiljö",
  tab_overview: "Yleiskatsaus", tab_invoices: "Laskut", tab_settings: "Asetukset",
  loading: "Ladataan…",
  none: "VafabMiljö-osoitetta ei ole vielä määritetty. Lisää integraatio kohdassa Asetukset → Laitteet ja palvelut.",
  next: "Seuraava tyhjennys", today: "tänään", tomorrow: "huomenna", in_days: "{n} päivän päästä",
  put_out: "Vie astiat ulos tänä iltana", put_out_now: "Tyhjennys tänään – astiat ulos klo 6.00 mennessä", nothing_tonight: "Tänä iltana ei vietävää",
  latest_invoice: "Viimeisin lasku", annual_fee: "Maksut", per_year: "tyhjennystä/vuosi",
  invoices: "Laskut", date: "Päivämäärä", due: "Eräpäivä", amount: "Summa", status: "Tila", pdf: "PDF", open: "Avaa",
  per_year_total: "Laskutettu vuosittain", no_invoices: "Yhdistä BankID integraatiossa nähdäksesi laskut ja maksut.",
  download_failed: "PDF:n haku epäonnistui",
  overdue: "Erääntynyt", unpaid: "Maksamatta", paid: "Maksettu",
  notifications: "VafabMiljö-sovelluksen ilmoitukset", reminders: "Muistutusajat",
  property: "Kiinteistö", calendar_info: "Lisää tyhjennyskalenteri HA:n kalenterinäkymään tai kalenterikorttiin.",
  language: "Kieli", lang_auto: "Sama kuin Home Assistantissa",
  ha_notify: "Ilmoitukset Home Assistantista",
  ha_notify_info: "Valitse, kuka saa mitkäkin viestit ja milloin: puhelin, jossa on HA-sovellus, tai jokin muu notify-palvelu.",
  no_recipients: "Ei vielä vastaanottajia.", add_recipient: "Lisää vastaanottaja", recipient: "Vastaanottaja",
  pickup_reminder: "Tyhjennysmuistutus", evening_before: "Edellisenä iltana", same_morning: "Samana aamuna", at: "klo",
  new_invoice: "Uusi lasku", invoice_due: "Lasku erääntyy huomenna",
  save: "Tallenna", cancel: "Peruuta", remove: "Poista", admin_only: "Vain ylläpitäjät voivat muuttaa tätä.",
};

const is_: T = {
  title: "VafabMiljö",
  tab_overview: "Yfirlit", tab_invoices: "Reikningar", tab_settings: "Stillingar",
  loading: "Hleð…",
  none: "Ekkert VafabMiljö-heimilisfang hefur verið sett upp. Bættu samþættingunni við undir Stillingar → Tæki og þjónustur.",
  next: "Næsta losun", today: "í dag", tomorrow: "á morgun", in_days: "eftir {n} daga",
  put_out: "Settu út í kvöld", put_out_now: "Losun í dag – tunnurnar út fyrir kl. 6:00", nothing_tonight: "Ekkert að setja út í kvöld",
  latest_invoice: "Nýjasti reikningur", annual_fee: "Gjöld", per_year: "losanir/ár",
  invoices: "Reikningar", date: "Dagsetning", due: "Gjalddagi", amount: "Upphæð", status: "Staða", pdf: "PDF", open: "Opna",
  per_year_total: "Reikningsfært á ári", no_invoices: "Tengdu BankID í samþættingunni til að sjá reikninga og gjöld.",
  download_failed: "Ekki tókst að sækja PDF-skjalið",
  overdue: "Fallinn í gjalddaga", unpaid: "Ógreiddur", paid: "Greiddur",
  notifications: "Tilkynningar í VafabMiljö-appinu", reminders: "Áminningartímar",
  property: "Fasteign", calendar_info: "Bættu losunardagatalinu við dagatalsyfirlit HA eða dagatalsspjald.",
  language: "Tungumál", lang_auto: "Sama og Home Assistant",
  ha_notify: "Tilkynningar frá Home Assistant",
  ha_notify_info: "Veldu hver fær hvaða skilaboð og hvenær: sími með HA-appinu eða önnur notify-þjónusta.",
  no_recipients: "Engir viðtakendur enn.", add_recipient: "Bæta við viðtakanda", recipient: "Viðtakandi",
  pickup_reminder: "Áminning um losun", evening_before: "Kvöldið áður", same_morning: "Sama morgun", at: "kl.",
  new_invoice: "Nýr reikningur", invoice_due: "Reikningur á gjalddaga á morgun",
  save: "Vista", cancel: "Hætta við", remove: "Fjarlægja", admin_only: "Aðeins stjórnendur geta breytt þessu.",
};

// code -> [strings, date locale, name in its own language]
export const LANGS: Record<string, [T, string, string]> = {
  sv: [sv, "sv-SE", "Svenska"], nb: [nb, "nb-NO", "Norsk"], da: [da, "da-DK", "Dansk"],
  fi: [fi, "fi-FI", "Suomi"], is: [is_, "is-IS", "Íslenska"], en: [en, "en-GB", "English"],
};

export function pick(haLang: string | undefined, override?: string | null): { t: T; locale: string } {
  // HA uses "nb" and "nn" for Norwegian; Nynorsk falls back to Bokmål
  const code = override || (haLang ?? "en").split("-")[0].replace("nn", "nb").replace(/^no$/, "nb");
  const [t, locale] = LANGS[code] ?? LANGS.en;
  return { t, locale };
}
