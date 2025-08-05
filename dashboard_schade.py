import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

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

# KPI
st.metric("Totaal aantal schadegevallen", len(df_filtered))

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["👤 Chauffeur", "🧑‍💼 Teamcoach", "🚌 Voertuig", "📍 Locatie"])

# --- TAB 1: Chauffeur ---
with tab1:
    st.subheader("Aantal schadegevallen per chauffeur")
    top_n_option = st.selectbox("Toon top aantal chauffeurs:", ["10", "20", "50", "Allemaal"])

    chart_data = df_filtered["volledige naam"].value_counts()
    if top_n_option != "Allemaal":
        chart_data = chart_data.head(int(top_n_option))

    fig, ax = plt.subplots(figsize=(8, len(chart_data) * 0.3 + 1))
    chart_data.sort_values().plot(kind="barh", ax=ax)
    ax.set_xlabel("Aantal schadegevallen")
    ax.set_ylabel("Chauffeur")
    ax.set_title(f"Top {top_n_option} schadegevallen per chauffeur" if top_n_option != "Allemaal" else "Alle chauffeurs")
    st.pyplot(fig)

    st.dataframe(chart_data.reset_index(name="Aantal").rename(columns={"index": "Chauffeur"}))

# --- TAB 2: Teamcoach ---
with tab2:
    st.subheader("Aantal schadegevallen per teamcoach")
    chart_data = df_filtered["teamcoach"].value_counts()

    fig, ax = plt.subplots(figsize=(8, len(chart_data) * 0.3 + 1))
    chart_data.sort_values().plot(kind="barh", ax=ax)
    ax.set_xlabel("Aantal schadegevallen")
    ax.set_ylabel("Teamcoach")
    ax.set_title("Schadegevallen per teamcoach")
    st.pyplot(fig)

    st.dataframe(chart_data.reset_index(name="Aantal").rename(columns={"index": "Teamcoach"}))

# --- TAB 3: Voertuig ---
with tab3:
    st.subheader("Aantal schadegevallen per type voertuig")
    chart_data = df_filtered["Bus/ Tram"].value_counts()

    fig, ax = plt.subplots(figsize=(8, len(chart_data) * 0.3 + 1))
    chart_data.sort_values().plot(kind="barh", ax=ax)
    ax.set_xlabel("Aantal schadegevallen")
    ax.set_ylabel("Voertuigtype")
    ax.set_title("Schadegevallen per type voertuig")
    st.pyplot(fig)

    st.dataframe(chart_data.reset_index(name="Aantal").rename(columns={"index": "Voertuig"}))

# --- TAB 4: Locatie ---
with tab4:
    st.subheader("Aantal schadegevallen per locatie")
    top_loc_option = st.selectbox("Toon top aantal locaties:", ["10", "20", "50", "Allemaal"])

    chart_data = df_filtered["Locatie"].value_counts()
    if top_loc_option != "Allemaal":
        chart_data = chart_data.head(int(top_loc_option))

    fig, ax = plt.subplots(figsize=(8, len(chart_data) * 0.3 + 1))
    chart_data.sort_values().plot(kind="barh", ax=ax)
    ax.set_xlabel("Aantal schadegevallen")
    ax.set_ylabel("Locatie")
    ax.set_title(f"Top {top_loc_option} schadegevallen per locatie" if top_loc_option != "Allemaal" else "Alle locaties")
    st.pyplot(fig)

    st.dataframe(chart_data.reset_index(name="Aantal").rename(columns={"index": "Locatie"}))
