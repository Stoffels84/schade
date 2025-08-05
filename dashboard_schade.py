import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

# Laad de data
df = pd.read_excel("schade met macro.xlsm", sheet_name="BRON")

# Opschonen
df = df[df["volledige naam"].notna() & (df["volledige naam"] != "9999 - -")]

# Titel
st.title("📊 Schadegevallen Dashboard")

# Filters
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

# Filter de dataframe
df_filtered = df[
    df["teamcoach"].isin(selected_teamcoaches) &
    df["Bus/ Tram"].isin(selected_voertuigen) &
    df["Locatie"].isin(selected_locaties)
]

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["👤 Chauffeur", "🧑‍💼 Teamcoach", "🚌 Voertuig", "📍 Locatie"])

with tab1:
    st.subheader("Aantal schadegevallen per chauffeur")
    st.bar_chart(df_filtered["volledige naam"].value_counts())

with tab2:
    st.subheader("Aantal schadegevallen per teamcoach")
    st.bar_chart(df_filtered["teamcoach"].value_counts())

with tab3:
    st.subheader("Aantal schadegevallen per type voertuig")
    st.bar_chart(df_filtered["Bus/ Tram"].value_counts())

with tab4:
    st.subheader("Aantal schadegevallen per locatie")
    st.bar_chart(df_filtered["Locatie"].value_counts())
