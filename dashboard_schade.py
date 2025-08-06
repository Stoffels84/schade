import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

# --- Laad de data vóór je filters toont ---
df = pd.read_excel("schade met macro.xlsm", sheet_name="BRON")
df = df[df["volledige naam"].notna() & (df["volledige naam"] != "9999 - -")]
df["Datum"] = pd.to_datetime(df["Datum"], errors="coerce")
df = df[df["Datum"].notna()]
df["Kwartaal"] = df["Datum"].dt.to_period("Q").astype(str)

# --- Dan pas: Filters (zoals multiselect met df) ---
with st.sidebar:
    st.header("🔍 Filters")
    selected_teamcoaches = st.multiselect("Teamcoach", options=df["teamcoach"].dropna().unique())


    selected_teamcoaches = st.multiselect(
        "Teamcoach",
        options=df["teamcoach"].dropna().unique(),
        default=df["teamcoach"].dropna().unique()
    )

    selected_voertuigen = st.multiselect(
        "Voertuigtype",
        options=df["Bus/ Tram"].dropna().unique(),
        default=df["Bus/ Tram"].dropna().unique()
    )

    selected_locaties = st.multiselect(
        "Locatie",
        options=df["Locatie"].dropna().unique(),
        default=df["Locatie"].dropna().unique()
    )

    kwartaal_opties = sorted(df["Kwartaal"].dropna().unique())
    selected_kwartalen = st.multiselect(
        "Kwartaal",
        options=kwartaal_opties,
        default=kwartaal_opties
    )

    st.markdown("---")
    st.subheader("📄 PDF Export per teamcoach")

    pdf_coach = st.selectbox("Kies teamcoach voor export", df["teamcoach"].dropna().unique())
    generate_pdf = st.button("Genereer PDF")

    if generate_pdf:
        # Filter data voor PDF
        schade_pdf = df[df["teamcoach"] == pdf_coach][["Datum", "volledige naam", "Locatie", "Bus/ Tram", "Link"]]
        schade_pdf = schade_pdf.sort_values(by="Datum")

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph(f"Overzicht schadegevallen - Teamcoach: <b>{pdf_coach}</b>", styles["Title"]))
        elements.append(Spacer(1, 12))

        # Aantal schadegevallen per chauffeur
        chauffeurs = schade_pdf["volledige naam"].value_counts().reset_index()
        chauffeurs.columns = ["Chauffeur", "Aantal"]
        table_data = [["Chauffeur", "Aantal"]] + chauffeurs.values.tolist()
        table = Table(table_data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(Paragraph("Aantal schadegevallen per chauffeur:", styles["Heading2"]))
        elements.append(table)
        elements.append(Spacer(1, 12))

        # Aantal per locatie
        locaties = schade_pdf["Locatie"].value_counts().reset_index()
        locaties.columns = ["Locatie", "Aantal"]
        loc_data = [["Locatie", "Aantal"]] + locaties.values.tolist()
        loc_table = Table(loc_data)
        loc_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(Paragraph("Aantal schadegevallen per locatie:", styles["Heading2"]))
        elements.append(loc_table)
        elements.append(Spacer(1, 12))

        # Aantal per maand (grafiek)
        schade_pdf["Maand"] = schade_pdf["Datum"].dt.to_period("M")
        per_maand = schade_pdf["Maand"].value_counts().sort_index()
        per_maand.index = per_maand.index.astype(str)

        fig, ax = plt.subplots(figsize=(6, 3))
        per_maand.plot(kind="bar", ax=ax)
        ax.set_title("Aantal schadegevallen per maand")
        ax.set_ylabel("Aantal")
        ax.set_xlabel("Maand")
        plt.tight_layout()

        img_buffer = BytesIO()
        plt.savefig(img_buffer, format="png")
        plt.close(fig)
        img_buffer.seek(0)

        elements.append(Paragraph("📊 Schadegevallen per maand:", styles["Heading2"]))
        elements.append(Image(img_buffer, width=400, height=200))
        elements.append(Spacer(1, 12))

        # PDF bouwen en download aanbieden
        doc.build(elements)
        buffer.seek(0)

        st.download_button(
            label="📥 Download PDF",
            data=buffer,
            file_name=f"schade_{pdf_coach.replace(' ', '_')}.pdf",
            mime="application/pdf"
        )





# KPI
st.metric("Totaal aantal schadegevallen", len(df_filtered))

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["👤 Chauffeur", "🧑‍💼 Teamcoach", "🚌 Voertuig", "📍 Locatie"])

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
with tab3:
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
