import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import matplotlib.pyplot as plt
from reportlab.platypus import Image
import tempfile

# Laad de data
df = pd.read_excel("schade met macro.xlsm", sheet_name="BRON")

# Opschonen
df = df[df["volledige naam"].notna() & (df["volledige naam"] != "9999 - -")]

# Zet datumkolom om naar datetime
df["Datum"] = pd.to_datetime(df["Datum"], errors="coerce")

# Filter rijen met ongeldige of lege datums (NaT)
df = df[df["Datum"].notna()]

# Voeg kwartaal-kolom toe (bijv. '2024-Q1')
df["Kwartaal"] = df["Datum"].dt.to_period("Q").astype(str)

# Titel
st.title("📊 Schadegevallen Dashboard")

# Sidebar filters
with st.sidebar:
    st.header("🔍 Filters")
    
    selected_teamcoaches = st.multiselect(
        "Teamcoach", options=df["teamcoach"].dropna().unique(), default=df["teamcoach"].dropna().unique()
    )
    selected_voertuigen = st.multiselect(
        "Voertuigtype", options=df["Bus/ Tram"].dropna().unique(), default=df["Bus/ Tram"].dropna().unique()
    )
    selected_locaties = st.multiselect(
        "Locatie", options=df["Locatie"].dropna().unique(), default=df["Locatie"].dropna().unique()
    )
    kwartaal_opties = sorted(df["Kwartaal"].dropna().unique())
    selected_kwartalen = st.multiselect("Kwartaal", options=kwartaal_opties, default=kwartaal_opties)

# Filter toepassen
df_filtered = df[
    df["teamcoach"].isin(selected_teamcoaches) &
    df["Bus/ Tram"].isin(selected_voertuigen) &
    df["Locatie"].isin(selected_locaties) &
    df["Kwartaal"].isin(selected_kwartalen)
]

# ❗ Controleer of er nog data is
if df_filtered.empty:
    st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    st.stop()


# KPI
st.metric("Totaal aantal schadegevallen", len(df_filtered))

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["👤 Chauffeur", "🧑‍💼 Teamcoach", "🚌 Voertuig", "📍 Locatie"])


# --- PDF genereren -

st.markdown("---")
st.sidebar.subheader("📄 PDF Export per teamcoach")

pdf_coach = st.sidebar.selectbox("Kies teamcoach voor export", df["teamcoach"].dropna().unique())
generate_pdf = st.sidebar.button("Genereer PDF")

if generate_pdf:
    # Filter schadegevallen van de gekozen coach
    schade_pdf = df_filtered[df_filtered["teamcoach"] == pdf_coach][["Datum", "volledige naam", "Locatie", "Bus/ Tram", "Link"]].copy()
    schade_pdf = schade_pdf.sort_values(by="Datum")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # Titel
    elements.append(Paragraph(f"Overzicht schadegevallen - Teamcoach: <b>{pdf_coach}</b>", styles["Title"]))
    elements.append(Spacer(1, 12))

    # ➕ Aantal schadegevallen per chauffeur
    aantal_per_chauffeur = schade_pdf["volledige naam"].value_counts()
    elements.append(Paragraph("👤 Aantal schadegevallen per chauffeur:", styles["Heading2"]))
    for naam, count in aantal_per_chauffeur.items():
        elements.append(Paragraph(f"- {naam}: {count}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    # ➕ Aantal schadegevallen per locatie
    aantal_per_locatie = schade_pdf["Locatie"].value_counts()
    elements.append(Paragraph("📍 Aantal schadegevallen per locatie:", styles["Heading2"]))
    for locatie, count in aantal_per_locatie.items():
        elements.append(Paragraph(f"- {locatie}: {count}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    # ➕ Grafiek per maand
    import matplotlib.pyplot as plt
    from reportlab.platypus import Image
    import tempfile

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
        elements.append(Image(tmpfile.name, width=400, height=200))
        elements.append(Spacer(1, 12))

    # ➕ Individuele schadegevallen
    elements.append(Paragraph("📂 Individuele schadegevallen:", styles["Heading2"]))
    elements.append(Spacer(1, 6))

    for _, row in schade_pdf.iterrows():
        datum = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
        naam = row["volledige naam"]
        locatie = row["Locatie"] or "onbekend"
        voertuig = row["Bus/ Tram"] or "onbekend"
        regel = f"📅 {datum} — 👤 {naam} — 🚌 {voertuig} — 📍 {locatie}"
        if pd.notna(row["Link"]) and isinstance(row["Link"], str):
            regel += f"<br/><a href='{row['Link']}'>🔗 Link</a>"

        elements.append(Paragraph(regel, styles["Normal"]))
        elements.append(Spacer(1, 6))

    # PDF genereren
    doc.build(elements)
    buffer.seek(0)

    st.sidebar.download_button(
        label="📥 Download PDF",
        data=buffer,
        file_name=f"schade_{pdf_coach.replace(' ', '_')}.pdf",
        mime="application/pdf"
    )






# --- TAB 1: Chauffeur ---
with tab1:
    st.subheader("Aantal schadegevallen per chauffeur")
    
    # Keuze voor top X chauffeurs
    top_n_option = st.selectbox("Toon top aantal chauffeurs:", ["10", "20", "50", "Allemaal"])

    # Aantal schadegevallen per chauffeur
    chart_data = df_filtered["volledige naam"].value_counts()
    if top_n_option != "Allemaal":
        chart_data = chart_data.head(int(top_n_option))

    # Horizontale bar chart
    fig, ax = plt.subplots(figsize=(8, len(chart_data) * 0.3 + 1))
    chart_data.sort_values().plot(kind="barh", ax=ax)
    ax.set_xlabel("Aantal schadegevallen")
    ax.set_ylabel("Chauffeur")
    ax.set_title(
        f"Top {top_n_option} schadegevallen per chauffeur" 
        if top_n_option != "Allemaal" else "Alle chauffeurs"
    )
    st.pyplot(fig)

    # Titel voor de accordionlijst
    st.subheader("📂 Schadegevallen per chauffeur")

    # Bepaal welke chauffeurs getoond moeten worden
    top_chauffeurs = chart_data.index.tolist()

    # Filter de schadegevallen met links en datums
    schade_links = df_filtered[
        df_filtered["volledige naam"].isin(top_chauffeurs) & df_filtered["Link"].notna()
    ][["volledige naam", "Datum", "Link"]].sort_values(by="Datum")

    # Maak 1 accordion per chauffeur
    for chauffeur in top_chauffeurs:
        schade_chauffeur = df_filtered[
            (df_filtered["volledige naam"] == chauffeur)
        ][["Datum", "Link"]].sort_values(by="Datum")

        aantal = len(schade_chauffeur)

        with st.expander(f"{chauffeur} — {aantal} schadegevallen"):
            for _, row in schade_chauffeur.iterrows():
                datum_str = (
                    row["Datum"].strftime("%d-%m-%Y")
                    if pd.notna(row["Datum"]) else "onbekend"
                )
                link = row["Link"]

                if pd.notna(link) and isinstance(link, str):
                    st.markdown(f"📅 {datum_str} — [🔗 Link]({link})", unsafe_allow_html=True)
                else:
                    st.markdown(f"📅 {datum_str} — ❌ Geen geldige link")


# --- TAB 2: Teamcoach ---
with tab2:
    st.subheader("Aantal schadegevallen per teamcoach")

    chart_data = df_filtered["teamcoach"].value_counts()

    if chart_data.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        # Bar chart
        fig, ax = plt.subplots(figsize=(8, len(chart_data) * 0.3 + 1))
        chart_data.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen")
        ax.set_ylabel("Teamcoach")
        ax.set_title("Schadegevallen per teamcoach")
        st.pyplot(fig)

        st.subheader("📂 Schadegevallen per teamcoach")

        top_teamcoaches = chart_data.index.tolist()

        for coach in top_teamcoaches:
            schade_per_coach = df_filtered[
                df_filtered["teamcoach"] == coach
            ][["Datum", "Link", "volledige naam"]].sort_values(by="Datum")

            aantal = len(schade_per_coach)

            with st.expander(f"{coach} — {aantal} schadegevallen"):
                for _, row in schade_per_coach.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam"]
                    link = row["Link"]

                    if pd.notna(link) and isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — ❌ Geen geldige link")



    # --- TAB 3: Voertuig ---
    # --- TAB 3: Voertuig ---
    with tab3:
        st.subheader("📈 Schadegevallen per maand per voertuigtype")

        df_per_maand = df_filtered.copy()
        # Maandnummer -> Nederlandstalige naam
        maanden_nl = {
        1: "januari", 2: "februari", 3: "maart", 4: "april", 5: "mei", 6: "juni",
        7: "juli", 8: "augustus", 9: "september", 10: "oktober", 11: "november", 12: "december"
    }
    df_per_maand["Maand"] = df_per_maand["Datum"].dt.month.map(maanden_nl)

    df_per_maand["Maand"] = df_per_maand["Maand"].str.lower()

    maand_volgorde = [
        "januari", "februari", "maart", "april", "mei", "juni",
        "juli", "augustus", "september", "oktober", "november", "december"
    ]

    groep = df_per_maand.groupby(["Maand", "Bus/ Tram"]).size().unstack(fill_value=0)
    groep = groep.reindex(maand_volgorde)

    fig2, ax2 = plt.subplots(figsize=(10, 4))
    groep.plot(ax=ax2, marker="o")
    ax2.set_xlabel("Maand")
    ax2.set_ylabel("Aantal schadegevallen")
    ax2.set_title("Lijngrafiek per maand per voertuigtype")
    ax2.legend(title="Voertuig")
    st.pyplot(fig2)

    st.subheader("Aantal schadegevallen per type voertuig")

   

    chart_data = df_filtered["Bus/ Tram"].value_counts()

    if chart_data.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        # Bar chart
        fig, ax = plt.subplots(figsize=(8, len(chart_data) * 0.3 + 1))
        chart_data.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen")
        ax.set_ylabel("Voertuigtype")
        ax.set_title("Schadegevallen per type voertuig")
        st.pyplot(fig)

        st.subheader("📂 Schadegevallen per voertuigtype")

        top_voertuigen = chart_data.index.tolist()

        for voertuig in top_voertuigen:
            schade_per_voertuig = df_filtered[
                df_filtered["Bus/ Tram"] == voertuig
            ][["Datum", "Link", "volledige naam"]].sort_values(by="Datum")

            aantal = len(schade_per_voertuig)

            with st.expander(f"{voertuig} — {aantal} schadegevallen"):
                for _, row in schade_per_voertuig.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam"]
                    link = row["Link"]

                    if pd.notna(link) and isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — ❌ Geen geldige link")

# --- TAB 4: Locatie ---
with tab4:
    st.subheader("Aantal schadegevallen per locatie")

    # ➕ Keuzemenu voor top X locaties
    top_locatie_option = st.selectbox("Toon top aantal locaties:", ["10", "20", "50", "Allemaal"])

    # Groeperen
    chart_data = df_filtered["Locatie"].value_counts()
    if top_locatie_option != "Allemaal":
        chart_data = chart_data.head(int(top_locatie_option))

    if chart_data.empty:
        st.warning("⚠️ Geen schadegevallen gevonden voor de geselecteerde filters.")
    else:
        # Bar chart
        fig, ax = plt.subplots(figsize=(8, len(chart_data) * 0.3 + 1))
        chart_data.sort_values().plot(kind="barh", ax=ax)
        ax.set_xlabel("Aantal schadegevallen")
        ax.set_ylabel("Locatie")
        ax.set_title(
            f"Top {top_locatie_option} schadegevallen per locatie"
            if top_locatie_option != "Allemaal" else "Schadegevallen per locatie"
        )
        st.pyplot(fig)

        st.subheader("📂 Schadegevallen per locatie")

        top_locaties = chart_data.index.tolist()

        for locatie in top_locaties:
            schade_per_locatie = df_filtered[
                df_filtered["Locatie"] == locatie
            ][["Datum", "Link", "volledige naam"]].sort_values(by="Datum")

            aantal = len(schade_per_locatie)

            with st.expander(f"{locatie} — {aantal} schadegevallen"):
                for _, row in schade_per_locatie.iterrows():
                    datum_str = row["Datum"].strftime("%d-%m-%Y") if pd.notna(row["Datum"]) else "onbekend"
                    chauffeur = row["volledige naam"]
                    link = row["Link"]

                    if pd.notna(link) and isinstance(link, str) and link.startswith(("http://", "https://")):
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — [🔗 Link]({link})", unsafe_allow_html=True)
                    else:
                        st.markdown(f"📅 {datum_str} — 👤 {chauffeur} — ❌ Geen geldige link")
