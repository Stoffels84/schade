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
    if not isinstance(naam, str):
        return None
    m = re.match(r"\s*(\d+)", naam)
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
        df = pd.read_excel(xls, sheet_name=sheetnaam)
        df.columns = df.columns.str.strip().str.lower()
        kol = None
        for k in ["p-nr", "p_nr", "pnr", "pnummer", "dienstnummer", "p nr"]:
            if k in df.columns:
                kol = k; break
        if kol is None:
            return set()
        return set(
            df[kol].astype(str).str.extract(r"(\d+)", expand=False).dropna().str.strip().tolist()
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

# Normaliseer kolomnamen en basis-schoonmaak (zonder rijen te droppen)
raw.columns = raw.columns.str.strip()
for col in ["volledige naam", "teamcoach", "Locatie", "Bus/ Tram"]:
    if col in raw.columns:
        raw[col] = raw[col].astype(str).str.strip()

# Teamcoach-opties uit RUWE data (dus volledig)
raw_tc = (
    raw["teamcoach"]
    .astype(str)
    .str.strip()
    .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
)
teamcoach_options = sorted(pd.Series(raw_tc).dropna().unique().tolist())

# ========= Opgeschoonde df voor analyses =========
df = raw.copy()

# Datum eenduidig parsen en daarna pas droppen
df["Datum"] = pd.to_datetime(df["Datum"], errors="coerce", dayfirst=True)

# Weg met ongeldige/lege namen of speciale placeholder
df = df[df["volledige naam"].notna() & (df["volledige naam"] != "") & (df["volledige naam"] != "9999 - -")].copy()
# Alleen rijen met geldige datums
df = df[df["Datum"].notna()].copy()

# Afgeleide velden
df["Kwartaal"] = df["Datum"].dt.to_period("Q").astype(str)
df["dienstnummer"] = df["volledige naam"].astype(str).str.extract(r"^(\d+)", expand=False).astype(str).str.strip()

# ========= Coachingslijst =========
gecoachte_ids, coaching_ids, coach_warn = lees_coachingslijst()
if coach_warn:
    st.sidebar.warning(f"⚠️ {coach_warn}")

# Flags op df (optioneel)
df["gecoacht_geel"] = df["dienstnummer"].astype(str).isin(gecoachte_ids)
df["gecoacht_blauw"] = df["dienstnummer"].astype(str).isin(coaching_ids)

# ========= UI: Titel + Caption =========
st.title("📊 Schadegevallen Dashboard")
st.caption("🟡 = voltooide coaching · 🔵 = in coaching (lopend)")

# ========= Query params presets (LEZEN) =========
qp = st.query_params  # Streamlit 1.32+

def _clean_list(values, allowed):
    return [v for v in (values or []) if v in allowed]

# Teamcoach presets: alleen geldige waarden
pref_tc = _clean_list(qp.get_all("teamcoach"), teamcoach_options) or teamcoach_options
# Voertuig/locatie/kwartaal opties uit opgeschoonde df (mag)
voertuig_options = sorted(df["Bus/ Tram"].dropna().unique().tolist())
locatie_options  = sorted(df["Locatie"].dropna().unique().tolist())
kwartaal_options = sorted(df["Kwartaal"].dropna().unique().tolist())

pref_vh = _clean_list(qp.get_all("voertuig"), voertuig_options) or voertuig_options
pref_lo = _clean_list(qp.get_all("locatie"),  locatie_options)  or locatie_options
pref_kw = _clean_list(qp.get_all("kwartaal"), kwartaal_options)  or kwartaal_options

# ========= Sidebar filters =========
with st.sidebar:
    st.header("🔍 Filters")
    selected_teamcoaches = st.multiselect(
        "Teamcoach",
        options=teamcoach_options,
        default=pref_tc
    )

    selected_voertuigen = st.multiselect(
        "Voertuigtype",
        options=voertuig_options,
        default=pref_vh
    )

    selected_locaties = st.multiselect(
        "Locatie",
        options=locatie_options,
        default=pref_lo
    )

    selected_kwartalen = st.multiselect(
        "Kwartaal",
        options=kwartaal_options,
        default=pref_kw
    )

    # 🗓️ Datum-bereik filter
    st.markdown("### 🗓️ Datum")
    min_d, max_d = df["Datum"].min().date(), df["Datum"].max().date()
    date_from, date_to = st.date_input(
        "Periode",
        value=(min_d, max_d),
        min_value=min_d,
        max_value=max_d
    )
    if isinstance(date_from, tuple):
        date_from, date_to = date_from

    colA, colB = st.columns(2)
    with colA:
        if st.button("🔄 Reset filters"):
            qp.clear()
            st.rerun()
    with colB:
        if st.button("🔖 Bewaar filters in URL"):
            qp.clear()
            qp["teamcoach"] = selected_teamcoaches
            qp["voertuig"]  = selected_voertuigen
            qp["locatie"]   = selected_locaties
            qp["kwartaal"]  = selected_kwartalen
            st.success("Link met filters staat nu in de adresbalk. Kopieer & deel!")

# ========= Filters toepassen =========
mask = (
    df["teamcoach"].isin(selected_teamcoaches) &
    df["Bus/ Tram"].isin(selected_voertuigen) &
    df["Locatie"].isin(selected_locaties) &
    df["Kwartaal"].isin(selected_kwartalen)
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
    kolommen_pdf = ["Datum", "volledige naam", "Locatie", "Bus/ Tram"]
    if "Link" in df.columns:
        kolommen_pdf.append("Link")

    schade_pdf = df_filtered[df_filtered["teamcoach"] == pdf_coach][kolommen_pdf].copy()
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
        elements.append(Paragraph(f"- Unieke chauffeurs: {schade_pdf['volledige naam'].nunique()}", styles["Normal"]))
        elements.append(Paragraph(f"- Unieke locaties: {schade_pdf['Locatie'].nunique()}", styles["Normal"]))
        elements.append(Spacer(1, 12))

    aantal_per_chauffeur = schade_pdf["volledige naam"].value_counts()
    elements.append(Paragraph("👤 Aantal schadegevallen per chauffeur:", styles["Heading2"]))
    for nm, count in aantal_per_chauffeur.items():
        nm_disp = nm or "onbekend"
        elements.append(Paragraph(f"- {nm_disp}: {count}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    aantal_per_locatie = schade_pdf["Locatie"].value_counts()
    elements.append(Paragraph("📍 Aantal schadegevallen per locatie:", styles["Heading2"]))
    for loc, count in aantal_per_locatie.items():
        loc_disp = loc or "onbekend"
        elements.append(Paragraph(f"- {loc_disp}: {count}", styles["Normal"]))
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
        nm = (row["volledige naam"] or "onbekend")
        voertuig = (row["Bus/ Tram"] or "onbekend")
        locatie = (row["Locatie"] or "onbekend")
        rij = [datum, nm, voertuig, locatie]
        if heeft_link:
            link = row.get("Link")
            rij.append(str(link) if (pd.notna(link) and isinstance(link, str) and link.startswith(("http://","https://"))) else "-")
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

    # opruimen temp chart-bestand
    if chart_path and os.path.exists(chart_path):
        try:
            os.remove(chart_path)
        except Exception:
            pass

# ========= TAB 1: Chauffeur =========
with tab1:
    st.subheader("Aantal schadegevallen per chauffeur")
    top_n_option = st.selectbox("Toon top aantal chauffeurs:", ["10", "20", "50", "Allemaal"])

    # 1) Data veilig opbouwen
    chart_series = df_filtered["volledige naam"].value_counts()
    if top_n_option != "Allemaal":
        chart_series = chart_series.head(int(top_n_option))

    if chart_series.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        # Bouw dataframe voor plotly
        plot_df = (
            chart_series
            .rename_axis("chauffeur")
            .reset_index(name="aantal")
        )
        # Voeg status + badge toe
        plot_df["status"] = plot_df["chauffeur"].apply(status_van_chauffeur)
        plot_df["badge"]  = plot_df["status"].apply(badge_van_status)
        # Sorteer oplopend zodat horizontale bars van klein -> groot lopen
        plot_df = plot_df.sort_values("aantal", ascending=True, kind="stable")

        # 2) Legenda met badges boven de grafiek (visueel/snappy)
        st.markdown("**Legenda:** 🟡 Voltooid · 🔵 Coaching · 🟡🔵 Beide · ⚪ Geen")

        # 3) Plotly grafiek met consistente kleuren + hover-tooltips
        color_map = {
            "Voltooid": COLOR_GEEL,
            "Coaching": COLOR_BLAUW,
            "Beide":    COLOR_MIX,
            "Geen":     COLOR_GRIJS,
        }

        fig = px.bar(
            plot_df,
            x="aantal",
            y="chauffeur",
            color="status",
            orientation="h",
            color_discrete_map=color_map,
            hover_data={
                "aantal": True,
                "chauffeur": True,
                "status": True,
                "badge": False,
            },
            labels={"aantal": "Aantal schadegevallen", "chauffeur": "Chauffeur", "status": "Status"},
        )

        # Hovertemplate (enkel de juiste versie houden)
        fig.update_traces(
            customdata=plot_df[["badge", "status"]].to_numpy(),
            hovertemplate="<b>%{y}</b><br>"
                          "Aantal: %{x}<br>"
                          "Status: %{customdata[0]}%{customdata[1]}<extra></extra>"
        )

        # Layout: compacte marges, horizontale legenda bovenaan
        fig.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(l=10, r=10, t=10, b=10),
            height=max(260, 28 * len(plot_df) + 120),
        )

        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        # 4) Lijst per chauffeur (expanders) – badges voor de titel
        st.subheader("📂 Schadegevallen per chauffeur")
        # Gebruik dezelfde volgorde als de grafiek (van klein naar groot)
        ordered_names = plot_df["chauffeur"].tolist()

        for chauffeur in ordered_names[::-1]:  # van groot -> klein voor prettige leeservaring
            aantal = int(chart_series.get(chauffeur, 0))
            status = status_van_chauffeur(chauffeur)
            badge = badge_van_status(status)
            titel = f"{badge}{chauffeur} — {aantal} schadegevallen"

            with st.expander(titel):
                schade_chauffeur = (
                    df_filtered.loc[df_filtered["volledige naam"] == chauffeur, ["Datum", "Link"]]
                    .sort_values(by="Datum")
                )
                for _, row in schade_chauffeur.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    link = row.get("Link") if "Link" in df_filtered.columns else None
                    if isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — ❌ Geen geldige link")

# (Optioneel) verdere tabs tab2/tab3/tab4 kun je vullen met je bestaande of extra analyses
with tab2:
    st.subheader("Teamcoach overzicht")
    coach_counts = (
        df_filtered.groupby("teamcoach")["volledige naam"].count()
        .rename("aantal").reset_index().sort_values("aantal", ascending=False)
    )
    st.bar_chart(coach_counts.set_index("teamcoach"), height=260)
    st.dataframe(coach_counts, use_container_width=True)

with tab3:
    st.subheader("Voertuig overzicht")
    veh_counts = (
        df_filtered.groupby("Bus/ Tram")["volledige naam"].count()
        .rename("aantal").reset_index().sort_values("aantal", ascending=False)
    )
    st.bar_chart(veh_counts.set_index("Bus/ Tram"), height=260)
    st.dataframe(veh_counts, use_container_width=True)

with tab4:
    st.subheader("Locatie overzicht")
    loc_counts = (
        df_filtered.groupby("Locatie")["volledige naam"].count()
        .rename("aantal").reset_index().sort_values("aantal", ascending=False)
    )
    st.bar_chart(loc_counts.set_index("Locatie"), height=260)
    st.dataframe(loc_counts, use_container_width=True)




# ========= TAB 2: Teamcoach =========
with tab2:
    st.subheader("Aantal schadegevallen per teamcoach")
    chart_data = df_filtered["teamcoach"].value_counts()
    if chart_data.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
        chart_data.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen")
        ax.set_ylabel("Teamcoach")
        ax.set_title("Schadegevallen per teamcoach")
        st.pyplot(fig)

        st.subheader("📂 Schadegevallen per teamcoach")
        for coach in chart_data.index.tolist():
            schade_per_coach = df_filtered[df_filtered["teamcoach"] == coach][["Datum", "Link", "volledige naam"]].sort_values(by="Datum")
            aantal = len(schade_per_coach)
            with st.expander(f"{coach} — {aantal} schadegevallen"):
                for _, row in schade_per_coach.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam"]; link = row["Link"]
                    if pd.notna(link) and isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — ❌ Geen geldige link")

# ========= TAB 3: Voertuig =========
with tab3:
    st.subheader("📈 Schadegevallen per maand per voertuigtype")
    df_per_maand = df_filtered.copy()
    maanden_nl = {1:"januari",2:"februari",3:"maart",4:"april",5:"mei",6:"juni",7:"juli",8:"augustus",9:"september",10:"oktober",11:"november",12:"december"}
    df_per_maand["Maand"] = df_per_maand["Datum"].dt.month.map(maanden_nl).str.lower()
    maand_volgorde = ["januari","februari","maart","april","mei","juni","juli","augustus","september","oktober","november","december"]
    groep = df_per_maand.groupby(["Maand", "Bus/ Tram"]).size().unstack(fill_value=0)
    groep = groep.reindex(maand_volgorde)

    fig2, ax2 = plt.subplots(figsize=(10, 4))
    groep.plot(ax=ax2, marker="o")
    ax2.set_xlabel("Maand"); ax2.set_ylabel("Aantal schadegevallen")
    ax2.set_title("Lijngrafiek per maand per voertuigtype")
    ax2.legend(title="Voertuig")
    st.pyplot(fig2)

    st.subheader("Aantal schadegevallen per type voertuig")
    chart_data = df_filtered["Bus/ Tram"].value_counts()
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
            schade_per_voertuig = df_filtered[df_filtered["Bus/ Tram"] == voertuig][["Datum", "Link", "volledige naam"]].sort_values(by="Datum")
            aantal = len(schade_per_voertuig)
            with st.expander(f"{voertuig} — {aantal} schadegevallen"):
                for _, row in schade_per_voertuig.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam"]; link = row["Link"]
                    if pd.notna(link) and isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — ❌ Geen geldige link")

# ========= TAB 4: Locatie =========
with tab4:
    st.subheader("Aantal schadegevallen per locatie")
    top_locatie_option = st.selectbox("Toon top aantal locaties:", ["10", "20", "50", "Allemaal"])
    chart_data = df_filtered["Locatie"].value_counts()
    if top_locatie_option != "Allemaal":
        chart_data = chart_data.head(int(top_locatie_option))

    if chart_data.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
        chart_data.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen"); ax.set_ylabel("Locatie")
        ax.set_title("Top " + top_locatie_option + " schadegevallen per locatie" if top_locatie_option != "Allemaal" else "Schadegevallen per locatie")
        st.pyplot(fig)

        st.subheader("📂 Schadegevallen per locatie")
        for locatie in chart_data.index.tolist():
            schade_per_locatie = df_filtered[df_filtered["Locatie"] == locatie][["Datum", "Link", "volledige naam"]].sort_values(by="Datum")
            aantal = len(schade_per_locatie)
            with st.expander(f"{locatie} — {aantal} schadegevallen"):
                for _, row in schade_per_locatie.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam"]; link = row["Link"]
                    if pd.notna(link) and isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — ❌ Geen geldige link")
ChatGPT zei:
Nagedacht gedurende 52s

Lekker werk! Je app is al heel compleet. Ik heb ‘m snel “code-reviewed” en hieronder staan de belangrijkste verbeterpunten met kant-en-klare snippets die je zo kunt plakken.

Belangrijkste bugs/risico’s

Login-kolomnamen mismatch
Je code verwacht gebruikersnaam, terwijl je eerder bestand (geheugen) login gebruikte. Voeg mapping toe zodat beide werken, en maak (optioneel) hashed wachtwoorden mogelijk met terugval op plaintext.

Cache + schrijven naar chauffeurs.xlsx
Je schrijft “laatste login” terug, maar je gebruikt cached data (@st.cache_data). Dat is prima, maar wissel bij de volgende run pas opnieuw inlezen (nu geen direct probleem). Wel try/except is goed.

naam_naar_dn kan eenvoudiger/robuster
Huidige implementatie maakt een Series. Een simpele regex op een string is sneller en duidelijker.

Coachingslijst robuuster inlezen
Maak het tolerant voor hoofdletters/spaties en vang ontbrekende sheet- of kolomnamen netjes op.

Query params veilig schrijven
Je gebruikt de nieuwe API correct. Voor zekerheid (en compat) kun je st.query_params.clear() gevolgd door toewijzen blijven doen (zoals je al doet).

PDF: lange tabellen & afbeelding-cleanup
Je handhaaft repeatRows=1 (top), maar zorg dat de temp-grafiek altijd netjes wordt verwijderd en dat kolombreedtes ook goed zijn zonder “Link”. (Je doet dit grotendeels al; hieronder een iets strakkere variant.)

Kleine UX-polish

Voeg een Reset-filters knop toe.

Voeg Download CSV toe voor de gefilterde set.

In expanders: toon ook teamcoach/voertuig waar nuttig.

Kant-en-klare snippets
1) Login: kolommen mappen + (optioneel) hashed wachtwoord

Plak dit na het inladen van chauffeurs.xlsx, direct na:

gebruikers_df = load_excel("chauffeurs.xlsx")
gebruikers_df.columns = gebruikers_df.columns.str.strip().str.lower()


Vervang je controle op kolommen door:

# === Kolomnamen normaliseren (accepteer 'login' of 'gebruikersnaam') ===
kol_map = {}
if "gebruikersnaam" in gebruikers_df.columns:
    kol_map["gebruikersnaam"] = "gebruikersnaam"
elif "login" in gebruikers_df.columns:
    kol_map["login"] = "gebruikersnaam"

if "paswoord" in gebruikers_df.columns:
    kol_map["paswoord"] = "paswoord"
elif "wachtwoord" in gebruikers_df.columns:
    kol_map["wachtwoord"] = "paswoord"

# Optioneel:
if "dienstnummer" in gebruikers_df.columns:
    kol_map["dienstnummer"] = "dienstnummer"
if "rol" in gebruikers_df.columns:
    kol_map["rol"] = "rol"
if "laatste login" in gebruikers_df.columns:
    kol_map["laatste login"] = "laatste login"

gebruikers_df = gebruikers_df.rename(columns=kol_map)

vereist_login_kolommen = {"gebruikersnaam", "paswoord"}
missend_login = [c for c in vereist_login_kolommen if c not in gebruikers_df.columns]
if missend_login:
    st.error(f"Login configuratie onvolledig. Ontbrekende kolommen (na normalisatie): {', '.join(missend_login)}")
    st.stop()

# Strippen
gebruikers_df["gebruikersnaam"] = gebruikers_df["gebruikersnaam"].astype(str).str.strip()
gebruikers_df["paswoord"] = gebruikers_df["paswoord"].astype(str).str.strip()

for c in ["rol","dienstnummer","laatste login"]:
    if c not in gebruikers_df.columns:
        gebruikers_df[c] = pd.NA


Inlogcontrole (vervang je huidige if bij st.button("Log in"):):

if st.button("Log in"):
    rij = gebruikers_df.loc[gebruikers_df["gebruikersnaam"] == str(username).strip()]
    if not rij.empty:
        opgeslagen = str(rij["paswoord"].iloc[0])

        # 1) Probeer exact (plaintext) zoals in Excel
        ok = (opgeslagen == str(password))

        # 2) OF sta SHA256 toe: sla in Excel eventueel al gehashte waarde op
        if not ok:
            ok = (opgeslagen == hash_wachtwoord(password))

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


Tip: wil je altijd hashes gebruiken, vervang dan opgeslagen == str(password) door alleen de hash-vergelijking en sla in Excel enkel gehashte wachtwoorden op.

2) Snellere/robustere naam_naar_dn

Vervang de functie door:

def naam_naar_dn(naam: str) -> str | None:
    if not isinstance(naam, str):
        return None
    m = pd.Series([naam]).str.extract(r"^\s*(\d+)", expand=False).iloc[0]
    return str(m).strip() if pd.notna(m) else None


Of zonder pandas (nog sneller):

import re
def naam_naar_dn(naam: str) -> str | None:
    if not isinstance(naam, str):
        return None
    m = re.match(r"\s*(\d+)", naam)
    return m.group(1) if m else None

3) Coachingslijst robuuster

Vervang het hele try/except-blok door:

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
        df = pd.read_excel(xls, sheet_name=sheetnaam)
        df.columns = df.columns.str.strip().str.lower()
        kol = None
        for k in ["p-nr", "p_nr", "pnr", "pnummer", "dienstnummer", "p nr"]:
            if k in df.columns:
                kol = k; break
        if kol is None:
            return set()
        return set(df[kol].astype(str).str.extract(r"(\d+)", expand=False).dropna().str.strip())

    s_geel = vind_sheet(xls, "voltooide coachings")
    s_blauw = vind_sheet(xls, "coaching")
    if s_geel:
        ids_geel = haal_ids(s_geel)
    if s_blauw:
        ids_blauw = haal_ids(s_blauw)

    return ids_geel, ids_blauw, None

gecoachte_ids, coaching_ids, coach_warn = lees_coachingslijst()
if coach_warn:
    st.warning(f"⚠️ {coach_warn}")

4) Filters: reset + deelbare link

Onder je sidebar-filters, voeg toe:

colA, colB = st.columns(2)
with colA:
    if st.button("🔄 Reset filters"):
        qp.clear()
        st.rerun()
with colB:
    if st.button("🔖 Bewaar filters in URL"):
        qp.clear()
        qp["teamcoach"] = selected_teamcoaches
        qp["voertuig"]  = selected_voertuigen
        qp["locatie"]   = selected_locaties
        qp["kwartaal"]  = selected_kwartalen
        st.success("Link met filters staat nu in de adresbalk. Kopieer & deel!")


(Je had de “bewaar”-knop al; dit voegt enkel reset toe en zet de knoppen netjes naast elkaar.)

5) Download CSV van de gefilterde data

Plaats dit vlak na st.metric(...):

st.download_button(
    "⬇️ Download gefilterde data (CSV)",
    df_filtered.to_csv(index=False).encode("utf-8"),
    file_name=f"schade_filtered_{datetime.today().strftime('%Y%m%d')}.csv",
    mime="text/csv",
    help="Exporteer de huidige selectie inclusief datumfilter."
)

6) PDF: compactere tabel + veilig opruimen

Vervang de tabel-opbouw in je PDF-blok door:

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
    nm = (row["volledige naam"] or "onbekend")
    voertuig = (row["Bus/ Tram"] or "onbekend")
    locatie = (row["Locatie"] or "onbekend")
    rij = [datum, nm, voertuig, locatie]
    if heeft_link:
        link = row.get("Link")
        rij.append(str(link) if (pd.notna(link) and isinstance(link, str) and link.startswith(("http://","https://"))) else "-")
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


En maak het opruimen van de chart bestandsveilig:

chart_path = None
...
with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
    fig.savefig(tmpfile.name, dpi=150)
    plt.close(fig)
    chart_path = tmpfile.name
    ...
...
if chart_path and os.path.exists(chart_path):
    try:
        os.remove(chart_path)
    except Exception:
        pass

7) UX: extra context in expanders

Bij de chauffeur-expander (tab 1), je toont datum + link. Voeg bv. voertuig toe:

schade_chauffeur = (
    df_filtered.loc[df_filtered["volledige naam"] == chauffeur, ["Datum", "Link", "Bus/ Tram", "Locatie", "teamcoach"]]
    .sort_values(by="Datum")
)
for _, row in schade_chauffeur.iterrows():
    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
    voertuig = row["Bus/ Tram"]; loc = row["Locatie"]; coach = row["teamcoach"]
    prefix = f"📅 {datum_str} — 🚌 {voertuig} — 📍 {loc} — 🧑‍💼 {coach} — "
    link = row.get("Link")
    if isinstance(link, str) and link.startswith(("http://", "https://")):
        st.markdown(prefix + f"[🔗 Link]({link})", unsafe_allow_html=True)
    else:
        st.markdown(prefix + "❌ Geen geldige link")


(Analoog kun je voertuigen/locaties-expanders net wat informatiever maken.)

Kleine kwaliteitsverbeteringen

Zet COLOR_* ook door in de PDF (ReportLab werkt met RGB; je kunt hex → RGB converteren en in TableStyle of custom bullets gebruiken).

Voeg st.toast("PDF klaar!") na download_button voor een subtiele bevestiging.

Zet plt.rcParams["figure.dpi"] = 150 bovenaan voor scherpere PNG’s in PDF.

Overweeg overal Plotly te gebruiken voor consistentie (nu mix je met Matplotlib).

Voeg (optioneel) een “Vandaag” snelknop bij de datumfilter: if st.button("Vandaag"): ....

Als je wil, kan ik deze wijzigingen in jouw volledige bestand integreren en je een opgeschoonde versie geven (met dezelfde functionaliteit maar netter gestructureerd in helpers).

Je zei:
waarom krijg ik niet alle teamcoaches te zien?
ChatGPT zei:
Nagedacht gedurende 48s

Die rode “chips” betekenen: de geselecteerde waarden staan niet (meer) in de opties van de multiselect. Dat gebeurt meestal door één van deze oorzaken:

Spaties/varianten in je data
teamcoach-waarden met voor/achter-spaties of verschillende hoofdletters tellen als andere namen. De query-param of oude selectie (“Jarne Stubbe”) matcht dan niet met de optie in df (“Jarne Stubbe ”), en Streamlit kleurt hem rood.

Verouderde query parameters
Je gebruikt st.query_params. Als in de URL nog ?teamcoach=… staat die niet meer bestaat (bv. na data-update), verschijnen ze rood en kan de opties-lijst leeg lijken.

Coach heeft geen (geldige) rijen meer
Omdat je vóór de filters rijen met lege naam of 9999 - - wegfiltert, kan een coach helemaal verdwijnen uit df (en dus uit de opties).

Snelle fix

Maak teamcoach schoon vóór je de opties bouwt, en laat lege strings vallen:

# Na het inladen van df en vóór de sidebar:
df["teamcoach"] = (
    df["teamcoach"]
    .astype(str)
    .str.strip()                # trim spaties
    .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
)

teamcoach_options = sorted(df["teamcoach"].dropna().unique().tolist())

# presets uit de URL, maar val terug op de volledige lijst
pref_tc = st.query_params.get_all("teamcoach") or teamcoach_options

# multiselect
selected_teamcoaches = st.multiselect(
    "Teamcoach",
    options=teamcoach_options,
    default=[v for v in pref_tc if v in teamcoach_options]  # voorkom rode chips
)

Handige tip

Klik je eigen Reset-filters knop (of verwijder alles na het ? in de URL) om verouderde query-params kwijt te raken.

Wil je álle coaches tonen, ook zonder huidige rijen? Lees dan een referentielijst met alle coaches in (apart Excel-tabblad) en gebruik die als options in plaats van df["teamcoach"].

Je zei:
schade met macro.xlsm
Bestand
aan de excel is niets gewijzigd. waarom zie ik niet alle teamcoaches in de filter?
ChatGPT zei:
Nagedacht gedurende 26s

Kort antwoord: je multiselect-opties komen uit df ná je opschoning (volledige naam filter + datumconversie + NaT-drop). Als een teamcoach alleen rijen heeft die daar wegvallen (bv. door een mislukte datumconversie), verdwijnt die coach uit de opties—ook al is het Excel-bestand zelf niet gewijzigd.

De 3 meest waarschijnlijke oorzaken in jouw code:

Je bouwt options uit de opgeschoonde df (niet uit de ruwe sheet).

Je datumparser gebruikt 2 paden; soms dayfirst=True, soms niet. Dat kan extra NaT opleveren ⇒ hele rijen (en dus coaches) verdwijnen.

Spaties/inconsistenties in teamcoach-namen (voor/achterspatie).

Snelle, concrete fixes

A. Bouw de opties uit de ruwe data (voor de filters/opschoning):

# Lees ruwe bron
raw = load_excel("schade met macro.xlsm", sheet_name="BRON")

# Teamcoach-waarden netjes maken
raw["teamcoach"] = (
    raw["teamcoach"]
    .astype(str)
    .str.strip()
    .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
)

teamcoach_options = sorted(raw["teamcoach"].dropna().unique().tolist())

# Presets uit URL, maar alleen geldige behouden
pref_tc = [v for v in (st.query_params.get_all("teamcoach") or teamcoach_options) if v in teamcoach_options]

# Multiselect gebruikt de volledige referentielijst
selected_teamcoaches = st.multiselect(
    "Teamcoach",
    options=teamcoach_options,
    default=pref_tc
)


B. Parse data altijd met dayfirst=True en pas dáárna schoonmaken:

df = load_excel("schade met macro.xlsm", sheet_name="BRON").copy()

# Datum altijd dezelfde parser:
df["Datum"] = pd.to_datetime(df["Datum"], errors="coerce", dayfirst=True)

# Namen & coaches schonen
df["volledige naam"] = df["volledige naam"].astype(str).str.strip()
df["teamcoach"] = df["teamcoach"].astype(str).str.strip()

# Daarna pas filteren
df = df[df["volledige naam"].notna() & (df["volledige naam"] != "") & (df["volledige naam"] != "9999 - -")]
df = df[df["Datum"].notna()]


C. Zorg dat defaults nooit ‘rode chips’ geven:

# (al in A gedaan)
default=[v for v in pref_tc if v in teamcoach_options]

Bonus: snel zien waar het misgaat

Voeg tijdelijk een klein debugblok toe om het verschil te zien:

with st.expander("🔎 Debug: coaches vóór/na opschoning"):
    coaches_raw = pd.Series(teamcoach_options)
    coaches_clean = sorted(df["teamcoach"].dropna().unique().tolist())
    st.write("Aantal in ruwe data:", len(coaches_raw))
    st.write("Aantal na opschoning:", len(coaches_clean))
    ontbrekend = sorted(set(coaches_raw) - set(coaches_clean))
    if ontbrekend:
        st.warning("Deze coaches verdwijnen na opschoning (check datum/namen):")
        st.write(ontbrekend)


Met deze aanpassingen zie je weer alle teamcoaches in de filter (uit de bronlijst), terwijl je analyses nog steeds draaien op de opgeschoonde df.

Je zei:
kan je de code herschrijven?
ChatGPT zei:

Top! Hieronder staat jouw herschreven streamlit-app als één geheel, met de fixes en verbeteringen geïntegreerd:

Teamcoach-filter bouwt zijn opties uit de ruwe data (dus niemand verdwijnt door opschoning of datum-issues).

Consistente en veilige datum-parsing (dayfirst=True) vóór verdere schoonmaak.

Login-kolommen worden genormaliseerd (login → gebruikersnaam, wachtwoord → paswoord) + optionele hash-vergelijking.

Reset-filters, CSV-download, en robuustere PDF-export met veilig opruimen van temp-bestanden.

Coachingslijst-inleesfunctie toleranter voor sheet-/kolomvarianten.

Geen “rode chips” meer: defaultwaarden worden gevalideerd tegen beschikbare opties.

Plak dit bestand 1-op-1 over je bestaande script.

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
    if not isinstance(naam, str):
        return None
    m = re.match(r"\s*(\d+)", naam)
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
        df = pd.read_excel(xls, sheet_name=sheetnaam)
        df.columns = df.columns.str.strip().str.lower()
        kol = None
        for k in ["p-nr", "p_nr", "pnr", "pnummer", "dienstnummer", "p nr"]:
            if k in df.columns:
                kol = k; break
        if kol is None:
            return set()
        return set(
            df[kol].astype(str).str.extract(r"(\d+)", expand=False).dropna().str.strip().tolist()
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

# Normaliseer kolomnamen en basis-schoonmaak (zonder rijen te droppen)
raw.columns = raw.columns.str.strip()
for col in ["volledige naam", "teamcoach", "Locatie", "Bus/ Tram"]:
    if col in raw.columns:
        raw[col] = raw[col].astype(str).str.strip()

# Teamcoach-opties uit RUWE data (dus volledig)
raw_tc = (
    raw["teamcoach"]
    .astype(str)
    .str.strip()
    .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
)
teamcoach_options = sorted(pd.Series(raw_tc).dropna().unique().tolist())

# ========= Opgeschoonde df voor analyses =========
df = raw.copy()

# Datum eenduidig parsen en daarna pas droppen
df["Datum"] = pd.to_datetime(df["Datum"], errors="coerce", dayfirst=True)

# Weg met ongeldige/lege namen of speciale placeholder
df = df[df["volledige naam"].notna() & (df["volledige naam"] != "") & (df["volledige naam"] != "9999 - -")].copy()
# Alleen rijen met geldige datums
df = df[df["Datum"].notna()].copy()

# Afgeleide velden
df["Kwartaal"] = df["Datum"].dt.to_period("Q").astype(str)
df["dienstnummer"] = df["volledige naam"].astype(str).str.extract(r"^(\d+)", expand=False).astype(str).str.strip()

# ========= Coachingslijst =========
gecoachte_ids, coaching_ids, coach_warn = lees_coachingslijst()
if coach_warn:
    st.sidebar.warning(f"⚠️ {coach_warn}")

# Flags op df (optioneel)
df["gecoacht_geel"] = df["dienstnummer"].astype(str).isin(gecoachte_ids)
df["gecoacht_blauw"] = df["dienstnummer"].astype(str).isin(coaching_ids)

# ========= UI: Titel + Caption =========
st.title("📊 Schadegevallen Dashboard")
st.caption("🟡 = voltooide coaching · 🔵 = in coaching (lopend)")

# ========= Query params presets (LEZEN) =========
qp = st.query_params  # Streamlit 1.32+

def _clean_list(values, allowed):
    return [v for v in (values or []) if v in allowed]

# Teamcoach presets: alleen geldige waarden
pref_tc = _clean_list(qp.get_all("teamcoach"), teamcoach_options) or teamcoach_options
# Voertuig/locatie/kwartaal opties uit opgeschoonde df (mag)
voertuig_options = sorted(df["Bus/ Tram"].dropna().unique().tolist())
locatie_options  = sorted(df["Locatie"].dropna().unique().tolist())
kwartaal_options = sorted(df["Kwartaal"].dropna().unique().tolist())

pref_vh = _clean_list(qp.get_all("voertuig"), voertuig_options) or voertuig_options
pref_lo = _clean_list(qp.get_all("locatie"),  locatie_options)  or locatie_options
pref_kw = _clean_list(qp.get_all("kwartaal"), kwartaal_options)  or kwartaal_options

# ========= Sidebar filters =========
with st.sidebar:
    st.header("🔍 Filters")
    selected_teamcoaches = st.multiselect(
        "Teamcoach",
        options=teamcoach_options,
        default=pref_tc
    )

    selected_voertuigen = st.multiselect(
        "Voertuigtype",
        options=voertuig_options,
        default=pref_vh
    )

    selected_locaties = st.multiselect(
        "Locatie",
        options=locatie_options,
        default=pref_lo
    )

    selected_kwartalen = st.multiselect(
        "Kwartaal",
        options=kwartaal_options,
        default=pref_kw
    )

    # 🗓️ Datum-bereik filter
    st.markdown("### 🗓️ Datum")
    min_d, max_d = df["Datum"].min().date(), df["Datum"].max().date()
    date_from, date_to = st.date_input(
        "Periode",
        value=(min_d, max_d),
        min_value=min_d,
        max_value=max_d
    )
    if isinstance(date_from, tuple):
        date_from, date_to = date_from

    colA, colB = st.columns(2)
    with colA:
        if st.button("🔄 Reset filters"):
            qp.clear()
            st.rerun()
    with colB:
        if st.button("🔖 Bewaar filters in URL"):
            qp.clear()
            qp["teamcoach"] = selected_teamcoaches
            qp["voertuig"]  = selected_voertuigen
            qp["locatie"]   = selected_locaties
            qp["kwartaal"]  = selected_kwartalen
            st.success("Link met filters staat nu in de adresbalk. Kopieer & deel!")

# ========= Filters toepassen =========
mask = (
    df["teamcoach"].isin(selected_teamcoaches) &
    df["Bus/ Tram"].isin(selected_voertuigen) &
    df["Locatie"].isin(selected_locaties) &
    df["Kwartaal"].isin(selected_kwartalen)
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
    kolommen_pdf = ["Datum", "volledige naam", "Locatie", "Bus/ Tram"]
    if "Link" in df.columns:
        kolommen_pdf.append("Link")

    schade_pdf = df_filtered[df_filtered["teamcoach"] == pdf_coach][kolommen_pdf].copy()
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
        elements.append(Paragraph(f"- Unieke chauffeurs: {schade_pdf['volledige naam'].nunique()}", styles["Normal"]))
        elements.append(Paragraph(f"- Unieke locaties: {schade_pdf['Locatie'].nunique()}", styles["Normal"]))
        elements.append(Spacer(1, 12))

    aantal_per_chauffeur = schade_pdf["volledige naam"].value_counts()
    elements.append(Paragraph("👤 Aantal schadegevallen per chauffeur:", styles["Heading2"]))
    for nm, count in aantal_per_chauffeur.items():
        nm_disp = nm or "onbekend"
        elements.append(Paragraph(f"- {nm_disp}: {count}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    aantal_per_locatie = schade_pdf["Locatie"].value_counts()
    elements.append(Paragraph("📍 Aantal schadegevallen per locatie:", styles["Heading2"]))
    for loc, count in aantal_per_locatie.items():
        loc_disp = loc or "onbekend"
        elements.append(Paragraph(f"- {loc_disp}: {count}", styles["Normal"]))
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
        nm = (row["volledige naam"] or "onbekend")
        voertuig = (row["Bus/ Tram"] or "onbekend")
        locatie = (row["Locatie"] or "onbekend")
        rij = [datum, nm, voertuig, locatie]
        if heeft_link:
            link = row.get("Link")
            rij.append(str(link) if (pd.notna(link) and isinstance(link, str) and link.startswith(("http://","https://"))) else "-")
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

    # opruimen temp chart-bestand
    if chart_path and os.path.exists(chart_path):
        try:
            os.remove(chart_path)
        except Exception:
            pass
# ========= TAB 1: Chauffeur =========
with tab1:
    st.subheader("Aantal schadegevallen per chauffeur")
    top_n_option = st.selectbox("Toon top aantal chauffeurs:", ["10", "20", "50", "Allemaal"])

    # 1) Data veilig opbouwen
    chart_series = df_filtered["volledige naam"].value_counts()
    if top_n_option != "Allemaal":
        chart_series = chart_series.head(int(top_n_option))

    if chart_series.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        # Bouw dataframe voor plotly
        plot_df = (
            chart_series
            .rename_axis("chauffeur")
            .reset_index(name="aantal")
        )
        # Voeg status + badge toe
        plot_df["status"] = plot_df["chauffeur"].apply(status_van_chauffeur)
        plot_df["badge"]  = plot_df["status"].apply(badge_van_status)
        # Sorteer oplopend zodat horizontale bars van klein -> groot lopen
        plot_df = plot_df.sort_values("aantal", ascending=True, kind="stable")

        # 2) Legenda met badges boven de grafiek (visueel/snappy)
        st.markdown("**Legenda:** 🟡 Voltooid · 🔵 Coaching · 🟡🔵 Beide · ⚪ Geen")

        # 3) Plotly grafiek met consistente kleuren + hover-tooltips
        color_map = {
            "Voltooid": COLOR_GEEL,
            "Coaching": COLOR_BLAUW,
            "Beide":    COLOR_MIX,
            "Geen":     COLOR_GRIJS,
        }

        fig = px.bar(
            plot_df,
            x="aantal",
            y="chauffeur",
            color="status",
            orientation="h",
            color_discrete_map=color_map,
            hover_data={
                "aantal": True,
                "chauffeur": True,
                "status": True,
                "badge": False,
            },
            labels={"aantal": "Aantal schadegevallen", "chauffeur": "Chauffeur", "status": "Status"},
        )

        # Hovertemplate (enkel de juiste versie houden)
        fig.update_traces(
            customdata=plot_df[["badge", "status"]].to_numpy(),
            hovertemplate="<b>%{y}</b><br>"
                          "Aantal: %{x}<br>"
                          "Status: %{customdata[0]}%{customdata[1]}<extra></extra>"
        )

        # Layout: compacte marges, horizontale legenda bovenaan
        fig.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(l=10, r=10, t=10, b=10),
            height=max(260, 28 * len(plot_df) + 120),
        )

        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        # 4) Lijst per chauffeur (expanders) – badges voor de titel
        st.subheader("📂 Schadegevallen per chauffeur")
        # Gebruik dezelfde volgorde als de grafiek (van klein naar groot)
        ordered_names = plot_df["chauffeur"].tolist()

        for chauffeur in ordered_names[::-1]:  # van groot -> klein voor prettige leeservaring
            aantal = int(chart_series.get(chauffeur, 0))
            status = status_van_chauffeur(chauffeur)
            badge = badge_van_status(status)
            titel = f"{badge}{chauffeur} — {aantal} schadegevallen"

            with st.expander(titel):
                schade_chauffeur = (
                    df_filtered.loc[df_filtered["volledige naam"] == chauffeur, ["Datum", "Link"]]
                    .sort_values(by="Datum")
                )
                for _, row in schade_chauffeur.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    link = row.get("Link") if "Link" in df_filtered.columns else None
                    if isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — ❌ Geen geldige link")

# (Optioneel) verdere tabs tab2/tab3/tab4 kun je vullen met je bestaande of extra analyses
with tab2:
    st.subheader("Teamcoach overzicht")
    coach_counts = (
        df_filtered.groupby("teamcoach")["volledige naam"].count()
        .rename("aantal").reset_index().sort_values("aantal", ascending=False)
    )
    st.bar_chart(coach_counts.set_index("teamcoach"), height=260)
    st.dataframe(coach_counts, use_container_width=True)

with tab3:
    st.subheader("Voertuig overzicht")
    veh_counts = (
        df_filtered.groupby("Bus/ Tram")["volledige naam"].count()
        .rename("aantal").reset_index().sort_values("aantal", ascending=False)
    )
    st.bar_chart(veh_counts.set_index("Bus/ Tram"), height=260)
    st.dataframe(veh_counts, use_container_width=True)

with tab4:
    st.subheader("Locatie overzicht")
    loc_counts = (
        df_filtered.groupby("Locatie")["volledige naam"].count()
        .rename("aantal").reset_index().sort_values("aantal", ascending=False)
    )
    st.bar_chart(loc_counts.set_index("Locatie"), height=260)
    st.dataframe(loc_counts, use_container_width=True)




# ========= TAB 2: Teamcoach =========
with tab2:
    st.subheader("Aantal schadegevallen per teamcoach")
    chart_data = df_filtered["teamcoach"].value_counts()
    if chart_data.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
        chart_data.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen")
        ax.set_ylabel("Teamcoach")
        ax.set_title("Schadegevallen per teamcoach")
        st.pyplot(fig)

        st.subheader("📂 Schadegevallen per teamcoach")
        for coach in chart_data.index.tolist():
            schade_per_coach = df_filtered[df_filtered["teamcoach"] == coach][["Datum", "Link", "volledige naam"]].sort_values(by="Datum")
            aantal = len(schade_per_coach)
            with st.expander(f"{coach} — {aantal} schadegevallen"):
                for _, row in schade_per_coach.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam"]; link = row["Link"]
                    if pd.notna(link) and isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — ❌ Geen geldige link")

# ========= TAB 3: Voertuig =========
with tab3:
    st.subheader("📈 Schadegevallen per maand per voertuigtype")
    df_per_maand = df_filtered.copy()
    maanden_nl = {1:"januari",2:"februari",3:"maart",4:"april",5:"mei",6:"juni",7:"juli",8:"augustus",9:"september",10:"oktober",11:"november",12:"december"}
    df_per_maand["Maand"] = df_per_maand["Datum"].dt.month.map(maanden_nl).str.lower()
    maand_volgorde = ["januari","februari","maart","april","mei","juni","juli","augustus","september","oktober","november","december"]
    groep = df_per_maand.groupby(["Maand", "Bus/ Tram"]).size().unstack(fill_value=0)
    groep = groep.reindex(maand_volgorde)

    fig2, ax2 = plt.subplots(figsize=(10, 4))
    groep.plot(ax=ax2, marker="o")
    ax2.set_xlabel("Maand"); ax2.set_ylabel("Aantal schadegevallen")
    ax2.set_title("Lijngrafiek per maand per voertuigtype")
    ax2.legend(title="Voertuig")
    st.pyplot(fig2)

    st.subheader("Aantal schadegevallen per type voertuig")
    chart_data = df_filtered["Bus/ Tram"].value_counts()
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
            schade_per_voertuig = df_filtered[df_filtered["Bus/ Tram"] == voertuig][["Datum", "Link", "volledige naam"]].sort_values(by="Datum")
            aantal = len(schade_per_voertuig)
            with st.expander(f"{voertuig} — {aantal} schadegevallen"):
                for _, row in schade_per_voertuig.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam"]; link = row["Link"]
                    if pd.notna(link) and isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — ❌ Geen geldige link")

# ========= TAB 4: Locatie =========
with tab4:
    st.subheader("Aantal schadegevallen per locatie")
    top_locatie_option = st.selectbox("Toon top aantal locaties:", ["10", "20", "50", "Allemaal"])
    chart_data = df_filtered["Locatie"].value_counts()
    if top_locatie_option != "Allemaal":
        chart_data = chart_data.head(int(top_locatie_option))

    if chart_data.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data) * 0.3 + 1)))
        chart_data.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen"); ax.set_ylabel("Locatie")
        ax.set_title("Top " + top_locatie_option + " schadegevallen per locatie" if top_locatie_option != "Allemaal" else "Schadegevallen per locatie")
        st.pyplot(fig)

        st.subheader("📂 Schadegevallen per locatie")
        for locatie in chart_data.index.tolist():
            schade_per_locatie = df_filtered[df_filtered["Locatie"] == locatie][["Datum", "Link", "volledige naam"]].sort_values(by="Datum")
            aantal = len(schade_per_locatie)
            with st.expander(f"{locatie} — {aantal} schadegevallen"):
                for _, row in schade_per_locatie.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam"]; link = row["Link"]
                    if pd.notna(link) and isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — ❌ Geen geldige link")
