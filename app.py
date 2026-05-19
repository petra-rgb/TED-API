
import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="TED Intelligence — DevelopMinded",
                   page_icon="🔍", layout="wide")

st.markdown("# 🔍 TED Tender Intelligence")
st.caption("DevelopMinded — live EU procurement opportunities")

CSV_FILE = "ted_results.csv"

@st.cache_data(ttl=300)   # refresh every 5 min
def load_data():
    try:
        df = pd.read_csv(CSV_FILE)
        df["fetched_date"] = pd.to_datetime(df["fetched_date"], errors="coerce")
        return df
    except FileNotFoundError:
        return pd.DataFrame()

df = load_data()

if df.empty:
    st.warning("No data yet. The daily fetch hasn't run or the CSV is missing.")
    st.stop()

# ── Split into live and intel ─────────────────────────────────
live  = df[df["bucket"].isin(["Live opportunity", "Possible opportunity"])].copy()
intel = df[df["bucket"] == "Market intelligence"].copy()

# ── KPIs ──────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
today = datetime.now().strftime("%Y-%m-%d")
k1.metric("Live opportunities", len(live))
k2.metric("Market intelligence", len(intel))
k3.metric("High relevance (score ≥ 10)", len(live[live["score"] >= 10]))
open_dl = live[live["deadline"] > today] if "deadline" in live.columns else pd.DataFrame()
k4.metric("Open deadline", len(open_dl))

st.divider()

# ── LIVE OPPORTUNITIES ────────────────────────────────────────
st.subheader("🟢 Live Opportunities")

if live.empty:
    st.info("No live opportunities found yet.")
else:
    # Sidebar filters
    with st.sidebar:
        st.markdown("## Filters")
        search    = st.text_input("Search title / buyer")
        min_score = st.slider("Min score", 1, 30, 3)
        date_opts = ["All time"] + sorted(
            live["fetched_date"].dt.date.astype(str).unique().tolist(), reverse=True)
        date_filt = st.selectbox("Fetched on", date_opts)
        sort_by   = st.selectbox("Sort by", ["Score (high→low)", "Newest fetch", "Deadline"])

    view = live[live["score"] >= min_score].copy()

    if search:
        mask = (
            view["title"].str.contains(search, case=False, na=False) |
            view["buyer"].str.contains(search, case=False, na=False)
        )
        view = view[mask]

    if date_filt != "All time":
        view = view[view["fetched_date"].dt.date.astype(str) == date_filt]

    if sort_by == "Score (high→low)":
        view = view.sort_values("score", ascending=False)
    elif sort_by == "Newest fetch":
        view = view.sort_values("fetched_date", ascending=False)
    elif sort_by == "Deadline" and "deadline" in view.columns:
        view = view[view["deadline"] != "—"].sort_values("deadline")

    # Remove internal columns from display
    display_cols = [c for c in
        ["score", "bucket", "deadline", "title", "buyer",
         "notice_type", "t1_hits", "fetched_date", "description", "value", "currency", "language","link"]
        if c in view.columns]

    st.caption(f"Showing {len(view)} of {len(live)} opportunities")
    st.dataframe(
        view[display_cols].reset_index(drop=True),
        use_container_width=True,
        height=500,
        column_config={
            "link": st.column_config.LinkColumn("Link", display_text="View ↗"),
            "score": st.column_config.NumberColumn("Score", format="%d ⭐"),
        }
    )

    # CSV download
    st.download_button(
        "⬇️ Download CSV",
        data=view[display_cols].to_csv(index=False).encode(),
        file_name=f"ted_live_{today}.csv",
        mime="text/csv",
    )

# ── MARKET INTELLIGENCE ───────────────────────────────────────
with st.expander(f"📊 Market Intelligence ({len(intel)} awarded contracts)"):
    if intel.empty:
        st.info("No market intelligence data yet.")
    else:
        intel_cols = [c for c in
            ["score", "deadline", "title", "buyer",
             "notice_type", "t1_hits", "fetched_date", "link"]
            if c in intel.columns]
        st.dataframe(
            intel[intel_cols].sort_values("score", ascending=False).reset_index(drop=True),
            use_container_width=True,
            column_config={
                "link": st.column_config.LinkColumn("Link", display_text="View ↗"),
            }
        )
