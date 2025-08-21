import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import tempfile
import plotly.express as px
import hashlib
from datetime import datetime
import os
import re

# ========= Instellingen =========
LOGIN_ACTIEF = False  # Zet True om login te activeren
plt.rcParams["figure.dpi"] = 150
st.set_page_config(page_title="Schadegevallen Dashboard", layout="wide")

# ========= Helpers =========
def hash_wachtwoord(wachtwoord: str) -> str:
    return hashlib.sha256(str(wachtwoord).encode()).hexdigest()

@st.cache_data(show_spinner=False)
def load_excel(path, **kwargs):
    """Veilig Excel-bestand inladen met caching."""
    try:
        return pd.read_excel(path, **kwargs)
    except FileNotFoundError:
        st.error(f"Bestand niet gevonden: {path}")
        st.stop()
    except Exception as e:
        st.error(f"Kon '{path}' niet lezen: {e}")
        st.stop()

def naam_naar_dn(naam: str) -> str | None:
    """Haal dienstnummer uit 'volledige naam' zoals '1234 - Voornaam Achternaam'."""
    if pd.isna(naam):
        return None
    s = str(naam).strip()
    m = re.match(r"\s*(\d+)", s)
    return m.group(1) if m else None

def toon_chauffeur(x):
    """Geef nette chauffeur-naam terug, met fallback. Knipt vooraan '1234 - ' weg."""
    if x is None or pd.isna(x):
        return "onbekend"
    s = str(x).strip()
    if not s or s.lower() in {"nan", "none", "<na>"}:
        return "onbekend"
    # strip '1234 - ' of '1234-'
    s = re.sub(r"^\s*\d+\s*-\s*", "", s)
    return s

def safe_name(x) -> str:
    """Netjes tonen; vermijd 'nan'/'none'/lege strings."""
    s = "" if x is pd.NA else str(x or "").strip()
    return "onbekend" if s.lower() in {"nan", "none", ""} else s

def _parse_excel_dates(series: pd.Series) -> pd.Series:
    """Robuuste datumparser: probeer EU (dayfirst) en val terug op US (monthfirst)."""
    d1 = pd.to_datetime(series, errors="coerce", dayfirst=True)
    need_retry = d1.isna()
    if need_retry.any():
        d2 = pd.to_datetime(series[need_retry], errors="coerce", dayfirst=False)
        d1.loc[need_retry] = d2
    return d1

# Kleine helper om hyperlinks uit Excel-formules te halen
HYPERLINK_RE = re.compile(r'HYPERLINK\(\s*"([^"]+)"', re.IGNORECASE)
def extract_url(x) -> str | None:
    if pd.isna(x):
        return None
    s = str(x).strip()
    if s.startswith(("http://", "https://")):
        return s
    m = HYPERLINK_RE.search(s)
    return m.group(1) if m else None

# ========= Kleuren =========
COLOR_GEEL  = "#FFD54F"  # voltooide coaching
COLOR_BLAUW = "#2196F3"  # in coaching
COLOR_MIX   = "#7E57C2"  # beide
COLOR_GRIJS = "#BDBDBD"  # geen

def status_van_chauffeur(naam: str) -> str:
    dn = naam_naar_dn(naam)
    if not dn:
        return "Geen"
    sdn = str(dn)
    in_geel = sdn in gecoachte_ids
    in_blauw = sdn in coaching_ids
    if in_geel and in_blauw:
        return "Beide"
    if in_geel:
        return "Voltooid"
    if in_blauw:
        return "Coaching"
    return "Geen"

def badge_van_status(status: str) -> str:
    return {"Voltooid": "🟡 ", "Coaching": "🔵 ", "Beide": "🟡🔵 ", "Geen": ""}.get(status, "")

# ========= Coachingslijst inlezen (Voltooid/Coaching) =========
@st.cache_data(show_spinner=False)
def lees_coachingslijst(pad="Coachingslijst.xlsx"):
    ids_geel, ids_blauw = set(), set()
    try:
        xls = pd.ExcelFile(pad)
    except Exception as e:
        return ids_geel, ids_blauw, f"Coachingslijst niet gevonden of onleesbaar: {e}"

    def vind_sheet(xls, naam):
        return next((s for s in xls.sheet_names if s.strip().lower() == naam), None)

    def haal_ids(sheetnaam):
        dfc = pd.read_excel(xls, sheet_name=sheetnaam)
        dfc.columns = dfc.columns.str.strip().str.lower()
        kol = None
        for k in ["p-nr", "p_nr", "pnr", "pnummer", "dienstnummer", "p nr"]:
            if k in dfc.columns:
                kol = k; break
        if kol is None:
            return set()
        return set(
            dfc[kol].astype(str).str.extract(r"(\d+)", expand=False)
            .dropna().str.strip().tolist()
        )

    s_geel = vind_sheet(xls, "voltooide coachings")
    s_blauw = vind_sheet(xls, "coaching")
    if s_geel:
        ids_geel = haal_ids(s_geel)
    if s_blauw:
        ids_blauw = haal_ids(s_blauw)

    return ids_geel, ids_blauw, None

# ========= Gebruikersbestand (login) =========
gebruikers_df = load_excel("chauffeurs.xlsx")
gebruikers_df.columns = gebruikers_df.columns.str.strip().str.lower()

# normaliseer kolommen (login/wachtwoord varianten)
kol_map = {}
if "gebruikersnaam" in gebruikers_df.columns:
    kol_map["gebruikersnaam"] = "gebruikersnaam"
elif "login" in gebruikers_df.columns:
    kol_map["login"] = "gebruikersnaam"

if "paswoord" in gebruikers_df.columns:
    kol_map["paswoord"] = "paswoord"
elif "wachtwoord" in gebruikers_df.columns:
    kol_map["wachtwoord"] = "paswoord"

for c in ["rol", "dienstnummer", "laatste login"]:
    if c in gebruikers_df.columns:
        kol_map[c] = c

gebruikers_df = gebruikers_df.rename(columns=kol_map)

# Vereisten check
vereist_login_kolommen = {"gebruikersnaam", "paswoord"}
missend_login = [c for c in vereist_login_kolommen if c not in gebruikers_df.columns]
if missend_login:
    st.error(f"Login configuratie onvolledig. Ontbrekende kolommen (na normalisatie): {', '.join(missend_login)}")
    st.stop()

# Strings netjes
gebruikers_df["gebruikersnaam"] = gebruikers_df["gebruikersnaam"].astype(str).str.strip()
gebruikers_df["paswoord"] = gebruikers_df["paswoord"].astype(str).str.strip()
for c in ["rol", "dienstnummer", "laatste login"]:
    if c not in gebruikers_df.columns:
        gebruikers_df[c] = pd.NA

# Session login status
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if LOGIN_ACTIEF and not st.session_state.logged_in:
    st.title("🔐 Inloggen")
    username = st.text_input("Gebruikersnaam")
    password = st.text_input("Wachtwoord", type="password")
    if st.button("Log in"):
        rij = gebruikers_df.loc[gebruikers_df["gebruikersnaam"] == str(username).strip()]
        if not rij.empty:
            opgeslagen = str(rij["paswoord"].iloc[0])
            ok = (opgeslagen == str(password)) or (opgeslagen == hash_wachtwoord(password))
            if ok:
                st.session_state.logged_in = True
                st.session_state.username = str(username).strip()
                st.success("✅ Ingelogd!")
                if "laatste login" in gebruikers_df.columns:
                    try:
                        gebruikers_df.loc[rij.index, "laatste login"] = datetime.now()
                        gebruikers_df.to_excel("chauffeurs.xlsx", index=False)
                    except Exception as e:
                        st.warning(f"Kon 'laatste login' niet opslaan: {e}")
                st.rerun()
            else:
                st.error("❌ Onjuiste gebruikersnaam of wachtwoord.")
        else:
            st.error("❌ Onjuiste gebruikersnaam of wachtwoord.")
    st.stop()
else:
    if not LOGIN_ACTIEF:
        st.session_state.logged_in = True
        st.session_state.username = "demo"

# Rol + naam
if not LOGIN_ACTIEF:
    rol = "teamcoach"; naam = "demo"
else:
    ingelogde_info = gebruikers_df.loc[gebruikers_df["gebruikersnaam"] == st.session_state.username].iloc[0]
    rol = str(ingelogde_info.get("rol", "teamcoach")).strip()
    if rol == "chauffeur":
        naam = str(ingelogde_info.get("dienstnummer", ingelogde_info["gebruikersnaam"]))
    else:
        naam = str(ingelogde_info["gebruikersnaam"]).strip()

# ========= Data laden =========
raw = load_excel("schade met macro.xlsm", sheet_name="BRON").copy()
raw.columns = raw.columns.str.strip()

# -- parse datums robuust
raw["Datum"] = _parse_excel_dates(raw["Datum"])

# -- normaliseer relevante kolommen (als string; nog NIET filteren op leeg)
for col in ["volledige naam", "teamcoach", "Locatie", "Bus/ Tram", "Link"]:
    if col in raw.columns:
        raw[col] = raw[col].astype("string").str.strip()

# --- df_for_options: ALLE rijen met geldige datum (voor kwartaal-lijst)
df_for_options = raw[raw["Datum"].notna()].copy()
df_for_options["KwartaalP"] = df_for_options["Datum"].dt.to_period("Q")

# --- df: analyses (alleen datums moeten geldig zijn; lege velden worden 'onbekend')
df = raw[raw["Datum"].notna()].copy()

# Display-kolommen met 'onbekend'
df["volledige naam_disp"] = df["volledige naam"].apply(safe_name)
df["teamcoach_disp"]      = df["teamcoach"].apply(safe_name)
df["Locatie_disp"]        = df["Locatie"].apply(safe_name)
df["BusTram_disp"]        = df["Bus/ Tram"].apply(safe_name)

# Overige afgeleiden
dn = df["volledige naam"].astype(str).str.extract(r"^(\d+)", expand=False)
df["dienstnummer"] = dn.astype("string").str.strip()
df["KwartaalP"]    = df["Datum"].dt.to_period("Q")
df["Kwartaal"]     = df["KwartaalP"].astype(str)

# ========= Coachingslijst =========
gecoachte_ids, coaching_ids, coach_warn = lees_coachingslijst()
if coach_warn:
    st.sidebar.warning(f"⚠️ {coach_warn}")

# Flags op df (optioneel)
df["gecoacht_geel"]  = df["dienstnummer"].astype(str).isin(gecoachte_ids)
df["gecoacht_blauw"] = df["dienstnummer"].astype(str).isin(coaching_ids)

# ========= UI: Titel + Caption =========
st.title("📊 Schadegevallen Dashboard")
st.caption("🟡 = voltooide coaching · 🔵 = in coaching (lopend)")

# ========= Query params presets =========
qp = st.query_params  # Streamlit 1.32+

def _clean_list(values, allowed):
    return [v for v in (values or []) if v in allowed]

# Opties (komen uit display-kolommen zodat 'onbekend' selecteerbaar is)
teamcoach_options = sorted(df["teamcoach_disp"].dropna().unique().tolist())
locatie_options   = sorted(df["Locatie_disp"].dropna().unique().tolist())
voertuig_options  = sorted(df["BusTram_disp"].dropna().unique().tolist())
kwartaal_options  = sorted(df_for_options["KwartaalP"].dropna().astype(str).unique().tolist())

# Prefs uit URL
pref_tc = _clean_list(qp.get_all("teamcoach"), teamcoach_options) or teamcoach_options
pref_lo = _clean_list(qp.get_all("locatie"),  locatie_options)  or locatie_options
pref_vh = _clean_list(qp.get_all("voertuig"),  voertuig_options) or voertuig_options
pref_kw = _clean_list(qp.get_all("kwartaal"),  kwartaal_options)  or kwartaal_options

# ========= Sidebar filters =========
with st.sidebar:
    st.header("🔍 Filters")
    selected_teamcoaches = st.multiselect("Teamcoach", options=teamcoach_options, default=pref_tc)
    selected_locaties    = st.multiselect("Locatie", options=locatie_options, default=pref_lo)
    selected_voertuigen  = st.multiselect("Voertuigtype", options=voertuig_options, default=pref_vh)
    selected_kwartalen   = st.multiselect("Kwartaal", options=kwartaal_options, default=pref_kw)

    # Datum-bereik = gekozen kwartalen, anders volledige range
    st.markdown("### 🗓️ Datum")
    if selected_kwartalen:
        sel_periods_idx = pd.PeriodIndex(selected_kwartalen, freq="Q")
        date_from = sel_periods_idx.start_time.min().date()
        date_to   = sel_periods_idx.end_time.max().date()
    else:
        date_from = df["Datum"].min().date()
        date_to   = df["Datum"].max().date()

    # Reset-knop
    if st.button("🔄 Reset filters"):
        qp.clear()
        st.rerun()

# ========= Filters toepassen =========
sel_periods = pd.PeriodIndex(selected_kwartalen, freq="Q") if selected_kwartalen else pd.PeriodIndex([], freq="Q")

mask = (
    df["teamcoach_disp"].isin(selected_teamcoaches) &
    df["Locatie_disp"].isin(selected_locaties) &
    df["BusTram_disp"].isin(selected_voertuigen) &
    (df["KwartaalP"].isin(sel_periods) if len(sel_periods) > 0 else True)
)
df_filtered = df[mask].copy()

mask_date = (df_filtered["Datum"].dt.date >= date_from) & (df_filtered["Datum"].dt.date <= date_to)
df_filtered = df_filtered[mask_date].copy()

if df_filtered.empty:
    st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    st.stop()

# ========= KPI + export =========
st.metric("Totaal aantal schadegevallen", len(df_filtered))
st.download_button(
    "⬇️ Download gefilterde data (CSV)",
    df_filtered.to_csv(index=False).encode("utf-8"),
    file_name=f"schade_filtered_{datetime.today().strftime('%Y%m%d')}.csv",
    mime="text/csv",
    help="Exporteer de huidige selectie inclusief datumfilter."
)

# ========= Coaching-status in sidebar =========
with st.sidebar:
    st.markdown("### ℹ️ Coaching-status")
    st.write(f"🟡 Voltooide coachings: **{len(gecoachte_ids)}**")
    st.write(f"🔵 Coaching (lopend): **{len(coaching_ids)}**")

# ========= Tabs =========
tab1, tab2, tab3, tab4 = st.tabs(["👤 Chauffeur", "🧑‍💼 Teamcoach", "🚌 Voertuig", "📍 Locatie"])

# ========= PDF Export (per teamcoach) =========
st.markdown("---")
st.sidebar.subheader("📄 PDF Export per teamcoach")
pdf_coach = st.sidebar.selectbox("Kies teamcoach voor export", teamcoach_options)
generate_pdf = st.sidebar.button("Genereer PDF")

if generate_pdf:
    kolommen_pdf = ["Datum", "volledige naam_disp", "Locatie_disp", "BusTram_disp"]
    if "Link" in df.columns:
        kolommen_pdf.append("Link")

    schade_pdf = df_filtered[df_filtered["teamcoach_disp"] == pdf_coach][kolommen_pdf].copy()
    schade_pdf = schade_pdf.sort_values(by="Datum")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f"Overzicht schadegevallen - Teamcoach: <b>{pdf_coach}</b>", styles["Title"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"📅 Rapportdatum: {datetime.today().strftime('%d-%m-%Y')}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    totaal = len(schade_pdf)
    elements.append(Paragraph(f"📌 Totaal aantal schadegevallen: <b>{totaal}</b>", styles["Normal"]))
    elements.append(Spacer(1, 12))

    if not schade_pdf.empty:
        eerste_datum = schade_pdf["Datum"].min().strftime("%d-%m-%Y")
        laatste_datum = schade_pdf["Datum"].max().strftime("%d-%m-%Y")
        elements.append(Paragraph("📊 Samenvatting:", styles["Heading2"]))
        elements.append(Paragraph(f"- Periode: {eerste_datum} t/m {laatste_datum}", styles["Normal"]))
        elements.append(Paragraph(f"- Unieke chauffeurs: {schade_pdf['volledige naam_disp'].nunique()}", styles["Normal"]))
        elements.append(Paragraph(f"- Unieke locaties: {schade_pdf['Locatie_disp'].nunique()}", styles["Normal"]))
        elements.append(Spacer(1, 12))

    aantal_per_chauffeur = schade_pdf["volledige naam_disp"].value_counts()
    elements.append(Paragraph("👤 Aantal schadegevallen per chauffeur:", styles["Heading2"]))
    for nm, count in aantal_per_chauffeur.items():
        elements.append(Paragraph(f"- {safe_name(nm)}: {count}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    aantal_per_locatie = schade_pdf["Locatie_disp"].value_counts()
    elements.append(Paragraph("📍 Aantal schadegevallen per locatie:", styles["Heading2"]))
    for loc, count in aantal_per_locatie.items():
        elements.append(Paragraph(f"- {safe_name(loc)}: {count}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    chart_path = None
    if not schade_pdf.empty:
        schade_pdf["Maand"] = schade_pdf["Datum"].dt.to_period("M").astype(str)
        maand_data = schade_pdf["Maand"].value_counts().sort_index()
        fig, ax = plt.subplots()
        maand_data.plot(kind="bar", ax=ax)
        ax.set_title("Schadegevallen per maand")
        ax.set_ylabel("Aantal")
        plt.xticks(rotation=45)
        plt.tight_layout()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
            fig.savefig(tmpfile.name, dpi=150)
            plt.close(fig)
            chart_path = tmpfile.name
            elements.append(Paragraph("📊 Schadegevallen per maand:", styles["Heading2"]))
            elements.append(Paragraph("Deze grafiek toont het aantal gemelde schadegevallen per maand voor deze teamcoach.", styles["Italic"]))
            elements.append(Spacer(1, 6))
            elements.append(Image(tmpfile.name, width=400, height=200))
            elements.append(Spacer(1, 12))

    # Compacte tabel met individuele schadegevallen
    elements.append(Paragraph("📂 Individuele schadegevallen:", styles["Heading2"]))
    elements.append(Spacer(1, 6))

    kol_head = ["Datum", "Chauffeur", "Voertuig", "Locatie"]
    heeft_link = "Link" in schade_pdf.columns
    if heeft_link:
        kol_head.append("Link")

    tabel_data = [kol_head]
    for _, row in schade_pdf.iterrows():
        datum = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
        nm = row["volledige naam_disp"]; voertuig = row["BusTram_disp"]; locatie = row["Locatie_disp"]
        rij = [datum, nm, voertuig, locatie]
        if heeft_link:
            link = extract_url(row.get("Link"))
            rij.append(link if link else "-")
        tabel_data.append(rij)

    if len(tabel_data) > 1:
        colw = [60, 150, 70, 130] + ([120] if heeft_link else [])
        tbl = Table(tabel_data, repeatRows=1, colWidths=colw)
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("ALIGN", (0,0), (-1,0), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.whitesmoke, colors.white]),
        ]))
        elements.append(tbl)

    doc.build(elements)
    buffer.seek(0)
    bestandsnaam = f"schade_{pdf_coach.replace(' ', '_')}_{datetime.today().strftime('%Y%m%d')}.pdf"
    st.sidebar.download_button(label="📥 Download PDF", data=buffer, file_name=bestandsnaam, mime="application/pdf")

    if chart_path and os.path.exists(chart_path):
        try:
            os.remove(chart_path)
        except Exception:
            pass

# ========= TAB 1: Chauffeur =========
with tab1:
    st.subheader("📂 Schadegevallen per chauffeur")

    chart_series = df_filtered["volledige naam_disp"].value_counts()

    if chart_series.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        # Dataframe voor badges en status
        plot_df = chart_series.rename_axis("chauffeur").reset_index(name="aantal")
        plot_df["status"] = plot_df["chauffeur"].apply(status_van_chauffeur)
        plot_df["badge"]  = plot_df["status"].apply(badge_van_status)

        # ========== KPI blok ==========
        totaal_chauffeurs_auto = int(plot_df["chauffeur"].nunique())
        totaal_schades = int(plot_df["aantal"].sum())

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Aantal chauffeurs (automatisch)", totaal_chauffeurs_auto)
            handmatig_aantal = st.number_input(
                "Handmatig aantal chauffeurs",
                min_value=1,
                value=max(1, totaal_chauffeurs_auto),
                step=1,
                help="Vul hier het aantal chauffeurs in om het gemiddelde te herberekenen."
            )

        gem_handmatig = round(totaal_schades / handmatig_aantal, 2) if handmatig_aantal else 0.0
        col2.metric("Gemiddeld aantal schades", gem_handmatig)
        col3.metric("Totaal aantal schades", totaal_schades)

        if handmatig_aantal != totaal_chauffeurs_auto:
            st.caption(f"ℹ️ Handmatige invoer actief: {handmatig_aantal} i.p.v. {totaal_chauffeurs_auto}.")

        # ========== Accordeons per interval ==========
        st.subheader("📊 Chauffeurs gegroepeerd per interval")

        # Robuuste bin-randen (stap 5)
        step = 5
        max_val = int(plot_df["aantal"].max()) if not plot_df.empty else 0
        if max_val <= 0:
            edges = [0, step]
        else:
            edges = list(range(0, max_val + step, step))
            if edges[-1] < max_val:
                edges.append(edges[-1] + step)

        plot_df["interval"] = pd.cut(
            plot_df["aantal"],
            bins=edges,
            right=True,
            include_lowest=True
        )

        for interval, groep in plot_df.groupby("interval", sort=False):
            if groep.empty or pd.isna(interval):
                continue
            # Label netjes (1..right) i.p.v. 0..right
            left, right = int(interval.left), int(interval.right)
            low = max(1, left + 1)
            titel = f"{low} t/m {right} schades ({len(groep)} chauffeurs)"

            with st.expander(titel):
                for _, rec in groep.sort_values("aantal", ascending=False).iterrows():
                    chauffeur_label = rec["chauffeur"]
                    aantal = int(rec["aantal"])
                    status = rec["status"]
                    badge  = rec["badge"]
                    subtitel = f"{badge}{chauffeur_label} — {aantal} schadegevallen"
                    with st.expander(subtitel):
                        cols = ["Datum", "BusTram_disp", "Locatie_disp", "teamcoach_disp", "Link"] \
                               if "Link" in df_filtered.columns else \
                               ["Datum", "BusTram_disp", "Locatie_disp", "teamcoach_disp"]
                        schade_chauffeur = (
                            df_filtered.loc[df_filtered["volledige naam_disp"] == chauffeur_label, cols]
                            .sort_values(by="Datum")
                        )
                        for _, row in schade_chauffeur.iterrows():
                            datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                            voertuig  = row["BusTram_disp"]
                            loc       = row["Locatie_disp"]
                            coach     = row["teamcoach_disp"]
                            link      = extract_url(row.get("Link")) if "Link" in cols else None
                            prefix = f"📅 {datum_str} — 🚌 {voertuig} — 📍 {loc} — 🧑‍💼 {coach} — "
                            if isinstance(link, str) and link:
                                st.markdown(prefix + f"[🔗 Link]({link})", unsafe_allow_html=True)
                            else:
                                st.markdown(prefix + "❌ Geen geldige link")


# ========= TAB 2: Teamcoach =========
with tab2:
    st.subheader("Aantal schadegevallen per teamcoach")

    # Tel per teamcoach (we werken op de display-kolom zodat 'onbekend' ook mee telt)
    chart_data = df_filtered["teamcoach_disp"].value_counts()

    if chart_data.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        # Staafdiagram horizontaal; dynamische hoogte bij veel coaches
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
        chart_data.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen")
        ax.set_ylabel("Teamcoach")
        ax.set_title("Schadegevallen per teamcoach")
        st.pyplot(fig)

        st.subheader("📂 Schadegevallen per teamcoach")

        # Doorloop elke teamcoach in volgorde van aflopend aantal
        for coach in chart_data.sort_values(ascending=False).index.tolist():
            # Veilig kolommen kiezen (Link is optioneel)
            basis_kol = ["Datum", "volledige naam", "volledige naam_disp", "BusTram_disp", "Locatie_disp", "teamcoach_disp"]
            aanwezige_kol = [k for k in basis_kol if k in df_filtered.columns]
            if "Link" in df_filtered.columns:
                aanwezige_kol.append("Link")

            # Filter & sorteer
            schade_per_coach = (
                df_filtered.loc[df_filtered["teamcoach_disp"] == coach, aanwezige_kol]
                .sort_values(by="Datum")
            )
            aantal = len(schade_per_coach)

            with st.expander(f"{coach} — {aantal} schadegevallen"):
                if schade_per_coach.empty:
                    st.caption("Geen rijen binnen de huidige filters.")
                else:
                    # Toon elke rij compact met veilige fallback
                    for _, row in schade_per_coach.iterrows():
                        datum_obj = row.get("Datum")
                        datum_str = datum_obj.strftime("%d-%m-%Y") if pd.notna(datum_obj) else "onbekend"

                        # Chauffeurnaam: prefer 'volledige naam' -> toon_chauffeur, anders 'volledige naam_disp'
                        if "volledige naam" in schade_per_coach.columns and pd.notna(row.get("volledige naam")):
                            chauffeur = toon_chauffeur(row.get("volledige naam"))
                        else:
                            chauffeur = row.get("volledige naam_disp", "onbekend")

                        voertuig = row.get("BusTram_disp", "onbekend")
                        locatie  = row.get("Locatie_disp", "onbekend")

                        # Link (optioneel + formules uit Excel)
                        link = None
                        if "Link" in schade_per_coach.columns:
                            link = extract_url(row.get("Link"))

                        prefix = f"📅 {datum_str} — 👤 {chauffeur} — 🚌 {voertuig} — 📍 {locatie} — "
                        if isinstance(link, str) and link:
                            st.markdown(prefix + f"[🔗 Link]({link})", unsafe_allow_html=True)
                        else:
                            st.markdown(prefix + "❌ Geen geldige of aanwezige link")

# ========= TAB 3: Voertuig =========
with tab3:
    st.subheader("📈 Schadegevallen per maand per voertuigtype")
    df_per_maand = df_filtered.copy()
    maanden_nl = {1:"januari",2:"februari",3:"maart",4:"april",5:"mei",6:"juni",7:"juli",8:"augustus",9:"september",10:"oktober",11:"november",12:"december"}
    df_per_maand["Maand"] = df_per_maand["Datum"].dt.month.map(maanden_nl).str.lower()
    maand_volgorde = ["januari","februari","maart","april","mei","juni","juli","augustus","september","oktober","november","december"]
    groep = df_per_maand.groupby(["Maand", "BusTram_disp"]).size().unstack(fill_value=0)
    groep = groep.reindex(maand_volgorde)

    fig2, ax2 = plt.subplots(figsize=(10, 4))
    groep.plot(ax=ax2, marker="o")
    ax2.set_xlabel("Maand"); ax2.set_ylabel("Aantal schadegevallen")
    ax2.set_title("Lijngrafiek per maand per voertuigtype")
    ax2.legend(title="Voertuig")
    st.pyplot(fig2)

    st.subheader("Aantal schadegevallen per type voertuig")
    chart_data = df_filtered["BusTram_disp"].value_counts()
    if chart_data.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
        chart_data.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen"); ax.set_ylabel("Voertuigtype")
        ax.set_title("Schadegevallen per type voertuig")
        st.pyplot(fig)

        st.subheader("📂 Schadegevallen per voertuigtype")
        for voertuig in chart_data.index.tolist():
            cols = ["Datum", "volledige naam_disp", "Link"] if "Link" in df_filtered.columns else ["Datum", "volledige naam_disp"]
            schade_per_voertuig = df_filtered[df_filtered["BusTram_disp"] == voertuig][cols].sort_values(by="Datum")
            aantal = len(schade_per_voertuig)
            with st.expander(f"{voertuig} — {aantal} schadegevallen"):
                for _, row in schade_per_voertuig.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam_disp"]
                    link = extract_url(row.get("Link")) if "Link" in cols else None
                    if isinstance(link, str) and link:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — ❌ Geen geldige link")

# ========= TAB 4: Locatie =========
with tab4:
    st.subheader("Aantal schadegevallen per locatie")

    chart_data = df_filtered["Locatie_disp"].value_counts()
    if chart_data.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
        chart_data.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen")
        ax.set_ylabel("Locatie")
        ax.set_title("Schadegevallen per locatie")
        st.pyplot(fig)

        st.subheader("📂 Schadegevallen per locatie")
        for locatie in chart_data.index.tolist():
            cols = ["Datum", "volledige naam_disp", "BusTram_disp", "teamcoach_disp", "Link"] if "Link" in df_filtered.columns else ["Datum", "volledige naam_disp", "BusTram_disp", "teamcoach_disp"]
            schade_per_locatie = df_filtered[df_filtered["Locatie_disp"] == locatie][cols].sort_values(by="Datum")
            aantal = len(schade_per_locatie)
            with st.expander(f"{locatie} — {aantal} schadegevallen"):
                for _, row in schade_per_locatie.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam_disp"]
                    voertuig  = row["BusTram_disp"]
                    coach     = row["teamcoach_disp"]
                    link = extract_url(row.get("Link")) if "Link" in cols else None
                    prefix = f"📅 {datum_str} — 👤 {chauffeur} — 🚌 {voertuig} — 🧑‍💼 {coach} — "
                    if isinstance(link, str) and link:
                        st.markdown(prefix + f"[🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(prefix + "❌ Geen geldige link")
