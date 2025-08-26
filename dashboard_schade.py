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
from streamlit_autorefresh import st_autorefresh


# ========= Instellingen =========
LOGIN_ACTIEF = False  # Zet True om login te activeren
plt.rcParams["figure.dpi"] = 150
st.set_page_config(page_title="Schadegevallen Dashboard", layout="wide")

# 🔄 Auto-refresh: herlaad de pagina elk uur
st_autorefresh(interval=3600 * 1000, key="data_refresh")


# ========= Helpers =========
def hash_wachtwoord(wachtwoord: str) -> str:
    return hashlib.sha256(str(wachtwoord).encode()).hexdigest()

@st.cache_data(show_spinner=False, ttl=3600)  # cache max 1 uur geldig
def load_excel(path, **kwargs):
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

with st.sidebar:
    st.image("logo.png", use_container_width=True)
    st.header("🔍 Filters")

    # Helperfunctie: multiselect met "Alle"-optie
    def multiselect_all(label, options, all_label, key):
        opts_with_all = [all_label] + options
        picked_raw = st.multiselect(label, options=opts_with_all, default=[all_label], key=key)
        picked = options if (all_label in picked_raw or len(picked_raw) == 0) else picked_raw
        return picked

    # Teamcoach
    selected_teamcoaches = multiselect_all(
        "Teamcoach", teamcoach_options, "— Alle teamcoaches —", key="filter_teamcoach"
    )

    # Locatie
    selected_locaties = multiselect_all(
        "Locatie", locatie_options, "— Alle locaties —", key="filter_locatie"
    )

    # Voertuig
    selected_voertuigen = multiselect_all(
        "Voertuigtype", voertuig_options, "— Alle voertuigen —", key="filter_voertuig"
    )

    # Kwartaal
    selected_kwartalen = multiselect_all(
        "Kwartaal", kwartaal_options, "— Alle kwartalen —", key="filter_kwartaal"
    )

    # Periode afleiden uit kwartalen of volledige dataset
    if selected_kwartalen:
        sel_periods_idx = pd.PeriodIndex(selected_kwartalen, freq="Q")
        date_from = sel_periods_idx.start_time.min().normalize()
        date_to   = sel_periods_idx.end_time.max().normalize()
    else:
        date_from = df["Datum"].min().normalize()
        date_to   = df["Datum"].max().normalize()

    if st.button("🔄 Reset filters"):
        st.query_params.clear()
        st.rerun()

# === Filters toepassen ===
apply_quarters = bool(selected_kwartalen)
sel_periods = pd.PeriodIndex(selected_kwartalen, freq="Q") if apply_quarters else None

mask = (
    df["teamcoach_disp"].isin(selected_teamcoaches)
    & df["Locatie_disp"].isin(selected_locaties)
    & df["BusTram_disp"].isin(selected_voertuigen)
    & (df["KwartaalP"].isin(sel_periods) if apply_quarters else True)
)
df_filtered = df.loc[mask]

# Datumfilter
start = pd.to_datetime(date_from)
end   = pd.to_datetime(date_to) + pd.Timedelta(days=1)  # inclusief einddag
mask_date = (df_filtered["Datum"] >= start) & (df_filtered["Datum"] < end)
df_filtered = df_filtered.loc[mask_date]

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

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["👤 Chauffeur", "🧑‍💼 Teamcoach", "🚌 Voertuig", "📍 Locatie", "📈 Pareto", "🔎 Opzoeken"]
)





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
# ======= NIEUW: maandoverzicht met jaar-maand (YYYY-MM) =======
with tab3:
    st.subheader("📈 Schadegevallen per maand per voertuigtype")

    # Werk op een kopie; alleen rijen met geldige datum
    df_per_maand = df_filtered.copy()
    if "Datum" in df_per_maand.columns:
        df_per_maand = df_per_maand[df_per_maand["Datum"].notna()].copy()
    else:
        df_per_maand["Datum"] = pd.NaT  # voor uniforme kolommen

    # Bepaal kolomnaam voor voertuigtype
    voertuig_col = (
        "BusTram_disp" if "BusTram_disp" in df_per_maand.columns
        else ("Bus/ Tram" if "Bus/ Tram" in df_per_maand.columns else None)
    )

    if voertuig_col is None:
        st.warning("⚠️ Kolom voor voertuigtype niet gevonden.")
    elif df_per_maand.empty:
        st.info("ℹ️ Geen geldige datums binnen de huidige filters om een maandoverzicht te tonen.")
    else:
        # 1) Maak jaar-maand sleutel (YYYY-MM), zodat 2024-01 ≠ 2025-01
        df_per_maand["JaarMaandP"] = df_per_maand["Datum"].dt.to_period("M")
        df_per_maand["JaarMaand"]  = df_per_maand["JaarMaandP"].astype(str)

        # 2) Tel per jaar-maand × voertuigtype
        groep = (
            df_per_maand.groupby(["JaarMaand", voertuig_col])
            .size()
            .unstack(fill_value=0)
        )

        # 3) Vul ontbrekende maanden tussen min en max met 0, zodat de lijn doorloopt
        start_m = df_per_maand["JaarMaandP"].min()
        eind_m  = df_per_maand["JaarMaandP"].max()
        alle_maanden = pd.period_range(start=start_m, end=eind_m, freq="M").astype(str)
        groep = groep.reindex(alle_maanden, fill_value=0)

        # 4) Plot lijngrafiek
        fig2, ax2 = plt.subplots(figsize=(10, 4))
        groep.plot(ax=ax2, marker="o")
        ax2.set_xlabel("Jaar-Maand")
        ax2.set_ylabel("Aantal schadegevallen")
        ax2.set_title("Schadegevallen per maand per voertuigtype (YYYY-MM)")
        ax2.legend(title="Voertuig")
        plt.xticks(rotation=45)
        plt.tight_layout()
        st.pyplot(fig2)

    # ===== Het resterende deel van TAB 3 ( "Aantal schadegevallen per type voertuig" ) laat je ongewijzigd staan. =====


    st.subheader("Aantal schadegevallen per type voertuig")

    # Telling per voertuigtype op de display-kolom
    voertuig_col = "BusTram_disp" if "BusTram_disp" in df_filtered.columns else None
    if voertuig_col is None:
        st.warning("⚠️ Kolom voor voertuigtype niet gevonden.")
    else:
        chart_data = df_filtered[voertuig_col].value_counts()

        if chart_data.empty:
            st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
        else:
            # Staafdiagram horizontaal; dynamische hoogte
            fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
            chart_data.sort_values().plot(kind="barh", ax=ax)
            ax.set_xlabel("Aantal schadegevallen")
            ax.set_ylabel("Voertuigtype")
            ax.set_title("Schadegevallen per type voertuig")
            st.pyplot(fig)

            st.subheader("📂 Schadegevallen per voertuigtype")

            # Loop in aflopende volgorde van aantal
            for voertuig in chart_data.sort_values(ascending=False).index.tolist():
                # Kolommen veilig samenstellen; Link is optioneel
                kol_list = ["Datum", "volledige naam_disp"]
                if voertuig_col not in kol_list: 
                    kol_list.append(voertuig_col)
                if "Link" in df_filtered.columns:
                    kol_list.append("Link")
                if "teamcoach_disp" in df_filtered.columns:
                    kol_list.append("teamcoach_disp")
                if "Locatie_disp" in df_filtered.columns:
                    kol_list.append("Locatie_disp")

                schade_per_voertuig = (
                    df_filtered.loc[df_filtered[voertuig_col] == voertuig, [k for k in kol_list if k in df_filtered.columns]]
                    .sort_values(by="Datum")
                )
                aantal = len(schade_per_voertuig)

                with st.expander(f"{voertuig} — {aantal} schadegevallen"):
                    if schade_per_voertuig.empty:
                        st.caption("Geen rijen binnen de huidige filters.")
                    else:
                        for _, row in schade_per_voertuig.iterrows():
                            datum_obj = row.get("Datum")
                            datum_str = datum_obj.strftime("%d-%m-%Y") if pd.notna(datum_obj) else "onbekend"
                            chauffeur = row.get("volledige naam_disp", "onbekend")
                            coach     = row.get("teamcoach_disp", "onbekend")
                            locatie   = row.get("Locatie_disp", "onbekend")

                            # Link (optioneel + Excel-formules toestaan)
                            link = extract_url(row.get("Link")) if "Link" in schade_per_voertuig.columns else None

                            prefix = f"📅 {datum_str} — 👤 {chauffeur} — 🧑‍💼 {coach} — 📍 {locatie} — "
                            if isinstance(link, str) and link:
                                st.markdown(prefix + f"[🔗 Link]({link})", unsafe_allow_html=True)
                            else:
                                st.markdown(prefix + "❌ Geen geldige link")

# ========= TAB 4: Locatie =========
with tab4:
    st.subheader("Aantal schadegevallen per locatie")

    # Werk op de display-kolom zodat 'onbekend' ook meetelt
    locatie_col = "Locatie_disp" if "Locatie_disp" in df_filtered.columns else None
    if locatie_col is None:
        st.warning("⚠️ Kolom voor locatie niet gevonden.")
    else:
        chart_data = df_filtered[locatie_col].value_counts()

        if chart_data.empty:
            st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
        else:
            # Staafdiagram horizontaal; dynamische hoogte bij veel locaties
            fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
            chart_data.sort_values().plot(kind="barh", ax=ax)
            ax.set_xlabel("Aantal schadegevallen")
            ax.set_ylabel("Locatie")
            ax.set_title("Schadegevallen per locatie")
            st.pyplot(fig)

            st.subheader("📂 Schadegevallen per locatie")

            # Loop in aflopende volgorde van aantal
            for locatie in chart_data.sort_values(ascending=False).index.tolist():
                # Kolommen veilig bepalen; Link is optioneel
                kol_list = ["Datum", "volledige naam_disp", "BusTram_disp", "teamcoach_disp"]
                if "Link" in df_filtered.columns:
                    kol_list.append("Link")
                # Filter & sorteer
                aanwezige_kol = [k for k in kol_list if k in df_filtered.columns]
                schade_per_locatie = (
                    df_filtered.loc[df_filtered[locatie_col] == locatie, aanwezige_kol]
                    .sort_values(by="Datum")
                )
                aantal = len(schade_per_locatie)

                with st.expander(f"{locatie} — {aantal} schadegevallen"):
                    if schade_per_locatie.empty:
                        st.caption("Geen rijen binnen de huidige filters.")
                    else:
                        for _, row in schade_per_locatie.iterrows():
                            # Datum
                            datum_obj = row.get("Datum")
                            datum_str = datum_obj.strftime("%d-%m-%Y") if pd.notna(datum_obj) else "onbekend"
                            # Velden met veilige fallback
                            chauffeur = row.get("volledige naam_disp", "onbekend")
                            voertuig  = row.get("BusTram_disp", "onbekend")
                            coach     = row.get("teamcoach_disp", "onbekend")

                            # Link (optioneel + Excel HYPERLINK-ondersteuning)
                            link = extract_url(row.get("Link")) if "Link" in schade_per_locatie.columns else None

                            prefix = f"📅 {datum_str} — 👤 {chauffeur} — 🚌 {voertuig} — 🧑‍💼 {coach} — "
                            if isinstance(link, str) and link:
                                st.markdown(prefix + f"[🔗 Link]({link})", unsafe_allow_html=True)
                            else:
                                st.markdown(prefix + "❌ Geen geldige of aanwezige link")



# ... jouw bestaande tab1..tab4 code blijft ...

# ========= TAB 5: Pareto =========
with tab5:
    st.subheader("📈 Pareto-analyse (80/20)")

    # 📘 Uitlegtekst netjes opgemaakt
    st.markdown("""
    ### ℹ️ Wat is Pareto?
    De **Pareto-analyse** is gebaseerd op het **80/20-principe**:

    - **80% van de gevolgen** komt vaak uit **20% van de oorzaken**.  
    - Met andere woorden: een klein aantal factoren heeft een **grote invloed**.  

    In dit dashboard:  
    ➡️ 80% van de schadegevallen kan vaak worden verklaard door een beperkt aantal **chauffeurs**, **locaties**, of **voertuigen**.

    ---

    ### 🔎 Hoe werkt de grafiek?
    - De **blauwe balken** tonen het **aantal schadegevallen** per element (bv. per chauffeur).  
    - De **rode stippellijn** toont de **80%-grens**.  
    - De **lichtblauwe lijn** toont het **cumulatief percentage**.  

    **Voorbeeld:**  
    - Chauffeur A = 30 schadegevallen  
    - Chauffeur B = 20 schadegevallen  
    - Chauffeur C = 10 schadegevallen  

    Samen = 60 → A heeft 50%, A+B samen = 83%.  
    👉 Dus **2 chauffeurs veroorzaken al 80% van de schadegevallen**.  

    ---

    ### 🎯 Waarom nuttig?
    - Je kan **prioriteiten stellen**: focus op de kleine groep die de meeste schade veroorzaakt.  
    - Helpt om **coaching of acties gericht** in te zetten i.p.v. verspreid.  
    """)

    # Keuze dimensie
    dim_opties = {
        "Chauffeur": "volledige naam_disp",
        "Locatie": "Locatie_disp",
        "Voertuig": "BusTram_disp",
        "Teamcoach": "teamcoach_disp",
    }
    dim_keuze = st.selectbox("Dimensie", list(dim_opties.keys()), index=0)
    kol = dim_opties[dim_keuze]

    # ===== Alleen in Pareto: sluit chauffeurs met dienstnr 9999 uit =====
    base_df = df_filtered.copy()
    if dim_keuze == "Chauffeur" and "dienstnummer" in base_df.columns:
        base_df = base_df[base_df["dienstnummer"].astype(str).str.strip() != "9999"].copy()

    # ===== Pareto berekening =====
    if kol not in base_df.columns or base_df.empty:
        st.info("Geen data om te tonen voor deze selectie.")
    else:
        counts_all = base_df[kol].value_counts()
        max_n = int(len(counts_all))
        if max_n == 0:
            st.info("Geen data om te tonen voor deze selectie.")
        else:
            totaal = int(counts_all.sum())
            cum_share = (counts_all.cumsum() / totaal)

            # 80%-punt
            mask80 = cum_share.ge(0.80)
            if mask80.any():
                idx80_label = mask80.idxmax()
                k80 = int(counts_all.index.get_loc(idx80_label))
                cum80 = float(cum_share.loc[idx80_label])
            else:
                idx80_label = counts_all.index[-1]
                k80 = max_n - 1
                cum80 = float(cum_share.iloc[-1])

            # Robuuste Top-N slider
            min_n = 1
            hard_cap = 200
            max_slider = min(hard_cap, max_n)
            default_n = min(20, max_slider)
            top_n = st.slider("Toon top N", min_value=min_n, max_value=max_slider, value=default_n, step=1)
            counts_top = counts_all.head(top_n)

            # Plot
            import plotly.graph_objects as go
            fig = go.Figure()
            fig.add_bar(
                x=counts_top.index,
                y=counts_top.values,
                name="Aantal schades",
                hovertemplate=f"{dim_keuze}: %{{x}}<br>Aantal: %{{y}}<extra></extra>",
            )
            fig.add_scatter(
                x=counts_all.index,
                y=cum_share.values,
                mode="lines+markers",
                name="Cumulatief aandeel",
                yaxis="y2",
                hovertemplate=f"{dim_keuze}: %{{x}}<br>Cumulatief: %{{y:.1%}}<extra></extra>",
            )

            # Hulplijnen en annotatie
            shapes = [
                dict(type="line", x0=0, x1=max_n, y0=0.8, y1=0.8, yref="y2",
                     line=dict(dash="dash", color="red")),
                dict(type="line", xref="x", yref="paper",
                     x0=idx80_label, x1=idx80_label, y0=0, y1=1,
                     line=dict(dash="dot", color="black")),
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

            # KPI's + tabel
            colA, colB = st.columns(2)
            with colA:
                st.metric("Aantal elementen tot 80%", k80 + 1)
            with colB:
                st.metric("Cumulatief aandeel bij markering", f"{cum80*100:.1f}%")

            df_pareto = counts_all.reset_index()
            df_pareto.columns = [dim_keuze, "Aantal"]
            df_pareto["Bijdrage %"] = (df_pareto["Aantal"] / totaal * 100).round(1)
            df_pareto["Cumulatief %"] = (df_pareto["Aantal"].cumsum() / totaal * 100).round(1)
            df_pareto["Top 80%"] = df_pareto.index <= k80

            st.markdown("#### Top 20 detail")
            st.dataframe(df_pareto.head(20))




# ========= TAB 6: Opzoeken =========
with tab6:
    st.subheader("🔎 Opzoeken op personeelsnummer")

    zoek = st.text_input("Personeelsnummer (dienstnummer)", placeholder="bv. 41092")

    # Normaliseer invoer -> alleen cijfers
    dn_in = re.findall(r"\d+", str(zoek))
    dn_in = dn_in[0] if dn_in else ""

    if not dn_in:
        st.info("Geef een personeelsnummer in om resultaten te zien.")
    else:
        if "dienstnummer" not in df.columns:
            st.error("Kolom 'dienstnummer' ontbreekt in de data.")
        else:
            res = df[df["dienstnummer"].astype(str).str.strip() == dn_in].copy()

            if res.empty:
                st.warning(f"Geen resultaten gevonden voor personeelsnr **{dn_in}**.")
            else:
                # Haal naam & teamcoach (eerste waarde uit res)
                naam_chauffeur = res["volledige naam_disp"].iloc[0]
                naam_teamcoach = res["teamcoach_disp"].iloc[0] if "teamcoach_disp" in res.columns else "onbekend"

                st.markdown(f"**👤 Chauffeur:** {naam_chauffeur}")
                st.markdown(f"**🧑‍💼 Teamcoach:** {naam_teamcoach}")
                st.markdown("---")

                st.metric("Aantal schadegevallen", len(res))

                # Resultaten tabel
                heeft_link = "Link" in res.columns
                res["URL"] = res["Link"].apply(extract_url) if heeft_link else None

                toon_kol = ["Datum", "Locatie_disp"]
                if heeft_link:
                    toon_kol.append("URL")

                res = res.sort_values("Datum", ascending=False)

                if heeft_link:
                    st.dataframe(
                        res[toon_kol],
                        column_config={
                            "Datum": st.column_config.DateColumn("Datum", format="DD-MM-YYYY"),
                            "Locatie_disp": st.column_config.TextColumn("Locatie"),
                            "URL": st.column_config.LinkColumn("Link", display_text="🔗 openen")
                        },
                        use_container_width=True,
                    )
                else:
                    st.dataframe(
                        res[toon_kol],
                        column_config={
                            "Datum": st.column_config.DateColumn("Datum", format="DD-MM-YYYY"),
                            "Locatie_disp": st.column_config.TextColumn("Locatie"),
                        },
                        use_container_width=True,
                    )



