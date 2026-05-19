import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(
    page_title="TED Intelligence — DevelopMinded",
    page_icon="🔍",
    layout="wide"
)

st.markdown("# 🔍 TED Tender Intelligence")
st.caption("DevelopMinded — live EU procurement opportunities")

CSV_FILE = "ted_results.csv"

@st.cache_data(ttl=300)
def load_data():
    try:
        df = pd.read_csv(CSV_FILE)
        df["fetched_date"] = pd.to_datetime(df["fetched_date"], errors="coerce")
        if "value" in df.columns:
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
        if "score" in df.columns:
            df["score"] = pd.to_numeric(df["score"], errors="coerce")
        return df
    except FileNotFoundError:
        return pd.DataFrame()

df = load_data()

if df.empty:
    st.warning("No data yet. The daily fetch hasn't run or the CSV is missing.")
    st.stop()

# ── Split into buckets ────────────────────────────────────────
live     = df[df["bucket"] == "Live opportunity"].copy()
possible = df[df["bucket"] == "Possible opportunity"].copy()
intel    = df[df["bucket"] == "Market intelligence"].copy()
all_live = df[df["bucket"].isin(["Live opportunity", "Possible opportunity"])].copy()

# ── Last updated ──────────────────────────────────────────────
last_run = df["fetched_date"].max()
last_run_str = last_run.strftime("%Y-%m-%d") if pd.notna(last_run) else "—"
st.caption(f"Last updated: **{last_run_str}**")

# ── KPIs ──────────────────────────────────────────────────────
today = datetime.now().strftime("%Y-%m-%d")
open_dl = all_live[all_live["deadline"] > today] if "deadline" in all_live.columns else pd.DataFrame()
high_rel = all_live[all_live["score"] >= 10] if "score" in all_live.columns else pd.DataFrame()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("🟢 Live", len(live))
k2.metric("🟡 Possible", len(possible))
k3.metric("📊 Market intel", len(intel))
k4.metric("High relevance (≥10)", len(high_rel))
k5.metric("Open deadlines", len(open_dl))

st.divider()

# ── DEADLINE ALERTS ───────────────────────────────────────────
warn_cutoff = (pd.Timestamp.now() + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
if "deadline" in all_live.columns:
    urgent = all_live[
        (all_live["deadline"] != "—") &
        (all_live["deadline"] <= warn_cutoff) &
        (all_live["deadline"] >= today)
    ].sort_values("deadline")
    if not urgent.empty:
        st.warning(f"⏰ {len(urgent)} opportunity/ies with deadline within 7 days")
        for _, r in urgent.iterrows():
            icon  = "🟢" if r["bucket"] == "Live opportunity" else "🟡"
            link  = r.get("link", "")
            title = str(r["title"])[:90]
            st.markdown(
                f"- {icon} **[{title}]({link})** — deadline **{r['deadline']}** | score {r['score']}"
            )
        st.divider()

# ── SIDEBAR FILTERS ───────────────────────────────────────────
with st.sidebar:
    st.markdown("## Filters")
    search    = st.text_input("🔍 Search title / buyer")
    min_score = st.slider("Min score", 1, 30, 3)

    if "country" in df.columns:
        country_opts = ["All"] + sorted(
            df["country"].dropna().replace("", pd.NA).dropna().unique().tolist()
        )
        country_filt = st.selectbox("Country", country_opts)
    else:
        country_filt = "All"

    date_opts = ["All time"] + sorted(
        df["fetched_date"].dt.date.astype(str).unique().tolist(), reverse=True
    )
    date_filt = st.selectbox("Fetched on", date_opts)
    sort_by   = st.selectbox("Sort by", ["Score (high→low)", "Newest fetch", "Deadline"])

# ── FILTER FUNCTION ───────────────────────────────────────────
def apply_filters(view: pd.DataFrame) -> pd.DataFrame:
    if view.empty:
        return view
    view = view[view["score"] >= min_score].copy()
    if search:
        mask = (
            view["title"].str.contains(search, case=False, na=False) |
            view["buyer"].str.contains(search, case=False, na=False)
        )
        view = view[mask]
    if country_filt != "All" and "country" in view.columns:
        view = view[view["country"] == country_filt]
    if date_filt != "All time":
        view = view[view["fetched_date"].dt.date.astype(str) == date_filt]
    if sort_by == "Score (high→low)":
        view = view.sort_values("score", ascending=False)
    elif sort_by == "Newest fetch":
        view = view.sort_values("fetched_date", ascending=False)
    elif sort_by == "Deadline" and "deadline" in view.columns:
        view = view[view["deadline"] != "—"].sort_values("deadline")
    return view.reset_index(drop=True)

# ── COLUMN CONFIG ─────────────────────────────────────────────
def col_config(df):
    cfg = {
        "link":  st.column_config.LinkColumn("Link", display_text="View ↗"),
        "score": st.column_config.NumberColumn("Score", format="%d ⭐"),
    }
    if "value" in df.columns:
        cfg["value"] = st.column_config.NumberColumn("Value", format="€%,.0f")
    return cfg

# ── DISPLAY COLUMNS ───────────────────────────────────────────
live_cols = [c for c in
    ["score", "deadline", "title", "buyer", "country",
     "value", "currency", "duration", "languages",
     "notice_type", "t1_hits", "description", "link"]
    if c in df.columns]

intel_cols = [c for c in
    ["score", "deadline", "title", "buyer", "country",
     "value", "currency", "notice_type", "t1_hits", "link"]
    if c in df.columns]

def prep_description(view: pd.DataFrame) -> pd.DataFrame:
    """Truncate description to a readable preview length."""
    if "description" in view.columns:
        view = view.copy()
        view["description"] = view["description"].fillna("").apply(
            lambda x: x[:200] + "…" if len(x) > 200 else x
        )
    return view

# ── TABS ──────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    f"🟢 Live Opportunities ({len(live)})",
    f"🟡 Possible Opportunities ({len(possible)})",
    f"📊 Market Intelligence ({len(intel)})",
])

# ── TAB 1: LIVE ───────────────────────────────────────────────
with tab1:
    view = apply_filters(live)

    if view.empty:
        st.info("No live opportunities match your filters. Try lowering the minimum score.")
    else:
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.caption(f"Showing **{len(view)}** of {len(live)} live opportunities")
        with col_b:
            st.download_button(
                "⬇️ Download CSV",
                data=view[live_cols].to_csv(index=False).encode(),
                file_name=f"ted_live_{today}.csv",
                mime="text/csv",
            )

        # Score distribution
        with st.expander("📊 Score distribution", expanded=False):
            bins = pd.cut(
                view["score"],
                bins=[0, 6, 9, 14, 100],
                labels=["4–6", "7–9", "10–14", "15+"]
            )
            chart_data = bins.value_counts().sort_index().rename("notices")
            st.bar_chart(chart_data)

        st.dataframe(
            prep_description(view)[live_cols].reset_index(drop=True),
            use_container_width=True,
            height=520,
            column_config=col_config(view),
        )

# ── TAB 2: POSSIBLE ───────────────────────────────────────────
with tab2:
    view = apply_filters(possible)

    if view.empty:
        st.info("No possible opportunities match your filters. Try lowering the minimum score.")
    else:
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.caption(f"Showing **{len(view)}** of {len(possible)} possible opportunities")
        with col_b:
            st.download_button(
                "⬇️ Download CSV",
                data=view[live_cols].to_csv(index=False).encode(),
                file_name=f"ted_possible_{today}.csv",
                mime="text/csv",
            )

        st.dataframe(
            prep_description(view)[live_cols].reset_index(drop=True),
            use_container_width=True,
            height=520,
            column_config=col_config(view),
        )

# ── TAB 3: MARKET INTELLIGENCE ────────────────────────────────
with tab3:
    if intel.empty:
        st.info("No market intelligence data yet.")
    else:
        view = intel.copy()
        if search:
            mask = (
                view["title"].str.contains(search, case=False, na=False) |
                view["buyer"].str.contains(search, case=False, na=False)
            )
            view = view[mask]
        if country_filt != "All" and "country" in view.columns:
            view = view[view["country"] == country_filt]
        view = view[view["score"] >= min_score]

        st.caption(
            f"Showing **{len(view)}** awarded contracts — use as buyer & budget intelligence"
        )

        # Value summary if data available
        if "value" in view.columns and view["value"].notna().any():
            v1, v2, v3 = st.columns(3)
            v1.metric("Avg contract value", f"€{view['value'].mean():,.0f}")
            v2.metric("Max contract value", f"€{view['value'].max():,.0f}")
            v3.metric("Total awarded value", f"€{view['value'].sum():,.0f}")

        st.dataframe(
            view[intel_cols].sort_values("score", ascending=False).reset_index(drop=True),
            use_container_width=True,
            height=520,
            column_config=col_config(view),
        )
        st.download_button(
            "⬇️ Download CSV",
            data=view[intel_cols].to_csv(index=False).encode(),
            file_name=f"ted_intel_{today}.csv",
            mime="text/csv",
        )
