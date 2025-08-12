import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
import tempfile
import hashlib
from datetime import datetime

# ========= Instellingen =========
LOGIN_ACTIEF = False  # Zet True om login te activeren
st.set_page_config(page_title="Schadegevallen Dashboard", layout="wide")

# ========= Helpers =========
def hash_wachtwoord(wachtwoord: str) -> str:
    return hashlib.sha256(str(wachtwoord).encode()).hexdigest()

def naam_naar_dn(naam: str) -> str | None:
    """Haal dienstnummer uit 'volledige naam' zoals '1234 - Voornaam Achternaam'."""
    if pd.isna(naam):
        return None
    s = pd.Series([str(naam)])
    dn = s.astype(str).str.extract(r"^(\d+)", expand=False).iloc[0]
    return str(dn).strip() if pd.notna(dn) else None

# ========= Gebruikersbestand (login) =========
gebruikers_df = pd.read_excel("chauffeurs.xlsx")
gebruikers_df.columns = gebruikers_df.columns.str.strip().str.lower()
if "gebruikersnaam" in gebruikers_df.columns:
    gebruikers_df["gebruikersnaam"] = gebruikers_df["gebruikersnaam"].astype(str).str.strip()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if LOGIN_ACTIEF and not st.session_state.logged_in:
    st.title("🔐 Inloggen")
    username = st.text_input("Gebruikersnaam")
    password = st.text_input("Wachtwoord", type="password")
    if st.button("Log in"):
        gebruiker = gebruikers_df[gebruikers_df.get("gebruikersnaam", "") == username]
        if not gebruiker.empty:
            echte_hash = hash_wachtwoord(password)
            juiste_hash = hash_wachtwoord(str(gebruiker["paswoord"].values[0]))
            if echte_hash == juiste_hash:
                st.session_state.logged_in = True
                st.session_state.username = username
                st.success("✅ Ingelogd!")
                if "laatste login" in gebruikers_df.columns:
                    gebruikers_df.loc[gebruikers_df["gebruikersnaam"] == username, "laatste login"] = datetime.now()
                    gebruikers_df.to_excel("chauffeurs.xlsx", index=False)
                st.rerun()
            else:
                st.error("❌ Verkeerd wachtwoord.")
        else:
            st.error("❌ Gebruiker niet gevonden.")
    st.stop()
else:
    if not LOGIN_ACTIEF:
        st.session_state.logged_in = True
        st.session_state.username = "demo"

# Rol + naam
if not LOGIN_ACTIEF:
    rol = "teamcoach"; naam = "demo"
else:
    ingelogde_info = gebruikers_df[gebruikers_df["gebruikersnaam"] == st.session_state.username].iloc[0]
    rol = ingelogde_info["rol"]; naam = ingelogde_info["gebruikersnaam"]

# ========= Data laden & opschonen =========
df = pd.read_excel("schade met macro.xlsm", sheet_name="BRON")
df = df[df["volledige naam"].notna() & (df["volledige naam"] != "9999 - -")].copy()
df["Datum"] = pd.to_datetime(df["Datum"], errors="coerce")
df = df[df["Datum"].notna()].copy()
df["Kwartaal"] = df["Datum"].dt.to_period("Q").astype(str)
df["dienstnummer"] = df["volledige naam"].astype(str).str.extract(r"^(\d+)", expand=False).astype(str).str.strip()

# Login-filter
if rol == "chauffeur":
    df = df[df["dienstnummer"] == str(naam)].copy()
    if not df.empty:
        try:
            volledige_naam = df["volledige naam"].iloc[0].split(" - ", 1)[1]
            st.info(f"👤 Ingelogd als chauffeur: {volledige_naam} ({naam})")
        except Exception:
            st.info(f"👤 Ingelogd als chauffeur: {naam}")
    else:
        st.info(f"👤 Ingelogd als chauffeur: {naam}")
else:
    st.success(f"🧑‍💼 Ingelogd als teamcoach: {naam}")

# ========= Coachingslijst inlezen (Voltooide coachings / P-nr) =========
gecoachte_ids = set()
try:
    xls = pd.ExcelFile("Coachingslijst.xlsx")
    sheet_naam = next((s for s in xls.sheet_names if s.strip().lower() == "voltooide coachings"), None)
    if sheet_naam is None:
        st.warning("⚠️ Geen tabblad gevonden dat 'Voltooide coachings' heet in Coachingslijst.xlsx.")
    else:
        coach_df = pd.read_excel("Coachingslijst.xlsx", sheet_name=sheet_naam)
        coach_df.columns = coach_df.columns.str.strip()
        if "P-nr" not in coach_df.columns:
            st.warning("⚠️ Kolom 'P-nr' niet gevonden in tabblad 'Voltooide coachings'.")
        else:
            gecoachte_ids = set(
                coach_df["P-nr"]
                .astype(str)
                .str.extract(r"(\d+)", expand=False)
                .dropna()
                .str.strip()
                .tolist()
            )
except Exception as e:
    st.warning(f"⚠️ Coachingslijst niet gevonden of onleesbaar: {e}")

df["gecoacht"] = df["dienstnummer"].astype(str).isin(gecoachte_ids)

# ========= UI: Titel + Caption =========
st.title("📊 Schadegevallen Dashboard")
st.caption("🟡 = chauffeur heeft een voltooide coaching in de Coachingslijst")

# ========= Sidebar filters =========
with st.sidebar:
    st.header("🔍 Filters")
    selected_teamcoaches = st.multiselect(
        "Teamcoach", options=df["teamcoach"].dropna().unique().tolist(),
        default=df["teamcoach"].dropna().unique().tolist()
    )
    selected_voertuigen = st.multiselect(
        "Voertuigtype", options=df["Bus/ Tram"].dropna().unique().tolist(),
        default=df["Bus/ Tram"].dropna().unique().tolist()
    )
    selected_locaties = st.multiselect(
        "Locatie", options=df["Locatie"].dropna().unique().tolist(),
        default=df["Locatie"].dropna().unique().tolist()
    )
    kwartaal_opties = sorted(df["Kwartaal"].dropna().unique().tolist())
    selected_kwartalen = st.multiselect("Kwartaal", options=kwartaal_opties, default=kwartaal_opties)

df_filtered = df[
    df["teamcoach"].isin(selected_teamcoaches) &
    df["Bus/ Tram"].isin(selected_voertuigen) &
    df["Locatie"].isin(selected_locaties) &
    df["Kwartaal"].isin(selected_kwartalen)
].copy()

if df_filtered.empty:
    st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    st.stop()

# ========= KPI =========
st.metric("Totaal aantal schadegevallen", len(df_filtered))

# ========= Tabs =========
tab1, tab2, tab3, tab4 = st.tabs(["👤 Chauffeur", "🧑‍💼 Teamcoach", "🚌 Voertuig", "📍 Locatie"])

# ========= PDF Export (per teamcoach) =========
st.markdown("---")
st.sidebar.subheader("📄 PDF Export per teamcoach")
pdf_coach = st.sidebar.selectbox("Kies teamcoach voor export", df["teamcoach"].dropna().unique())
generate_pdf = st.sidebar.button("Genereer PDF")

if generate_pdf:
    schade_pdf = df_filtered[df_filtered["teamcoach"] == pdf_coach][["Datum", "volledige naam", "Locatie", "Bus/ Tram", "Link"]].copy()
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
            fig.savefig(tmpfile.name)
            plt.close(fig)
            elements.append(Paragraph("📊 Schadegevallen per maand:", styles["Heading2"]))
            elements.append(Paragraph("Deze grafiek toont het aantal gemelde schadegevallen per maand voor deze teamcoach.", styles["Italic"]))
            elements.append(Spacer(1, 6))
            elements.append(Image(tmpfile.name, width=400, height=200))
            elements.append(Spacer(1, 12))

    elements.append(Paragraph("📂 Individuele schadegevallen:", styles["Heading2"]))
    elements.append(Spacer(1, 6))
    for _, row in schade_pdf.iterrows():
        datum = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
        nm = row["volledige naam"] or "onbekend"
        locatie = row["Locatie"] or "onbekend"
        voertuig = row["Bus/ Tram"] or "onbekend"
        link = row["Link"]
        regel = f"📅 {datum} — 👤 {nm} — 🚌 {voertuig} — 📍 {locatie}"
        if pd.notna(link) and isinstance(link, str) and link.startswith(("http://", "https://")):
            regel += f"<br/><a href='{link}'>🔗 Link</a>"
        elements.append(Paragraph(regel, styles["Normal"]))
        elements.append(Spacer(1, 6))

    doc.build(elements)
    buffer.seek(0)
    bestandsnaam = f"schade_{pdf_coach.replace(' ', '_')}_{datetime.today().strftime('%Y%m%d')}.pdf"
    st.sidebar.download_button(label="📥 Download PDF", data=buffer, file_name=bestandsnaam, mime="application/pdf")

# ========= TAB 1: Chauffeur =========
with tab1:
    st.subheader("Aantal schadegevallen per chauffeur")
    top_n_option = st.selectbox("Toon top aantal chauffeurs:", ["10", "20", "50", "Allemaal"])

    chart_data = df_filtered["volledige naam"].value_counts()
    if top_n_option != "Allemaal":
        chart_data = chart_data.head(int(top_n_option))

    def is_gecoacht_naam(naam: str) -> bool:
        dn = naam_naar_dn(naam)
        return (dn is not None) and (str(dn) in gecoachte_ids)

    chart_data_sorted = chart_data.sort_values()
    # Geel voor gecoacht, grijs voor niet-gecoacht
    bar_colors = ["#FFD54F" if is_gecoacht_naam(nm) else "#BDBDBD" for nm in chart_data_sorted.index]

    fig, ax = plt.subplots(figsize=(8, max(1.5, len(chart_data_sorted) * 0.3 + 1)))
    chart_data_sorted.plot(kind="barh", ax=ax, color=bar_colors)
    ax.set_xlabel("Aantal schadegevallen")
    ax.set_ylabel("Chauffeur")
    ax.set_title("Top " + top_n_option + " schadegevallen per chauffeur" if top_n_option != "Allemaal" else "Alle chauffeurs")
    st.pyplot(fig)

    st.subheader("📂 Schadegevallen per chauffeur")
    top_chauffeurs = chart_data.index.tolist()
    for chauffeur in top_chauffeurs:
        aantal = len(df_filtered[df_filtered["volledige naam"] == chauffeur])
        badge = "🟡 " if is_gecoacht_naam(chauffeur) else ""
        titel = f"{badge}{chauffeur} — {aantal} schadegevallen"
        with st.expander(titel):
            schade_chauffeur = df_filtered[df_filtered["volledige naam"] == chauffeur][["Datum", "Link"]].sort_values(by="Datum")
            for _, row in schade_chauffeur.iterrows():
                datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                link = row["Link"]
                if pd.notna(link) and isinstance(link, str):
                    st.markdown(f"📅 {datum_str} — [🔗 Link]({link})", unsafe_allow_html=True)
                else:
                    st.markdown(f"📅 {datum_str} — ❌ Geen geldige link")

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
