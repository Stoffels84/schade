import streamlit as st

st.set_page_config(page_title="Schadeportaal", page_icon="🚐")

st.title("Welkom bij het Schadeportaal")
st.write("Klik op de knop hieronder om verder te gaan naar de nieuwe pagina.")

# Knop naar de externe website
if st.button("➡️ Ga naar schade.borolo.be"):
    st.markdown(
        """
        <meta http-equiv="refresh" content="0; url=https://schade.borolo.be" />
        """,
        unsafe_allow_html=True
    )

st.info("Dit is een tussenpagina. Klik op de knop om verder te gaan.")
