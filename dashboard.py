import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

# Upload Excel
df = pd.read_excel("schadegevallen.xlsx", parse_dates=["Datum"])

# Filters
st.sidebar.header("Filters")
locaties = st.sidebar.multiselect("Locatie", options=df["Locatie"].unique(), default=df["Locatie"].unique())
statussen = st.sidebar.multiselect("Status", options=df["Status"].unique(), default=df["Status"].unique())

# Filter de data
filtered_df = df[(df["Locatie"].isin(locaties)) & (df["Status"].isin(statussen))]

# Aantal schadegevallen per maand
df['Maand'] = df['Datum'].dt.to_period('M')
maand_count = filtered_df.groupby('Maand').size()

# Schadebedrag per type
bedrag_per_type = filtered_df.groupby("Type")["Schadebedrag"].sum()

# Layout
st.title("Dashboard Schadegevallen")
st.subheader("Aantal schadegevallen per maand")
st.line_chart(maand_count)

st.subheader("Totaal schadebedrag per type")
st.bar_chart(bedrag_per_type)

st.subheader("Tabel met openstaande schadegevallen")
st.dataframe(filtered_df[filtered_df["Status"] != "Afgehandeld"])

