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

# ========= Kleuren (consistent in app & PDF waar van toepassing) =========
COLOR_GEEL  = "#FFD54F"  # voltooide coaching
COLOR_BLAUW = "#2196F3"  # in coaching
COLOR_MIX   = "#7E57C2"  # beide
COLOR_GRIJS = "#BDBDBD"  # geen



def status_van_chauffeur(naam: str) -> str:
    """Geef status op basis van sets: 'Voltooid', 'Coaching', 'Beide', of 'Geen'."""
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
    return {
        "Voltooid": "🟡 ",
        "Coaching": "🔵 ",
        "Beide":    "🟡🔵 ",
        "Geen":     ""
    }.get(status, "")


# ========= Gebruikersbestand (login) =========
gebruikers_df = pd.read_excel("chauffeurs.xlsx")
gebruikers_df.columns = gebruikers_df.columns.str.strip().str.lower()

# Zorg dat de kolommen die we gebruiken bestaan
vereist_login_kolommen = {"gebruikersnaam", "paswoord"}
missend_login = [c for c in vereist_login_kolommen if c not in gebruikers_df.columns]
if missend_login:
    st.error(f"Login configuratie onvolledig. Ontbrekende kolommen in 'chauffeurs.xlsx': {', '.join(missend_login)}")
    st.stop()

# String-strippen voor zekere vergelijking
gebruikers_df["gebruikersnaam"] = gebruikers_df["gebruikersnaam"].astype(str).str.strip()
gebruikers_df["paswoord"] = gebruikers_df["paswoord"].astype(str)

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if LOGIN_ACTIEF and not st.session_state.logged_in:
    st.title("🔐 Inloggen")
    username = st.text_input("Gebruikersnaam")
    password = st.text_input("Wachtwoord", type="password")
    if st.button("Log in"):
        rij = gebruikers_df.loc[gebruikers_df["gebruikersnaam"] == str(username).strip()]

        if not rij.empty and str(rij["paswoord"].iloc[0]) == str(password):
            st.session_state.logged_in = True
            st.session_state.username = str(username).strip()
            st.success("✅ Ingelogd!")

            # 'laatste login' bijwerken als kolom bestaat
            if "laatste login" in gebruikers_df.columns:
                try:
                    gebruikers_df.loc[rij.index, "laatste login"] = datetime.now()
                    gebruikers_df.to_excel("chauffeurs.xlsx", index=False)
                except Exception as e:
                    st.warning(f"Kon 'laatste login' niet opslaan: {e}")

            st.rerun()
        else:
            st.error("❌ Onjuiste gebruikersnaam of wachtwoord.")
    st.stop()
else:
    if not LOGIN_ACTIEF:
        st.session_state.logged_in = True
        st.session_state.username = "demo"

# ========= Rol + naam =========
if not LOGIN_ACTIEF:
    rol = "teamcoach"
    naam = "demo"
else:
    ingelogde_info = gebruikers_df.loc[gebruikers_df["gebruikersnaam"] == st.session_state.username].iloc[0]
    rol = str(ingelogde_info.get("rol", "teamcoach")).strip()
    # Als 'dienstnummer' in chauffeurs.xlsx staat, gebruik die voor chauffeur-filter; anders fallback op gebruikersnaam
    if rol == "chauffeur":
        naam = str(ingelogde_info.get("dienstnummer", ingelogde_info["gebruikersnaam"])).strip()
    else:
        naam = str(ingelogde_info["gebruikersnaam"]).strip()

# ========= Data laden & opschonen =========
df = pd.read_excel("schade met macro.xlsm", sheet_name="BRON")
vereist = {"volledige naam","Datum","Locatie","Bus/ Tram","teamcoach"}
missend = [c for c in vereist if c not in df.columns]
if missend:
    st.error(f"Ontbrekende kolommen in data: {', '.join(missend)}")
    st.stop()

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

# ========= Coachingslijst inlezen (Voltooide coachings / Coaching) =========
gecoachte_ids = set()       # 🟡
coaching_ids = set()        # 🔵

try:
    xls = pd.ExcelFile("Coachingslijst.xlsx")

    # 🟡 Voltooide coachings
    sheet_voltooid = next((s for s in xls.sheet_names if s.strip().lower() == "voltooide coachings"), None)
    if sheet_voltooid:
        coach_df = pd.read_excel(xls, sheet_name=sheet_voltooid)
        coach_df.columns = coach_df.columns.str.strip()
        if "P-nr" in coach_df.columns:
            gecoachte_ids = set(
                coach_df["P-nr"].astype(str).str.extract(r"(\d+)", expand=False).dropna().str.strip().tolist()
            )

    # 🔵 Coaching
    sheet_coaching = next((s for s in xls.sheet_names if s.strip().lower() == "coaching"), None)
    if sheet_coaching:
        coach2_df = pd.read_excel(xls, sheet_name=sheet_coaching)
        coach2_df.columns = coach2_df.columns.str.strip()
        if "P-nr" in coach2_df.columns:
            coaching_ids = set(
                coach2_df["P-nr"].astype(str).str.extract(r"(\d+)", expand=False).dropna().str.strip().tolist()
            )

except Exception as e:
    st.warning(f"⚠️ Coachingslijst niet gevonden of onleesbaar: {e}")

# Extra info in de sidebar om te zien of er wel blauwe/geel IDs zijn
with st.sidebar:
    st.markdown("### ℹ️ Coaching-status")
    st.write(f"🟡 Voltooide coachings: **{len(gecoachte_ids)}**")
    st.write(f"🔵 Coaching (lopend): **{len(coaching_ids)}**")

# Flags op df (optioneel, niet strikt noodzakelijk voor weergave)
df["gecoacht_geel"] = df["dienstnummer"].astype(str).isin(gecoachte_ids)
df["gecoacht_blauw"] = df["dienstnummer"].astype(str).isin(coaching_ids)

# ========= UI: Titel + Caption =========
st.title("📊 Schadegevallen Dashboard")
st.caption("🟡 = voltooide coaching · 🔵 = in coaching (lopend)")

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

    # Compacte tabel met individuele schadegevallen
    elements.append(Paragraph("📂 Individuele schadegevallen:", styles["Heading2"]))
    elements.append(Spacer(1, 6))
    tabel_data = [["Datum", "Chauffeur", "Voertuig", "Locatie", "Link"]]
    for _, row in schade_pdf.iterrows():
        datum = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
        nm = row["volledige naam"] or "onbekend"
        locatie = row["Locatie"] or "onbekend"
        voertuig = row["Bus/ Tram"] or "onbekend"
        link = row.get("Link")
        linktxt = str(link) if (pd.notna(link) and isinstance(link, str) and link.startswith(("http://","https://"))) else "-"
        tabel_data.append([datum, nm, voertuig, locatie, linktxt])

    if len(tabel_data) > 1:
        tbl = Table(tabel_data, repeatRows=1, colWidths=[70, 160, 60, 100, 70])
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
                "badge": False,  # we tonen badge in hovertemplate zelf
            },
            labels={"aantal": "Aantal schadegevallen", "chauffeur": "Chauffeur", "status": "Status"},
        )

        # Hovertemplate met badge + nette formatting
        fig.update_traces(
            hovertemplate="<b>%{customdata[0]}</b><br>"
                          "Status: %{marker.color}<extra></extra>",
        )
        # Bovenstaande is tricky met kleur; gebruik customdata met badge + status
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
                    link = row.get("Link")
                    if isinstance(link, str) and link.startswith(("http://", "https://")):
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
