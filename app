import streamlit as st
import pandas as pd

st.set_page_config(page_title="TED Tender Intelligence", layout="wide")

st.title("📊 TED Tender Intelligence — DevelopMinded")

FILE = "ted_tenders.xlsx"

try:
    live = pd.read_excel(FILE, sheet_name="Live Opportunities")
    intel = pd.read_excel(FILE, sheet_name="Market Intelligence")

    st.subheader("🟢 Live Opportunities")
    st.dataframe(live, use_container_width=True)

    st.subheader("📊 Market Intelligence")
    st.dataframe(intel, use_container_width=True)

except Exception as e:
    st.warning("No data yet. Run the GitHub Action first.")
    st.caption(str(e))
