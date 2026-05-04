import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="TED Intelligence", layout="wide")

FILE = "ted_tenders.xlsx"

st.title("📊 TED Tender Intelligence")

# Check if file exists
if not os.path.exists(FILE):
    st.warning("No data yet — wait for GitHub Action to run.")
    st.stop()

# Load data
live = pd.read_excel(FILE, sheet_name="Live Opportunities")
intel = pd.read_excel(FILE, sheet_name="Market Intelligence")

# Tabs
tab1, tab2 = st.tabs(["🟢 Live Opportunities", "📊 Market Intelligence"])

with tab1:
    st.dataframe(live, use_container_width=True)

with tab2:
    st.dataframe(intel, use_container_width=True)
