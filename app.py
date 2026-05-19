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

CSV_FILE     = "ted_results.csv"
REVIEWS_FILE = "reviews.csv"
WARN_DAYS    = 14

# ── Load data ─────────────────────────────────────────────────
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

def load_reviews() -> set:
    try:
        return set(pd.read_csv(REVIEWS_FILE)["pub_num"].astype(str).tolist())
    except FileNotFoundError:
        return set()

def save_reviews(reviewed: set):
    pd.DataFrame({"pub_num": sorted(reviewed)}).to_csv(REVIEWS_FILE, index=False)

df = load_data()

if df.empty:
    st.warning("No data yet. The daily fetch hasn't run or the CSV is missing.")
    st.stop()

# ── Session state for reviews ─────────────────────────────────
if "reviewed" not in st.session_state:
    st.session_state.reviewed = load_reviews()

# ── Classify into display buckets ─────────────────────────────
# Planning = Live/Possible with no deadline (PIN notices, upcoming tenders)
# Open     = Live/Possible with a future deadline
# Closed   = Awarded contracts (was "Market intelligence")

live_possible = df[df["bucket"].isin(["Live opportunity", "Possible opportunity"])].copy()
planning = live_possible[live_possible["deadline"] == "—"].copy()
open_    = live_possible[live_possible["deadline"] != "—"].copy()
closed   = df[df["bucket"] == "Market intelligence"].copy()

# ── Last updated ──────────────────────────────────────────────
last_run = df["fetched_date"].max()
last_run_str = last_run.strftime("%Y-%m-%d") if pd.notna(last_run) else "—"
st.caption(f"Last updated: **{last_run_str}**")

# ── KPIs ──────────────────────────────────────────────────────
today = datetime.now().strftime("%Y-%m-%d")
warn_cutoff = (pd.Timestamp.now() + pd.Timedelta(days=WARN_DAYS)).strftime("%Y-%m-%d")

open_deadlines = open_[
    (open_["deadline"] != "—") &
    (open_["deadline"] >= today)
] if "deadline" in open_.columns else pd.DataFrame()

high_rel = live_possible[live_possible["score"] >= 10]

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("📋 Planning",         len(planning))
k2.metric("🟢 Open",             len(open_))
k3.metric("📁 Closed",           len(closed))
k4.metric("High relevance (≥10)", len(high_rel))
k5.metric("Deadlines ≤14 days",  len(open_deadlines[open_deadlines["deadline"] <= warn_cutoff]))

st.divider()

# ── DEADLINE ALERTS ───────────────────────────────────────────
if "deadline" in open_.columns:
    urgent = open_[
        (open_["deadline"] != "—") &
        (open_["deadline"] <= warn_cutoff) &
        (open_["deadline"] >= today)
    ].sort_values("deadline")
    if not urgent.empty:
        st.warning(f"⏰ {len(urgent)} opportunity/ies with deadline within {WARN_DAYS} days")
        for _, r in urgent.iterrows():
            icon  = "🟢" if r["bucket"] == "Live opportunity" else "🟡"
            link  = r.get("link", "")
            title = str(r["title"])[:90]
            reviewed_mark = " ✓" if str(r["pub_num"]) in st.session_state.reviewed else ""
            st.markdown(
                f"- {icon} **[{title}]({link})**{reviewed_mark} "
                f"— deadline **{r['deadline']}** | score {r['score']}"
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

    st.divider()
    hide_reviewed = st.toggle("Hide reviewed", value=False)

    st.divider()
    st.caption(f"✓ {len(st.session_state.reviewed)} notices marked reviewed")
    if st.button("Clear all reviews"):
        st.session_state.reviewed = set()
        save_reviews(set())
        st.rerun()

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
    if hide_reviewed:
        view = view[~view["pub_num"].astype(str).isin(st.session_state.reviewed)]
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
        "reviewed": st.column_config.CheckboxColumn("✓ Reviewed", default=False, width="small"),
        "link":     st.column_config.LinkColumn("Link", display_text="View ↗"),
        "score":    st.column_config.NumberColumn("Score", format="%d ⭐"),
    }
    if "value" in df.columns:
        cfg["value"] = st.column_config.NumberColumn("Value", format="€%,.0f")
    return cfg

# ── DISPLAY COLUMNS ───────────────────────────────────────────
base_cols = [c for c in
    ["reviewed", "score", "deadline", "title", "buyer", "country",
     "value", "currency", "duration", "languages",
     "notice_type", "t1_hits", "description", "link"]
    if c in df.columns or c == "reviewed"]

intel_cols = [c for c in
    ["reviewed", "score", "deadline", "title", "buyer", "country",
     "value", "currency", "notice_type", "t1_hits", "link"]
    if c in df.columns or c == "reviewed"]

def prep_description(view: pd.DataFrame) -> pd.DataFrame:
    if "description" in view.columns:
        view = view.copy()
        view["description"] = view["description"].fillna("").apply(
            lambda x: x[:200] + "…" if len(x) > 200 else x
        )
    return view

# ── INTERACTIVE TABLE ─────────────────────────────────────────
def show_table(view: pd.DataFrame, cols: list, tab_key: str):
    """Render an editable table with review checkboxes and persist changes."""
    if view.empty:
        st.info("No notices match your filters. Try lowering the minimum score.")
        return

    # Inject reviewed column
    view = view.copy()
    view["reviewed"] = view["pub_num"].astype(str).isin(st.session_state.reviewed)

    # Only keep columns that exist
    display_cols = [c for c in cols if c in view.columns]

    edited = st.data_editor(
        prep_description(view)[display_cols].reset_index(drop=True),
        column_config=col_config(view),
        disabled=[c for c in display_cols if c != "reviewed"],
        use_container_width=True,
        height=520,
        key=f"editor_{tab_key}",
    )

    # Persist review changes
    if "reviewed" in edited.columns and "pub_num" in view.columns:
        pub_nums = view["pub_num"].astype(str).tolist()
        for i, is_reviewed in enumerate(edited["reviewed"]):
            if i < len(pub_nums):
                pn = pub_nums[i]
                if is_reviewed:
                    st.session_state.reviewed.add(pn)
                else:
                    st.session_state.reviewed.discard(pn)
        save_reviews(st.session_state.reviewed)

# ── TABS ──────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    f"📋 Planning ({len(planning)})",
    f"🟢 Open ({len(open_)})",
    f"📁 Closed ({len(closed)})",
])

# ── TAB 1: PLANNING ───────────────────────────────────────────
with tab1:
    view = apply_filters(planning)
    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.caption(
            f"Showing **{len(view)}** of {len(planning)} planning notices "
            f"— no submission deadline set yet (PIN / prior information notices)"
        )
    with col_b:
        if not view.empty:
            st.download_button(
                "⬇️ Download CSV",
                data=view.to_csv(index=False).encode(),
                file_name=f"ted_planning_{today}.csv",
                mime="text/csv",
            )

    with st.expander("📊 Score distribution", expanded=False):
        if not view.empty:
            bins = pd.cut(view["score"], bins=[0,6,9,14,100], labels=["4–6","7–9","10–14","15+"])
            st.bar_chart(bins.value_counts().sort_index().rename("notices"))

    show_table(view, base_cols, "planning")

# ── TAB 2: OPEN ───────────────────────────────────────────────
with tab2:
    view = apply_filters(open_)
    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.caption(f"Showing **{len(view)}** of {len(open_)} open opportunities")
    with col_b:
        if not view.empty:
            st.download_button(
                "⬇️ Download CSV",
                data=view.to_csv(index=False).encode(),
                file_name=f"ted_open_{today}.csv",
                mime="text/csv",
            )

    with st.expander("📊 Score distribution", expanded=False):
        if not view.empty:
            bins = pd.cut(view["score"], bins=[0,6,9,14,100], labels=["4–6","7–9","10–14","15+"])
            st.bar_chart(bins.value_counts().sort_index().rename("notices"))

    show_table(view, base_cols, "open")

# ── TAB 3: CLOSED ─────────────────────────────────────────────
with tab3:
    if closed.empty:
        st.info("No closed/awarded contracts yet.")
    else:
        view = closed.copy()
        if search:
            mask = (
                view["title"].str.contains(search, case=False, na=False) |
                view["buyer"].str.contains(search, case=False, na=False)
            )
            view = view[mask]
        if country_filt != "All" and "country" in view.columns:
            view = view[view["country"] == country_filt]
        view = view[view["score"] >= min_score]
        if hide_reviewed:
            view = view[~view["pub_num"].astype(str).isin(st.session_state.reviewed)]

        st.caption(
            f"Showing **{len(view)}** awarded contracts "
            f"— use for buyer research and budget benchmarking"
        )

        if "value" in view.columns and view["value"].notna().any():
            v1, v2, v3 = st.columns(3)
            v1.metric("Avg contract value", f"€{view['value'].mean():,.0f}")
            v2.metric("Max contract value", f"€{view['value'].max():,.0f}")
            v3.metric("Total awarded value", f"€{view['value'].sum():,.0f}")
            st.write("")

        show_table(view, intel_cols, "closed")

        if not view.empty:
            st.download_button(
                "⬇️ Download CSV",
                data=view.to_csv(index=False).encode(),
                file_name=f"ted_closed_{today}.csv",
                mime="text/csv",
            )
