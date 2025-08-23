# ==========================================
# Schadegevallen Dashboard — Performance Editie
# ==========================================
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import tempfile
import plotly.express as px
import plotly.graph_objects as go
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

def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except Exception:
        return -1.0

@st.cache_data(show_spinner=False)
def read_excel_with_key(path, mtime, **kwargs):
    # mtime in cache-key: reload pas bij wijziging
    df = pd.read_excel(path, **kwargs)
    return df

@st.cache_data(show_spinner=False)
def read_parquet_with_key(path, mtime):
    df = pd.read_parquet(path)
    return df

def load_excel_fast(path: str, sheet_name=None) -> pd.DataFrame:
    """
    Snelle loader:
    - als .parquet nieuwer is dan Excel: lees parquet
    - anders: lees Excel en schrijf/overschrijf parquet
    """
    base, _ = os.path.splitext(path)
    pq_path = f"{base}.parquet"
    m_excel = _file_mtime(path)
    m_parquet = _file_mtime(pq_path)

    if m_parquet > m_excel and m_parquet != -1:
        try:
            return read_parquet_with_key(pq_path, m_parquet)
        except Exception:
            pass  # fallback naar Excel

    # Excel lezen (key met mtime)
    try:
        df = read_excel_with_key(path, m_excel, sheet_name=sheet_name)
        # probeer parquet te schrijven voor volgende keer
        try:
            df.to_parquet(pq_path, index=False)
        except Exception:
            pass
        return df
    except FileNotFoundError:
        st.error(f"Bestand niet gevonden: {path}")
        st.stop()
    except Exception as e:
        st.error(f"Kon '{path}' niet lezen: {e}")
        st.stop()

def naam_naar_dn(naam: str) -> str | None:
    if pd.isna(naam):
        return None
    s = str(naam).strip()
    m = re.match(r"\s*(\d+)", s)
    return m.group(1) if m else None

def toon_chauffeur(x):
    if x is None or pd.isna(x):
        return "onbekend"
    s = str(x).strip()
    if not s or s.lower() in {"nan", "none", "<na>"}:
        return "onbekend"
    s = re.sub(r"^\s*\d+\s*-\s*", "", s)  # strip '1234 - '
    return s

def safe_name(x) -> str:
    s = "" if x is pd.NA else str(x or "").strip()
    return "onbekend" if s.lower() in {"nan", "none", ""} else s

def _parse_excel_dates(series: pd.Series) -> pd.Series:
    # Snelle parser met cache; fallback vrijwel nooit nodig
    return pd.to_datetime(series, errors="coerce", dayfirst=True, cache=True)

HYPERLINK_RE = re.compile(r'HYPERLINK\(\s*"([^"]+)"', re.IGNORECASE)

def status_van_chauffeur(naam: str, gecoachte_ids: set[str], coaching_ids: set[str]) -> str:
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

# ========= Coachingslijst =========
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
gebruikers = load_excel_fast("chauffeurs.xlsx")
gebruikers.columns = gebruikers.columns.str.strip().str.lower()

kol_map = {}
if "gebruikersnaam" in gebruikers.columns:
    kol_map["gebruikersnaam"] = "gebruikersnaam"
elif "login" in gebruikers.columns:
    kol_map["login"] = "gebruikersnaam"

if "paswoord" in gebruikers.columns:
    kol_map["paswoord"] = "paswoord"
elif "wachtwoord" in gebruikers.columns:
    kol_map["wachtwoord"] = "paswoord"

for c in ["rol", "dienstnummer", "laatste login"]:
    if c in gebruikers.columns:
        kol_map[c] = c

gebruikers = gebruikers.rename(columns=kol_map)

vereist_login_kolommen = {"gebruikersnaam", "paswoord"}
missend_login = [c for c in vereist_login_kolommen if c not in gebruikers.columns]
if missend_login:
    st.error(f"Login configuratie onvolledig. Ontbrekende kolommen (na normalisatie): {', '.join(missend_login)}")
    st.stop()

gebruikers["gebruikersnaam"] = gebruikers["gebruikersnaam"].astype(str).str.strip()
gebruikers["paswoord"] = gebruikers["paswoord"].astype(str).str.strip()
for c in ["rol", "dienstnummer", "laatste login"]:
    if c not in gebruikers.columns:
        gebruikers[c] = pd.NA

# Session login status
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if LOGIN_ACTIEF and not st.session_state.logged_in:
    st.title("🔐 Inloggen")
    username = st.text_input("Gebruikersnaam")
    password = st.text_input("Wachtwoord", type="password")
    if st.button("Log in"):
        rij = gebruikers.loc[gebruikers["gebruikersnaam"] == str(username).strip()]
        if not rij.empty:
            opgeslagen = str(rij["paswoord"].iloc[0])
            ok = (opgeslagen == str(password)) or (opgeslagen == hash_wachtwoord(password))
            if ok:
                st.session_state.logged_in = True
                st.session_state.username = str(username).strip()
                st.success("✅ Ingelogd!")
                if "laatste login" in gebruikers.columns:
                    try:
                        gebruikers.loc[rij.index, "laatste login"] = datetime.now()
                        gebruikers.to_excel("chauffeurs.xlsx", index=False)
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
    rol = "teamcoach"; naam_login = "demo"
else:
    ingelogde_info = gebruikers.loc[gebruikers["gebruikersnaam"] == st.session_state.username].iloc[0]
    rol = str(ingelogde_info.get("rol", "teamcoach")).strip()
    if rol == "chauffeur":
        naam_login = str(ingelogde_info.get("dienstnummer", ingelogde_info["gebruikersnaam"]))
    else:
        naam_login = str(ingelogde_info["gebruikersnaam"]).strip()

# ========= Data laden =========
raw = load_excel_fast("schade met macro.xlsm", sheet_name="BRON")
raw = raw.copy()  # éénmalige copy voor bewerking
raw.columns = raw.columns.str.strip()

# parse datums
if "Datum" not in raw.columns:
    st.error("Kolom 'Datum' ontbreekt in de brondata.")
    st.stop()
raw["Datum"] = _parse_excel_dates(raw["Datum"])

# normaliseer relevante kolommen
for col in ["volledige naam", "teamcoach", "Locatie", "Bus/ Tram", "Link"]:
    if col in raw.columns:
        raw[col] = raw[col].astype("string").str.strip()

# filter op geldige datums
df = raw[raw["Datum"].notna()]

# display-kolommen + categoricals
df["volledige naam_disp"] = df["volledige naam"].map(safe_name)
df["teamcoach_disp"]      = df["teamcoach"].map(safe_name)
df["Locatie_disp"]        = df["Locatie"].map(safe_name)
df["BusTram_disp"]        = df["Bus/ Tram"].map(safe_name)

for c in ["volledige naam_disp","teamcoach_disp","Locatie_disp","BusTram_disp"]:
    df[c] = df[c].astype("category")

# afgeleiden
df["dienstnummer"] = df["volledige naam"].astype(str).str.extract(r"^(\d+)", expand=False).astype("string").str.strip()
df["KwartaalP"]    = df["Datum"].dt.to_period("Q")
df["Kwartaal"]     = df["KwartaalP"].astype(str)

# vectorized links (Link_url)
if "Link" in df.columns:
    s = df["Link"].astype("string").str.strip()
    direct = s.str.startswith(("http://", "https://"), na=False)
    df["Link_url"] = s.where(direct, s.str.extract(HYPERLINK_RE, expand=False))
else:
    df["Link_url"] = pd.NA

# ========= Coachingslijst =========
gecoachte_ids, coaching_ids, coach_warn = lees_coachingslijst()
if coach_warn:
    st.sidebar.warning(f"⚠️ {coach_warn}")

# Flags op df
df["gecoacht_geel"]  = df["dienstnummer"].astype(str).isin(gecoachte_ids)
df["gecoacht_blauw"] = df["dienstnummer"].astype(str).isin(coaching_ids)

# ========= UI: Titel + Caption =========
st.title("📊 Schadegevallen Dashboard")
st.caption("🟡 = voltooide coaching · 🔵 = in coaching (lopend)")

# ========= Query params & opties =========
qp = st.query_params  # Streamlit 1.32+
def _clean_list(values, allowed):
    return [v for v in (values or []) if v in allowed]

df_for_options = df  # al gefilterd op geldige datums
teamcoach_options = sorted(df["teamcoach_disp"].dropna().cat.categories.tolist() if hasattr(df["teamcoach_disp"], "cat") else df["teamcoach_disp"].dropna().unique().tolist())
locatie_options   = sorted(df["Locatie_disp"].dropna().cat.categories.tolist() if hasattr(df["Locatie_disp"], "cat") else df["Locatie_disp"].dropna().unique().tolist())
voertuig_options  = sorted(df["BusTram_disp"].dropna().cat.categories.tolist() if hasattr(df["BusTram_disp"], "cat") else df["BusTram_disp"].dropna().unique().tolist())
kwartaal_options  = sorted(df_for_options["KwartaalP"].dropna().astype(str).unique().tolist())

pref_tc = _clean_list(qp.get_all("teamcoach"), teamcoach_options) or teamcoach_options
pref_lo = _clean_list(qp.get_all("locatie"),  locatie_options)  or locatie_options
pref_vh = _clean_list(qp.get_all("voertuig"),  voertuig_options) or voertuig_options
pref_kw = _clean_list(qp.get_all("kwartaal"),  kwartaal_options)  or kwartaal_options

with st.sidebar:
    st.image("logo.png", use_container_width=True)

with st.sidebar:
    st.header("🔍 Filters")

    ALL_COACHES = "— Alle teamcoaches —"
    teamcoach_opts_with_all = [ALL_COACHES] + teamcoach_options

    selected_teamcoaches_raw = st.multiselect(
        "Teamcoach",
        options=teamcoach_opts_with_all,
        default=[],  # leeg bij start
        help="Kies één of meer teamcoaches of selecteer '— Alle teamcoaches —'."
    )
    selected_teamcoaches = teamcoach_options if ALL_COACHES in selected_teamcoaches_raw else selected_teamcoaches_raw

    selected_locaties   = st.multiselect("Locatie",      options=locatie_options,  default=pref_lo)
    selected_voertuigen = st.multiselect("Voertuigtype", options=voertuig_options, default=pref_vh)
    selected_kwartalen  = st.multiselect("Kwartaal",     options=kwartaal_options, default=pref_kw)

    if selected_kwartalen:
        sel_periods_idx = pd.PeriodIndex(selected_kwartalen, freq="Q")
        date_from = sel_periods_idx.start_time.min().date()
        date_to   = sel_periods_idx.end_time.max().date()
    else:
        date_from = df["Datum"].min().date()
        date_to   = df["Datum"].max().date()

    if st.button("🔄 Reset filters"):
        qp.clear()
        st.rerun()

if not selected_teamcoaches:
    st.warning("⚠️ Kies eerst minstens één teamcoach in de filters (of selecteer ‘— Alle teamcoaches —’).")
    st.stop()

# ========= Filters toepassen (zonder onnodige copies) =========
sel_periods = pd.PeriodIndex(selected_kwartalen, freq="Q") if selected_kwartalen else pd.PeriodIndex([], freq="Q")
mask = (
    df["teamcoach_disp"].isin(selected_teamcoaches) &
    df["Locatie_disp"].isin(selected_locaties) &
    df["BusTram_disp"].isin(selected_voertuigen) &
    (df["KwartaalP"].isin(sel_periods) if len(sel_periods) > 0 else True)
)
df_filtered = df[mask]
mask_date = (df_filtered["Datum"].dt.date >= date_from) & (df_filtered["Datum"].dt.date <= date_to)
df_filtered = df_filtered[mask_date]

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

# ========= Precomputes voor tabs =========
counts_by_driver   = df_filtered["volledige naam_disp"].value_counts()
counts_by_coach    = df_filtered["teamcoach_disp"].value_counts()
counts_by_vehicle  = df_filtered["BusTram_disp"].value_counts()
counts_by_location = df_filtered["Locatie_disp"].value_counts()

# ========= Tabs =========
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["👤 Chauffeur", "🧑‍💼 Teamcoach", "🚌 Voertuig", "📍 Locatie", "📈 Pareto", "🔎 Opzoeken"]
)

# ========= PDF Export (per teamcoach) =========
st.markdown("---")
st.sidebar.subheader("📄 PDF Export per teamcoach")
pdf_coach = st.sidebar.selectbox("Kies teamcoach voor export", teamcoach_options)
generate_pdf = st.sidebar.button("Genereer PDF")

if generate_pdf:
    kolommen_pdf = ["Datum", "volledige naam_disp", "Locatie_disp", "BusTram_disp", "Link_url"]
    schade_pdf = df_filtered[df_filtered["teamcoach_disp"] == pdf_coach][kolommen_pdf].sort_values("Datum")

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f"Overzicht schadegevallen - Teamcoach: <b>{pdf_coach}</b>", styles["Title"]))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(f"📅 Rapportdatum: {datetime.today().strftime('%d-%m-%Y')}", styles["Normal"]))
    elements.append(Spacer(1, 8))

    totaal = len(schade_pdf)
    elements.append(Paragraph(f"📌 Totaal aantal schadegevallen: <b>{totaal}</b>", styles["Normal"]))
    elements.append(Spacer(1, 8))

    if not schade_pdf.empty:
        eerste_datum = schade_pdf["Datum"].min().strftime("%d-%m-%Y")
        laatste_datum = schade_pdf["Datum"].max().strftime("%d-%m-%Y")
        elements.append(Paragraph("📊 Samenvatting:", styles["Heading2"]))
        elements.append(Paragraph(f"- Periode: {eerste_datum} t/m {laatste_datum}", styles["Normal"]))
        elements.append(Paragraph(f"- Unieke chauffeurs: {schade_pdf['volledige naam_disp'].nunique()}", styles["Normal"]))
        elements.append(Paragraph(f"- Unieke locaties: {schade_pdf['Locatie_disp'].nunique()}", styles["Normal"]))
        elements.append(Spacer(1, 8))

    # Aantal per chauffeur (compacte tabel)
    aantal_per_chauffeur = schade_pdf["volledige naam_disp"].value_counts().reset_index()
    aantal_per_chauffeur.columns = ["Chauffeur", "Aantal"]
    if not aantal_per_chauffeur.empty:
        data_ch = [["Chauffeur", "Aantal"]] + aantal_per_chauffeur.values.tolist()
        tbl_ch = Table(data_ch, repeatRows=1, colWidths=[250, 60])
        tbl_ch.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("FONTSIZE", (0,0), (-1,-1), 8),
        ]))
        elements.append(Paragraph("👤 Aantal per chauffeur:", styles["Heading2"]))
        elements.append(tbl_ch)
        elements.append(Spacer(1, 8))

    # Aantal per locatie (compacte tabel)
    aantal_per_locatie = schade_pdf["Locatie_disp"].value_counts().reset_index()
    aantal_per_locatie.columns = ["Locatie", "Aantal"]
    if not aantal_per_locatie.empty:
        data_lo = [["Locatie", "Aantal"]] + aantal_per_locatie.values.tolist()
        tbl_lo = Table(data_lo, repeatRows=1, colWidths=[250, 60])
        tbl_lo.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("FONTSIZE", (0,0), (-1,-1), 8),
        ]))
        elements.append(Paragraph("📍 Aantal per locatie:", styles["Heading2"]))
        elements.append(tbl_lo)
        elements.append(Spacer(1, 8))

    # Grafiek per maand
    if not schade_pdf.empty:
        schade_pdf = schade_pdf.assign(Maand=schade_pdf["Datum"].dt.to_period("M").astype(str))
        maand_data = schade_pdf["Maand"].value_counts().sort_index()
        if not maand_data.empty:
            fig, ax = plt.subplots()
            maand_data.plot(kind="bar", ax=ax)
            ax.set_title("Schadegevallen per maand")
            ax.set_ylabel("Aantal")
            plt.xticks(rotation=45)
            plt.tight_layout()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
                fig.savefig(tmpfile.name, dpi=150)
                plt.close(fig)
                elements.append(Paragraph("📊 Schadegevallen per maand:", styles["Heading2"]))
                elements.append(Spacer(1, 4))
                elements.append(Image(tmpfile.name, width=400, height=200))
                elements.append(Spacer(1, 8))

    # Individuele schadegevallen (tabel)
    head = ["Datum", "Chauffeur", "Voertuig", "Locatie", "Link"]
    rows = []
    for _, r in schade_pdf.iterrows():
        datum = r["Datum"].strftime("%d-%m-%Y") if pd.notna(r["Datum"]) else "onbekend"
        rows.append([
            datum,
            safe_name(r["volledige naam_disp"]),
            safe_name(r["BusTram_disp"]),
            safe_name(r["Locatie_disp"]),
            (r["Link_url"] if isinstance(r["Link_url"], str) and r["Link_url"] else "-")
        ])
    if rows:
        tbl = Table([head] + rows, repeatRows=1, colWidths=[60, 150, 70, 130, 120])
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("ALIGN", (0,0), (-1,0), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.whitesmoke, colors.white]),
        ]))
        elements.append(Paragraph("📂 Individuele schadegevallen:", styles["Heading2"]))
        elements.append(tbl)

    doc.build(elements)
    buffer.seek(0)
    bestandsnaam = f"schade_{pdf_coach.replace(' ', '_')}_{datetime.today().strftime('%Y%m%d')}.pdf"
    st.sidebar.download_button(label="📥 Download PDF", data=buffer, file_name=bestandsnaam, mime="application/pdf")

# ========= TAB 1: Chauffeur =========
with tab1:
    st.subheader("📂 Schadegevallen per chauffeur")
    if counts_by_driver.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        plot_df = counts_by_driver.rename_axis("chauffeur").reset_index(name="aantal")
        # status + badge (vectorized via apply met closure)
        plot_df["status"] = plot_df["chauffeur"].apply(lambda x: status_van_chauffeur(x, gecoachte_ids, coaching_ids))
        plot_df["badge"]  = plot_df["status"].apply(badge_van_status)

        totaal_chauffeurs_auto = int(plot_df["chauffeur"].nunique())
        totaal_schades = int(plot_df["aantal"].sum())

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Aantal chauffeurs (met schade)", totaal_chauffeurs_auto)
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

        # Intervalgroepen (robuste bins)
        step = 5
        max_val = int(plot_df["aantal"].max())
        edges = [0, step] if max_val <= 0 else list(range(0, max_val + step, step))
        if edges[-1] < max_val:
            edges.append(edges[-1] + step)
        plot_df["interval"] = pd.cut(plot_df["aantal"], bins=edges, right=True, include_lowest=True)

        # In plaats van honderden markdowns: toon per interval een dataframe
        for interval, groep in plot_df.groupby("interval", sort=False):
            if groep.empty or pd.isna(interval):
                continue
            left, right = int(interval.left), int(interval.right)
            low = max(1, left + 1)
            titel = f"{low} t/m {right} schades ({len(groep)} chauffeurs)"
            with st.expander(titel):
                # voeg badge-emoji in een kolom voor visuele cue
                g2 = groep.sort_values("aantal", ascending=False)[["badge","chauffeur","aantal","status"]]
                st.dataframe(g2, use_container_width=True)

# ========= TAB 2: Teamcoach =========
with tab2:
    st.subheader("Aantal schadegevallen per teamcoach")
    if counts_by_coach.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(counts_by_coach) * 0.3 + 1)))
        counts_by_coach.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen"); ax.set_ylabel("Teamcoach")
        ax.set_title("Schadegevallen per teamcoach")
        st.pyplot(fig); plt.close(fig)

        st.subheader("📂 Schadegevallen per teamcoach")
        # Eén dataframe per coach (expander) i.p.v. per rij markdown
        base_cols = ["Datum","volledige naam_disp","BusTram_disp","Locatie_disp","teamcoach_disp","Link_url"]
        for coach in counts_by_coach.sort_values(ascending=False).index.tolist():
            schade_per_coach = df_filtered.loc[df_filtered["teamcoach_disp"] == coach, base_cols]
            schade_per_coach = schade_per_coach.sort_values("Datum")
            aantal = len(schade_per_coach)
            with st.expander(f"{coach} — {aantal} schadegevallen"):
                st.dataframe(
                    schade_per_coach,
                    column_config={
                        "Datum": st.column_config.DateColumn("Datum", format="DD-MM-YYYY"),
                        "volledige naam_disp": st.column_config.TextColumn("Chauffeur"),
                        "BusTram_disp": st.column_config.TextColumn("Voertuig"),
                        "Locatie_disp": st.column_config.TextColumn("Locatie"),
                        "Link_url": st.column_config.LinkColumn("Link", display_text="🔗 openen"),
                    },
                    use_container_width=True,
                )

# ========= TAB 3: Voertuig =========
with tab3:
    st.subheader("📈 Schadegevallen per maand per voertuigtype")
    df_per_maand = df_filtered[df_filtered["Datum"].notna()]
    maanden_nl = {
        1:"januari",2:"februari",3:"maart",4:"april",5:"mei",6:"juni",
        7:"juli",8:"augustus",9:"september",10:"oktober",11:"november",12:"december"
    }
    maand_volgorde = ["januari","februari","maart","april","mei","juni",
                      "juli","augustus","september","oktober","november","december"]

    if not df_per_maand.empty:
        df_per_maand = df_per_maand.assign(Maand=df_per_maand["Datum"].dt.month.map(maanden_nl).str.lower())
        voertuig_col = "BusTram_disp"
        groep = (
            df_per_maand.groupby(["Maand", voertuig_col])
            .size()
            .unstack(fill_value=0)
            .reindex(maand_volgorde)
            .fillna(0)
        )
        fig2, ax2 = plt.subplots(figsize=(10, 4))
        groep.plot(ax=ax2, marker="o")
        ax2.set_xlabel("Maand"); ax2.set_ylabel("Aantal schadegevallen")
        ax2.set_title("Lijngrafiek per maand per voertuigtype")
        ax2.legend(title="Voertuig")
        st.pyplot(fig2); plt.close(fig2)
    else:
        st.info("ℹ️ Geen geldige datums binnen de huidige filters om een maandoverzicht te tonen.")

    st.subheader("Aantal schadegevallen per type voertuig")
    if counts_by_vehicle.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(counts_by_vehicle) * 0.3 + 1)))
        counts_by_vehicle.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen"); ax.set_ylabel("Voertuigtype")
        ax.set_title("Schadegevallen per type voertuig")
        st.pyplot(fig); plt.close(fig)

        st.subheader("📂 Schadegevallen per voertuigtype")
        base_cols = ["Datum","volledige naam_disp","teamcoach_disp","Locatie_disp","Link_url","BusTram_disp"]
        for voertuig in counts_by_vehicle.sort_values(ascending=False).index.tolist():
            schade_per_voertuig = df_filtered.loc[df_filtered["BusTram_disp"] == voertuig, base_cols]
            schade_per_voertuig = schade_per_voertuig.sort_values("Datum")
            aantal = len(schade_per_voertuig)
            with st.expander(f"{voertuig} — {aantal} schadegevallen"):
                st.dataframe(
                    schade_per_voertuig.drop(columns=["BusTram_disp"]),
                    column_config={
                        "Datum": st.column_config.DateColumn("Datum", format="DD-MM-YYYY"),
                        "volledige naam_disp": st.column_config.TextColumn("Chauffeur"),
                        "teamcoach_disp": st.column_config.TextColumn("Teamcoach"),
                        "Locatie_disp": st.column_config.TextColumn("Locatie"),
                        "Link_url": st.column_config.LinkColumn("Link", display_text="🔗 openen"),
                    },
                    use_container_width=True,
                )

# ========= TAB 4: Locatie =========
with tab4:
    st.subheader("Aantal schadegevallen per locatie")
    if counts_by_location.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(counts_by_location) * 0.3 + 1)))
        counts_by_location.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen"); ax.set_ylabel("Locatie")
        ax.set_title("Schadegevallen per locatie")
        st.pyplot(fig); plt.close(fig)

        st.subheader("📂 Schadegevallen per locatie")
        base_cols = ["Datum","volledige naam_disp","BusTram_disp","teamcoach_disp","Link_url","Locatie_disp"]
        for locatie in counts_by_location.sort_values(ascending=False).index.tolist():
            schade_per_locatie = df_filtered.loc[df_filtered["Locatie_disp"] == locatie, base_cols]
            schade_per_locatie = schade_per_locatie.sort_values("Datum")
            aantal = len(schade_per_locatie)
            with st.expander(f"{locatie} — {aantal} schadegevallen"):
                st.dataframe(
                    schade_per_locatie.drop(columns=["Locatie_disp"]),
                    column_config={
                        "Datum": st.column_config.DateColumn("Datum", format="DD-MM-YYYY"),
                        "volledige naam_disp": st.column_config.TextColumn("Chauffeur"),
                        "BusTram_disp": st.column_config.TextColumn("Voertuig"),
                        "teamcoach_disp": st.column_config.TextColumn("Teamcoach"),
                        "Link_url": st.column_config.LinkColumn("Link", display_text="🔗 openen"),
                    },
                    use_container_width=True,
                )

# ========= TAB 5: Pareto =========
with tab5:
    st.subheader("📈 Pareto-analyse (80/20)")

    st.markdown("""
    ### ℹ️ Wat is Pareto?
    **80% van de gevolgen** komt vaak uit **20% van de oorzaken**. In dit dashboard:
    80% van de schades kan vaak worden verklaard door een beperkt aantal **chauffeurs**, **locaties**, of **voertuigen**.
    """)

    dim_opties = {
        "Chauffeur": "volledige naam_disp",
        "Locatie": "Locatie_disp",
        "Voertuig": "BusTram_disp",
        "Teamcoach": "teamcoach_disp",
    }
    dim_keuze = st.selectbox("Dimensie", list(dim_opties.keys()), index=0)
    kol = dim_opties[dim_keuze]

    base_df = df_filtered
    if dim_keuze == "Chauffeur" and "dienstnummer" in base_df.columns:
        base_df = base_df[base_df["dienstnummer"].astype(str).str.strip() != "9999"]

    if kol not in base_df.columns or base_df.empty:
        st.info("Geen data om te tonen voor deze selectie.")
    else:
        counts_all = base_df[kol].value_counts()
        max_n = int(len(counts_all))
        if max_n == 0:
            st.info("Geen data om te tonen voor deze selectie.")
        else:
            vals = counts_all.values.astype(float)
            totaal = float(vals.sum())
            cum = np.cumsum(vals) / (totaal if totaal else 1.0)

            # 80%-punt
            k80 = int(np.searchsorted(cum, 0.80))
            k80 = min(max_n - 1, max(0, k80))
            idx80_label = counts_all.index[k80]
            cum80 = float(cum[k80])

            min_n = 1
            hard_cap = 200
            max_slider = min(hard_cap, max_n)
            default_n = min(20, max_slider)
            top_n = st.slider("Toon top N", min_value=min_n, max_value=max_slider, value=default_n, step=1)
            counts_top = counts_all.head(top_n)

            fig = go.Figure()
            fig.add_bar(
                x=counts_top.index,
                y=counts_top.values,
                name="Aantal schades",
                hovertemplate=f"{dim_keuze}: %{{x}}<br>Aantal: %{{y}}<extra></extra>",
            )
            fig.add_scatter(
                x=list(counts_all.index),
                y=list(cum),
                mode="lines+markers",
                name="Cumulatief aandeel",
                yaxis="y2",
                hovertemplate=f"{dim_keuze}: %{{x}}<br>Cumulatief: %{{y:.1%}}<extra></extra>",
            )
            shapes = [
                dict(type="line", x0=0, x1=max_n, y0=0.8, y1=0.8, yref="y2",
                     line=dict(dash="dash")),
                dict(type="line", xref="x", yref="paper",
                     x0=idx80_label, x1=idx80_label, y0=0, y1=1,
                     line=dict(dash="dot")),
            ]
            fig.update_layout(
                title=f"Pareto — {dim_keuze} (80% hulplijn)",
                xaxis=dict(tickangle=-45, showticklabels=False),
                yaxis=dict(title="Aantal schades"),
                yaxis2=dict(title="Cumulatief aandeel", overlaying="y", side="right", range=[0, 1.05]),
                shapes=shapes,
                annotations=[
                    dict(
                        x=idx80_label, y=cum80, xref="x", yref="y2",
                        text=f"80% bij #{k80+1}",
                        showarrow=True, arrowhead=2, ax=0, ay=-30, bgcolor="white",
                    )
                ],
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, use_container_width=True)

            df_pareto = counts_all.reset_index()
            df_pareto.columns = [dim_keuze, "Aantal"]
            df_pareto["Bijdrage %"] = (df_pareto["Aantal"] / totaal * 100).round(1)
            df_pareto["Cumulatief %"] = (df_pareto["Aantal"].cumsum() / totaal * 100).round(1)
            df_pareto["Top 80%"] = df_pareto.index <= k80

            colA, colB = st.columns(2)
            colA.metric("Aantal elementen tot 80%", k80 + 1)
            colB.metric("Cumulatief aandeel bij markering", f"{cum80*100:.1f}%")

            st.markdown("#### Top 20 detail")
            st.dataframe(df_pareto.head(20), use_container_width=True)

# ========= TAB 6: Opzoeken =========
with tab6:
    st.subheader("🔎 Opzoeken op personeelsnummer")
    zoek = st.text_input("Personeelsnummer (dienstnummer)", placeholder="bv. 41092")
    dn_in = "".join(re.findall(r"\d+", str(zoek)))  # alleen cijfers

    if not dn_in:
        st.info("Geef een personeelsnummer in om resultaten te zien.")
    else:
        if "dienstnummer" not in df.columns:
            st.error("Kolom 'dienstnummer' ontbreekt in de data.")
        else:
            res = df[df["dienstnummer"].astype(str).str.strip() == dn_in]
            if res.empty:
                st.warning(f"Geen resultaten gevonden voor personeelsnr **{dn_in}**.")
            else:
                naam_chauffeur = res["volledige naam_disp"].iloc[0]
                naam_teamcoach = res["teamcoach_disp"].iloc[0] if "teamcoach_disp" in res.columns else "onbekend"
                st.markdown(f"**👤 Chauffeur:** {naam_chauffeur}")
                st.markdown(f"**🧑‍💼 Teamcoach:** {naam_teamcoach}")
                st.markdown("---")
                st.metric("Aantal schadegevallen", len(res))

                heeft_link = "Link_url" in res.columns
                toon_kol = ["Datum", "Locatie_disp"] + (["Link_url"] if heeft_link else [])
                res2 = res.sort_values("Datum", ascending=False)[toon_kol]

                if heeft_link:
                    st.dataframe(
                        res2,
                        column_config={
                            "Datum": st.column_config.DateColumn("Datum", format="DD-MM-YYYY"),
                            "Locatie_disp": st.column_config.TextColumn("Locatie"),
                            "Link_url": st.column_config.LinkColumn("Link", display_text="🔗 openen")
                        },
                        use_container_width=True,
                    )
                else:
                    st.dataframe(
                        res2,
                        column_config={
                            "Datum": st.column_config.DateColumn("Datum", format="DD-MM-YYYY"),
                            "Locatie_disp": st.column_config.TextColumn("Locatie"),
                        },
                        use_container_width=True,
                    )
