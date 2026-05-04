import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="TED Intelligence", layout="wide")

st.title("📊 TED Tender Intelligence")

FILE = "ted_tenders.xlsx"

if not os.path.exists(FILE):
    st.error("ted_tenders.xlsx not found")
    st.stop()

xls = pd.ExcelFile(FILE)
st.caption(f"Available sheets: {', '.join(xls.sheet_names)}")

if "Live Opportunities" in xls.sheet_names:
    live = pd.read_excel(FILE, sheet_name="Live Opportunities")
    st.subheader("🟢 Live Opportunities")
    st.dataframe(live, use_container_width=True)
else:
    st.warning("No Live Opportunities sheet found.")

if "Market Intelligence" in xls.sheet_names:
    intel = pd.read_excel(FILE, sheet_name="Market Intelligence")
    st.subheader("📊 Market Intelligence")
    st.dataframe(intel, use_container_width=True)
else:
    st.info("No Market Intelligence results in this run.")
