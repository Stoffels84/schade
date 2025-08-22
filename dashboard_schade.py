import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import tempfile
import plotly.graph_objects as go
import hashlib
from datetime import datetime
import os
import re

# =====================================
#            INSTELLINGEN
# =====================================
LOGIN_ACTIEF = False  # Zet True om login te activeren
plt.rcParams["figure.dpi"] = 150
st.set_page_config(page_title="Schadegevallen Dashboard", layout="wide")

# =====================================
#            HELPERS (SNEL)
# =====================================

def hash_wachtwoord(wachtwoord: str) -> str:
    return hashlib.sha256(str(wachtwoord).encode()).hexdigest()

# Klein compat-decor voor Streamlit 1.41+ fragments; anders no-op
try:
    fragment = st.fragment
except AttributeError:
    def fragment(func):
        return func

HYPERLINK_RE = re.compile(r'HYPERLINK\(\s*"([^"]+)"', re.IGNORECASE)

def extract_url(x) -> str | None:
    if pd.isna(x):
        return None
    s = str(x).strip()
    if s.startswith(("http://", "https://")):
        return s
    m = HYPERLINK_RE.search(s)
    return m.group(1) if m else None

@st.cache_data(show_spinner=False)
def _parse_excel_dates(series: pd.Series) -> pd.Series:
    d1 = pd.to_datetime(series, errors="coerce", dayfirst=True)
    need_retry = d1.isna()
    if need_retry.any():
        d2 = pd.to_datetime(series[need_retry], errors="coerce", dayfirst=False)
        d1.loc[need_retry] = d2
    return d1

@st.cache_data(show_spinner=False)
def safe_series(s: pd.Series) -> pd.Series:
    s = s.astype("string")
    s = s.fillna("").str.strip()
    s = s.mask(s.str.lower().isin({"nan", "none", "<na>", ""}), "onbekend")
    return s

@st.cache_data(show_spinner=False, max_entries=4)
def lees_coachingslijst(pad: str = "Coachingslijst.xlsx"):
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
                kol = k
                break
        if kol is None:
            return set()
        return set(
            dfc[kol].astype(str).str.extract(r"(\d+)", expand=False).dropna().str.strip().tolist()
        )

    s_geel = vind_sheet(xls, "voltooide coachings")
    s_blauw = vind_sheet(xls, "coaching")
    if s_geel:
        ids_geel = haal_ids(s_geel)
    if s_blauw:
        ids_blauw = haal_ids(s_blauw)

    return ids_geel, ids_blauw, None

# ---------- Data laden (snel: Parquet fallback) ----------
@st.cache_data(show_spinner=False, max_entries=2)
def load_raw_data() -> pd.DataFrame:
    # Probeer supersnel Parquet; val terug op Excel
    if os.path.exists("schade.parquet"):
        try:
            return pd.read_parquet("schade.parquet")
        except Exception:
            pass
    # Excel fallback (alleen nodigde kolommen kunnen extra versnellen)
    try:
        return pd.read_excel("schade met macro.xlsm", sheet_name="BRON", engine="openpyxl")
    except FileNotFoundError:
        st.error("Bestand niet gevonden: schade met macro.xlsm")
        st.stop()
    except Exception as e:
        st.error(f"Kon 'schade met macro.xlsm' niet lezen: {e}")
        st.stop()

@st.cache_data(show_spinner=False, max_entries=2)
def load_users() -> pd.DataFrame:
    try:
        dfu = pd.read_excel("chauffeurs.xlsx")
    except FileNotFoundError:
        st.error("Bestand niet gevonden: chauffeurs.xlsx")
        st.stop()
    except Exception as e:
        st.error(f"Kon 'chauffeurs.xlsx' niet lezen: {e}")
        st.stop()
    return dfu

@st.cache_data(show_spinner=False, max_entries=2)
def prepare_df(raw_in: pd.DataFrame) -> pd.DataFrame:
    raw = raw_in.copy()
    raw.columns = raw.columns.str.strip()
    if "Datum" not in raw.columns:
        st.error("Kolom 'Datum' ontbreekt in de data.")
        st.stop()

    raw["Datum"] = _parse_excel_dates(raw["Datum"])

    # Normaliseer strings
    for col in ["volledige naam", "teamcoach", "Locatie", "Bus/ Tram", "Link"]:
        if col in raw.columns:
            raw[col] = raw[col].astype("string").str.strip()

    df = raw[raw["Datum"].notna()].copy()

    # Display kolommen
    df["volledige naam_disp"] = safe_series(df.get("volledige naam", pd.Series(index=df.index)))
    df["teamcoach_disp"] = safe_series(df.get("teamcoach", pd.Series(index=df.index)))
    df["Locatie_disp"] = safe_series(df.get("Locatie", pd.Series(index=df.index)))
    df["BusTram_disp"] = safe_series(df.get("Bus/ Tram", pd.Series(index=df.index)))

    # Dienstnummer + kwartalen
    dn = df.get("volledige naam", df["volledige naam_disp"]).astype(str).str.extract(r"^(\d+)", expand=False)
    df["dienstnummer"] = dn.astype("string").str.strip()
    df["KwartaalP"] = df["Datum"].dt.to_period("Q")
    df["Kwartaal"] = df["KwartaalP"].astype(str)

    # Categorical voor sneller counts/groupby
    for c in ["volledige naam_disp", "teamcoach_disp", "Locatie_disp", "BusTram_disp", "Kwartaal"]:
        if c in df.columns:
            df[c] = df[c].astype("category")

    return df

# ---------- Snelle Pareto helpers ----------
@st.cache_data(show_spinner=False)
def pareto_counts(series: pd.Series):
    counts = series.value_counts()
    totaal = int(counts.sum()) if len(counts) else 0
    cum = counts.cumsum() / totaal if totaal else counts
    return counts, totaal, cum

# ---------- UI helper: één snelle tabel i.p.v. veel markdown ----------
def toon_tabel(df_in: pd.DataFrame, kol_volgorde: list[str], link_kol: str = "Link"):
    if df_in.empty:
        st.caption("Geen rijen binnen de huidige filters.")
        return
    dfv = df_in.copy()
    if "Datum" in dfv.columns:
        dfv = dfv.sort_values("Datum")
    cfg = {}
    kol = [k for k in kol_volgorde if k in dfv.columns]
    if link_kol in dfv.columns:
        dfv["URL"] = dfv[link_kol].map(extract_url)
        kol = kol + ["URL"]
        cfg["URL"] = st.column_config.LinkColumn("Link", display_text="🔗 openen")
    if "Datum" in dfv.columns:
        cfg["Datum"] = st.column_config.DateColumn("Datum", format="DD-MM-YYYY")
    st.dataframe(dfv[kol], column_config=cfg, use_container_width=True)

# =====================================
#             LOGIN (optioneel)
# =====================================
gebruikers_df = load_users()
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
    rol = "teamcoach"
    naam = "demo"
else:
    ingelogde_info = gebruikers_df.loc[gebruikers_df["gebruikersnaam"] == st.session_state.username].iloc[0]
    rol = str(ingelogde_info.get("rol", "teamcoach")).strip()
    if rol == "chauffeur":
        naam = str(ingelogde_info.get("dienstnummer", ingelogde_info["gebruikersnaam"]))
    else:
        naam = str(ingelogde_info["gebruikersnaam"]).strip()

# =====================================
#             DATA PREP
# =====================================
raw = load_raw_data()
df = prepare_df(raw)

# Voor opties-lijsten
df_for_options = df.copy()

a, b, coach_warn = lees_coachingslijst()
gecoachte_ids, coaching_ids = a, b
if coach_warn:
    st.sidebar.warning(f"⚠️ {coach_warn}")

# Flags op df
df["gecoacht_geel"] = df["dienstnummer"].astype(str).isin(gecoachte_ids)
df["gecoacht_blauw"] = df["dienstnummer"].astype(str).isin(coaching_ids)

# Vectorized status mapping voor chauffeurs (t.o.v. set membership)
# mapping op basis van dienstnummer per 'volledige naam_disp'
naam2dn = df.dropna(subset=["volledige naam_disp"]).drop_duplicates("volledige naam_disp")[["volledige naam_disp", "dienstnummer"]].set_index("volledige naam_disp")["dienstnummer"]

# =====================================
#            TITEL & CAPTION
# =====================================
st.title("📊 Schadegevallen Dashboard — snelle versie")
st.caption("🟡 = voltooide coaching · 🔵 = in coaching (lopend)")

# =====================================
#         SIDEBAR: LOGO + FILTERS
# =====================================
qp = st.query_params  # Streamlit ≥1.32

with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", use_container_width=True)

# Opties (display-kolommen zodat 'onbekend' zichtbaar blijft)
teamcoach_options = sorted(df["teamcoach_disp"].dropna().unique().tolist())
locatie_options = sorted(df["Locatie_disp"].dropna().unique().tolist())
voertuig_options = sorted(df["BusTram_disp"].dropna().unique().tolist())
kwartaal_options = sorted(df_for_options["KwartaalP"].dropna().astype(str).unique().tolist())

with st.sidebar:
    st.header("🔍 Filters")

    ALL_COACHES = "— Alle teamcoaches —"
    teamcoach_opts_with_all = [ALL_COACHES] + teamcoach_options

    selected_teamcoaches_raw = st.multiselect(
        "Teamcoach",
        options=teamcoach_opts_with_all,
        default=[],  # leeg bij start
        help="Kies één of meer teamcoaches of selecteer '— Alle teamcoaches —'.",
    )
    if ALL_COACHES in selected_teamcoaches_raw:
        selected_teamcoaches = teamcoach_options
    else:
        selected_teamcoaches = selected_teamcoaches_raw

    selected_locaties = st.multiselect("Locatie", options=locatie_options, default=locatie_options)
    selected_voertuigen = st.multiselect("Voertuigtype", options=voertuig_options, default=voertuig_options)
    selected_kwartalen = st.multiselect("Kwartaal", options=kwartaal_options, default=kwartaal_options)

    # Datum-bereik op basis van kwartalen
    if selected_kwartalen:
        sel_periods_idx = pd.PeriodIndex(selected_kwartalen, freq="Q")
        date_from = sel_periods_idx.start_time.min().date()
        date_to = sel_periods_idx.end_time.max().date()
    else:
        date_from = df["Datum"].min().date()
        date_to = df["Datum"].max().date()

    if st.button("🔄 Reset filters"):
        qp.clear()
        st.rerun()

# Verplicht minstens één teamcoach
if not selected_teamcoaches:
    st.warning("⚠️ Kies eerst minstens één teamcoach in de filters (of selecteer ‘— Alle teamcoaches —’).")
    st.stop()

# =====================================
#            FILTERS TOEPASSEN
# =====================================
sel_periods = pd.PeriodIndex(selected_kwartalen, freq="Q") if selected_kwartalen else pd.PeriodIndex([], freq="Q")
mask = (
    df["teamcoach_disp"].isin(selected_teamcoaches)
    & df["Locatie_disp"].isin(selected_locaties)
    & df["BusTram_disp"].isin(selected_voertuigen)
    & (df["KwartaalP"].isin(sel_periods) if len(sel_periods) > 0 else True)
)
df_filtered = df[mask].copy()
mask_date = (df_filtered["Datum"].dt.date >= date_from) & (df_filtered["Datum"].dt.date <= date_to)
df_filtered = df_filtered[mask_date].copy()

if df_filtered.empty:
    st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    st.stop()

# =====================================
#          KPI + EXPORT + COACH STATUS
# =====================================
@fragment
def blok_kpi(df_f: pd.DataFrame):
    c1, c2 = st.columns([1, 1])
    c1.metric("Totaal aantal schadegevallen", len(df_f))
    c2.download_button(
        "⬇️ Download gefilterde data (CSV)",
        df_f.to_csv(index=False).encode("utf-8"),
        file_name=f"schade_filtered_{datetime.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        help="Exporteer de huidige selectie inclusief datumfilter.",
    )

blok_kpi(df_filtered)

with st.sidebar:
    st.markdown("### ℹ️ Coaching-status")
    st.write(f"🟡 Voltooide coachings: **{len(gecoachte_ids)}**")
    st.write(f"🔵 Coaching (lopend): **{len(coaching_ids)}**")

# =====================================
#                 TABS
# =====================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["👤 Chauffeur", "🧑‍💼 Teamcoach", "🚌 Voertuig", "📍 Locatie", "📈 Pareto", "🔎 Opzoeken"]
)

# ---------- TAB 1: Chauffeur ----------
with tab1:
    st.subheader("📂 Schadegevallen per chauffeur")
    chart_series = df_filtered["volledige naam_disp"].value_counts()

    if chart_series.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        plot_df = chart_series.rename_axis("chauffeur").reset_index(name="aantal").set_index("chauffeur")
        # Status vectorized via naam2dn mapping
        s_dn = plot_df.index.to_series().map(naam2dn).astype(str)
        in_geel = s_dn.isin(gecoachte_ids)
        in_blauw = s_dn.isin(coaching_ids)
        status = pd.Series("Geen", index=plot_df.index)
        status[in_geel & ~in_blauw] = "Voltooid"
        status[~in_geel & in_blauw] = "Coaching"
        status[in_geel & in_blauw] = "Beide"
        plot_df["status"] = status
        plot_df["badge"] = plot_df["status"].map({"Voltooid": "🟡 ", "Coaching": "🔵 ", "Beide": "🟡🔵 ", "Geen": ""})

        # KPI's
        totaal_chauffeurs_auto = int(plot_df.index.nunique())
        totaal_schades = int(plot_df["aantal"].sum())
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Aantal chauffeurs (met schade)", totaal_chauffeurs_auto)
            handmatig_aantal = st.number_input(
                "Handmatig aantal chauffeurs",
                min_value=1,
                value=max(1, totaal_chauffeurs_auto),
                step=1,
                help="Vul hier het aantal chauffeurs in om het gemiddelde te herberekenen.",
            )
        gem_handmatig = round(totaal_schades / handmatig_aantal, 2) if handmatig_aantal else 0.0
        col2.metric("Gemiddeld aantal schades", gem_handmatig)
        col3.metric("Totaal aantal schades", totaal_schades)
        if handmatig_aantal != totaal_chauffeurs_auto:
            st.caption(f"ℹ️ Handmatige invoer actief: {handmatig_aantal} i.p.v. {totaal_chauffeurs_auto}.")

        # Accordeons per interval (minder items: slider)
        step = 5
        max_val = int(plot_df["aantal"].max()) if not plot_df.empty else 0
        edges = [0, step] if max_val <= 0 else list(range(0, max_val + step, step))
        if edges and edges[-1] < max_val:
            edges.append(edges[-1] + step)
        if edges:
            plot_df = plot_df.copy()
            plot_df["interval"] = pd.cut(plot_df["aantal"], bins=edges, right=True, include_lowest=True)

            max_expanders = st.slider("Max expanders tonen", 3, 30, 10)
            shown = 0
            for interval, groep in plot_df.groupby("interval", sort=False):
                if shown >= max_expanders:
                    break
                if groep.empty or pd.isna(interval):
                    continue
                left, right = int(interval.left), int(interval.right)
                low = max(1, left + 1)
                titel = f"{low} t/m {right} schades ({len(groep)} chauffeurs)"
                with st.expander(titel):
                    # Subset: alle rijen van deze groep chauffeurs
                    subset = df_filtered[df_filtered["volledige naam_disp"].isin(groep.index)]

                    # 🔢 Nieuw: overzicht totaal aantal schades per chauffeur
                    per_chauffeur = (
                        subset.groupby("volledige naam_disp").size().sort_values(ascending=False)
                    )
                    st.markdown("**Overzicht per chauffeur (totaal aantal schades):**")
                    st.dataframe(
                        per_chauffeur.reset_index().rename(
                            columns={"volledige naam_disp": "Chauffeur", 0: "Aantal schades"}
                        ),
                        use_container_width=True,
                    )
                        ["Datum", "volledige naam_disp", "BusTram_disp", "Locatie_disp", "teamcoach_disp"]
                shown += 1

# ---------- TAB 2: Teamcoach ----------
with tab2:
    st.subheader("Aantal schadegevallen per teamcoach")
    counts = df_filtered["teamcoach_disp"].value_counts()
    if counts.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(counts) * 0.3 + 1)))
        counts.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen")
        ax.set_ylabel("Teamcoach")
        ax.set_title("Schadegevallen per teamcoach")
        st.pyplot(fig)
        plt.close(fig)

        st.subheader("📂 Detail (filterbaar)")
        coach_filter = st.selectbox("Teamcoach", ["(alle)"] + counts.index.tolist())
        kol = ["Datum", "volledige naam_disp", "BusTram_disp", "Locatie_disp", "teamcoach_disp", "Link"]
        df_coach = df_filtered[kol].copy()
        if coach_filter != "(alle)":
            df_coach = df_coach[df_coach["teamcoach_disp"] == coach_filter]
        toon_tabel(df_coach, ["Datum", "volledige naam_disp", "BusTram_disp", "Locatie_disp", "teamcoach_disp"]) 

# ---------- TAB 3: Voertuig ----------
with tab3:
    st.subheader("📈 Schadegevallen per maand per voertuigtype")
    df_per_maand = df_filtered[df_filtered["Datum"].notna()].copy()

    maanden_nl = {
        1: "januari", 2: "februari", 3: "maart", 4: "april", 5: "mei", 6: "juni",
        7: "juli", 8: "augustus", 9: "september", 10: "oktober", 11: "november", 12: "december",
    }
    maand_volgorde = [
        "januari", "februari", "maart", "april", "mei", "juni",
        "juli", "augustus", "september", "oktober", "november", "december",
    ]

    if not df_per_maand.empty:
        df_per_maand["Maand"] = df_per_maand["Datum"].dt.month.map(maanden_nl).str.lower()
        voertuig_col = "BusTram_disp"
        if voertuig_col not in df_per_maand.columns:
            st.warning("⚠️ Kolom voor voertuigtype niet gevonden.")
        else:
            groep = df_per_maand.groupby(["Maand", voertuig_col]).size().unstack(fill_value=0)
            groep = groep.reindex(maand_volgorde).fillna(0)

            fig2, ax2 = plt.subplots(figsize=(10, 4))
            groep.plot(ax=ax2, marker="o")
            ax2.set_xlabel("Maand")
            ax2.set_ylabel("Aantal schadegevallen")
            ax2.set_title("Lijngrafiek per maand per voertuigtype")
            ax2.legend(title="Voertuig")
            st.pyplot(fig2)
            plt.close(fig2)
    else:
        st.info("ℹ️ Geen geldige datums binnen de huidige filters om een maandoverzicht te tonen.")

    st.subheader("Aantal schadegevallen per type voertuig")
    voertuig_col = "BusTram_disp" if "BusTram_disp" in df_filtered.columns else None
    if voertuig_col is None:
        st.warning("⚠️ Kolom voor voertuigtype niet gevonden.")
    else:
        chart_data = df_filtered[voertuig_col].value_counts()
        if chart_data.empty:
            st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
        else:
            fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
            chart_data.sort_values().plot(kind="barh", ax=ax)
            ax.set_xlabel("Aantal schadegevallen")
            ax.set_ylabel("Voertuigtype")
            ax.set_title("Schadegevallen per type voertuig")
            st.pyplot(fig)
            plt.close(fig)

            st.subheader("📂 Detail (filterbaar)")
            vh_filter = st.selectbox("Voertuigtype", ["(alle)"] + chart_data.index.tolist())
            kol = ["Datum", "volledige naam_disp", "BusTram_disp", "Locatie_disp", "teamcoach_disp", "Link"]
            df_vh = df_filtered[kol].copy()
            if vh_filter != "(alle)":
                df_vh = df_vh[df_vh["BusTram_disp"] == vh_filter]
            toon_tabel(df_vh, ["Datum", "volledige naam_disp", "BusTram_disp", "Locatie_disp", "teamcoach_disp"]) 

# ---------- TAB 4: Locatie ----------
with tab4:
    st.subheader("Aantal schadegevallen per locatie")
    locatie_col = "Locatie_disp" if "Locatie_disp" in df_filtered.columns else None
    if locatie_col is None:
        st.warning("⚠️ Kolom voor locatie niet gevonden.")
    else:
        chart_data = df_filtered[locatie_col].value_counts()
        if chart_data.empty:
            st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
        else:
            fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
            chart_data.sort_values().plot(kind="barh", ax=ax)
            ax.set_xlabel("Aantal schadegevallen")
            ax.set_ylabel("Locatie")
            ax.set_title("Schadegevallen per locatie")
            st.pyplot(fig)
            plt.close(fig)

            st.subheader("📂 Detail (filterbaar)")
            loc_filter = st.selectbox("Locatie", ["(alle)"] + chart_data.index.tolist())
            kol = ["Datum", "volledige naam_disp", "BusTram_disp", "Locatie_disp", "teamcoach_disp", "Link"]
            df_loc = df_filtered[kol].copy()
            if loc_filter != "(alle)":
                df_loc = df_loc[df_loc["Locatie_disp"] == loc_filter]
            toon_tabel(df_loc, ["Datum", "volledige naam_disp", "BusTram_disp", "Locatie_disp", "teamcoach_disp"]) 

# ---------- TAB 5: Pareto ----------
with tab5:
    st.subheader("📈 Pareto-analyse (80/20)")
    st.markdown(
        """
        ### ℹ️ Wat is Pareto?
        De **Pareto-analyse** is gebaseerd op het **80/20-principe**: 80% van de gevolgen komt vaak uit 20% van de oorzaken.
        In dit dashboard kun je kiezen tussen **Chauffeur**, **Locatie**, **Voertuig** en **Teamcoach**.
        """
    )

    dim_opties = {
        "Chauffeur": "volledige naam_disp",
        "Locatie": "Locatie_disp",
        "Voertuig": "BusTram_disp",
        "Teamcoach": "teamcoach_disp",
    }
    dim_keuze = st.selectbox("Dimensie", list(dim_opties.keys()), index=0)
    kol = dim_opties[dim_keuze]

    base_df = df_filtered.copy()
    if dim_keuze == "Chauffeur" and "dienstnummer" in base_df.columns:
        base_df = base_df[base_df["dienstnummer"].astype(str).str.strip() != "9999"].copy()

    if kol not in base_df.columns or base_df.empty:
        st.info("Geen data om te tonen voor deze selectie.")
    else:
        counts_all, totaal, cum_share = pareto_counts(base_df[kol])
        if totaal == 0:
            st.info("Geen data om te tonen voor deze selectie.")
        else:
            max_n = int(len(counts_all))
            mask80 = cum_share.ge(0.80)
            if mask80.any():
                idx80_label = mask80.idxmax()
                k80 = int(counts_all.index.get_loc(idx80_label))
                cum80 = float(cum_share.loc[idx80_label])
            else:
                idx80_label = counts_all.index[-1]
                k80 = max_n - 1
                cum80 = float(cum_share.iloc[-1])

            min_n, hard_cap = 1, 200
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
                x=counts_all.index,
                y=cum_share.values,
                mode="lines+markers",
                name="Cumulatief aandeel",
                yaxis="y2",
                hovertemplate=f"{dim_keuze}: %{{x}}<br>Cumulatief: %{{y:.1%}}<extra></extra>",
            )

            shapes = [
                dict(type="line", x0=0, x1=max_n, y0=0.8, y1=0.8, yref="y2", line=dict(dash="dash", color="red")),
                dict(type="line", xref="x", yref="paper", x0=idx80_label, x1=idx80_label, y0=0, y1=1, line=dict(dash="dot", color="black")),
            ]
            fig.update_layout(
                title=f"Pareto — {dim_keuze} (80% hulplijn)",
                xaxis=dict(tickangle=-45, showticklabels=False),
                yaxis=dict(title="Aantal schades"),
                yaxis2=dict(title="Cumulatief aandeel", overlaying="y", side="right", range=[0, 1.05]),
                shapes=shapes,
                annotations=[
                    dict(x=idx80_label, y=cum80, xref="x", yref="y2", text=f"80% bij #{k80+1}", showarrow=True, arrowhead=2, ax=0, ay=-30, bgcolor="white"),
                ],
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, use_container_width=True)

            colA, colB = st.columns(2)
            colA.metric("Aantal elementen tot 80%", k80 + 1)
            colB.metric("Cumulatief aandeel bij markering", f"{cum80*100:.1f}%")

            df_pareto = counts_all.reset_index()
            df_pareto.columns = [dim_keuze, "Aantal"]
            df_pareto["Bijdrage %"] = (df_pareto["Aantal"] / totaal * 100).round(1)
            df_pareto["Cumulatief %"] = (df_pareto["Aantal"].cumsum() / totaal * 100).round(1)
            df_pareto["Top 80%"] = df_pareto.index <= k80
            st.markdown("#### Top 20 detail")
            st.dataframe(df_pareto.head(20), use_container_width=True)

# ---------- TAB 6: Opzoeken ----------
with tab6:
    st.subheader("🔎 Opzoeken op personeelsnummer")
    zoek = st.text_input("Personeelsnummer (dienstnummer)", placeholder="bv. 41092")
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
                naam_chauffeur = res["volledige naam_disp"].iloc[0]
                naam_teamcoach = res["teamcoach_disp"].iloc[0] if "teamcoach_disp" in res.columns else "onbekend"
                st.markdown(f"**👤 Chauffeur:** {naam_chauffeur}")
                st.markdown(f"**🧑‍💼 Teamcoach:** {naam_teamcoach}")
                st.markdown("---")
                st.metric("Aantal schadegevallen", len(res))

                heeft_link = "Link" in res.columns
                res = res.sort_values("Datum", ascending=False)
                res["URL"] = res["Link"].map(extract_url) if heeft_link else None
                toon_kol = ["Datum", "Locatie_disp"] + (["URL"] if heeft_link else [])
                cfg = {"Datum": st.column_config.DateColumn("Datum", format="DD-MM-YYYY")}
                if heeft_link:
                    cfg["URL"] = st.column_config.LinkColumn("Link", display_text="🔗 openen")
                st.dataframe(res[toon_kol], column_config=cfg, use_container_width=True)

# =====================================
#        PDF EXPORT (per teamcoach)
# =====================================
st.markdown("---")
st.sidebar.subheader("📄 PDF Export per teamcoach")
pdf_coach = st.sidebar.selectbox("Kies teamcoach voor export", teamcoach_options)

if st.sidebar.button("Genereer PDF"):
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
        nm = "onbekend" if pd.isna(nm) else str(nm)
        elements.append(Paragraph(f"- {nm}: {count}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    aantal_per_locatie = schade_pdf["Locatie_disp"].value_counts()
    elements.append(Paragraph("📍 Aantal schadegevallen per locatie:", styles["Heading2"]))
    for loc, count in aantal_per_locatie.items():
        loc = "onbekend" if pd.isna(loc) else str(loc)
        elements.append(Paragraph(f"- {loc}: {count}", styles["Normal"]))
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
        nm = row["volledige naam_disp"]
        voertuig = row["BusTram_disp"]
        locatie = row["Locatie_disp"]
        rij = [datum, nm, voertuig, locatie]
        if heeft_link:
            link = extract_url(row.get("Link"))
            rij.append(link if link else "-")
        tabel_data.append(rij)

    if len(tabel_data) > 1:
        colw = [60, 150, 70, 130] + ([120] if heeft_link else [])
        tbl = Table(tabel_data, repeatRows=1, colWidths=colw)
        tbl.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                ]
            )
        )
        elements.append(tbl)

    doc.build(elements)
    buffer.seek(0)
    bestandsnaam = f"schade_{pdf_coach.replace(' ', '_')}_{datetime.today().strftime('%Y%m%d')}.pdf"
    st.sidebar.download_button(
        label="📥 Download PDF",
        data=buffer,
        file_name=bestandsnaam,
        mime="application/pdf",
    )

    if chart_path and os.path.exists(chart_path):
        try:
            os.remove(chart_path)
        except Exception:
            pass
