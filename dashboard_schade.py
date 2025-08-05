import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

# Laad de data
df = pd.read_excel("schade met macro.xlsm", sheet_name="BRON")

# Opschonen
df = df[df["volledige naam"].notna() & (df["volledige naam"] != "9999 - -")]

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

# Filteren
df_filtered = df[
    df["teamcoach"].isin(selected_teamcoaches) &
    df["Bus/ Tram"].isin(selected_voertuigen) &
    df["Locatie"].isin(selected_locaties)
]

# Totaal KPI
st.metric("Totaal aantal schadegevallen", len(df_filtered))

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["👤 Chauffeur", "🧑‍💼 Teamcoach", "🚌 Voertuig", "📍 Locatie"])

# --- TAB 1: Chauffeur ---
with tab1:
    st.subheader("Aantal schadegevallen per chauffeur")

    # Keuzemenu: hoeveel chauffeurs tonen
    top_n_option = st.selectbox("Toon top aantal chauffeurs op basis van schadegevallen:", ["10", "20", "50", "Allemaal"])

    # Data voorbereiden
    chart_data = df_filtered["volledige naam"].value_counts()
    if top_n_option != "Allemaal":
        top_n = int(top_n_option)
        chart_data = chart_data.head(top_n)

    # Grafiek (horizontaal)
    fig, ax = plt.subplots(figsize=(8, len(chart_data) * 0.3 + 1))
    chart_data.sort_values().plot(kind="barh", ax=ax)
    ax.set_xlabel("Aantal schadegevallen")
    ax.set_ylabel("Chauffeur")
    ax.set_title(f"Top {top_n_option} schadegevallen per chauffeur" if top_n_option != "Allemaal" else "Alle chauffeurs")
    st.pyplot(fig)

    # Tabel
    st.dataframe(chart_data.reset_index(name="Aantal").rename(columns={"index": "Chauffeur"}))

# --- TAB 2: Teamcoach ---
with tab2:
    st.subheader("Aantal schadegevallen per teamcoach")
    chart_data = df_filtered["teamcoach"].value_counts()
    st.bar_chart(chart_data)
    st.dataframe(chart_data.rename("Aantal").reset_index(names="Teamcoach"))

# --- TAB 3: Voertuig ---
with tab3:
    st.subheader("Aantal schadegevallen per type voertuig")
    chart_data = df_filtered["Bus/ Tram"].value_counts()
    st.bar_chart(chart_data)
    st.dataframe(chart_data.rename("Aantal").reset_index(names="Voertuig"))

# --- TAB 4: Locatie ---
with tab4:
    st.subheader("Aantal schadegevallen per locatie")
    chart_data = df_filtered["Locatie"].value_counts()
    st.bar_chart(chart_data)
    st.dataframe(chart_data.rename("Aantal").reset_index(names="Locatie"))
