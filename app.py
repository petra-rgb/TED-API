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

STATUS_OPTIONS = ["Reviewed", "Not a match", "In process of applying"]

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

def load_reviews() -> dict:
    try:
        rv = pd.read_csv(REVIEWS_FILE)
        if "status" not in rv.columns:
            return {str(pn): "Reviewed" for pn in rv["pub_num"]}
        return dict(zip(rv["pub_num"].astype(str), rv["status"]))
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return {}

def save_reviews(reviews: dict):
    pd.DataFrame([
        {"pub_num": k, "status": v} for k, v in reviews.items()
    ]).to_csv(REVIEWS_FILE, index=False)

df = load_data()

if df.empty:
    st.warning("No data yet. The daily fetch hasn't run or the CSV is missing.")
    st.stop()

# ── Session state ─────────────────────────────────────────────
if "reviews" not in st.session_state:
    st.session_state.reviews = load_reviews()

reviews = st.session_state.reviews   # shorthand

# ── Classify into display buckets ─────────────────────────────
live_possible = df[df["bucket"].isin(["Live opportunity", "Possible opportunity"])].copy()
planning = live_possible[live_possible["deadline"] == "—"].copy()
open_    = live_possible[live_possible["deadline"] != "—"].copy()
closed   = df[df["bucket"] == "Market intelligence"].copy()

# Reviewed = any notice that has been marked (from any bucket)
reviewed_pubs    = set(reviews.keys())
in_process_count = sum(1 for s in reviews.values() if s == "In process of applying")
no_match_count   = sum(1 for s in reviews.values() if s == "Not a match")

# ── Last updated ──────────────────────────────────────────────
last_run = df["fetched_date"].max()
last_run_str = last_run.strftime("%Y-%m-%d") if pd.notna(last_run) else "—"
st.caption(f"Last updated: **{last_run_str}**")

# ── KPIs ──────────────────────────────────────────────────────
today       = datetime.now().strftime("%Y-%m-%d")
warn_cutoff = (pd.Timestamp.now() + pd.Timedelta(days=WARN_DAYS)).strftime("%Y-%m-%d")

open_deadlines = open_[
    (open_["deadline"] != "—") & (open_["deadline"] >= today)
] if "deadline" in open_.columns else pd.DataFrame()

urgent_count = len(open_deadlines[open_deadlines["deadline"] <= warn_cutoff])

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("📋 Planning",            len(planning))
k2.metric("🟢 Open",                len(open_))
k3.metric("📁 Closed",              len(closed))
k4.metric(f"⏰ Deadline ≤{WARN_DAYS}d", urgent_count)
k5.metric("🔄 In process",          in_process_count)
k6.metric("✓ Reviewed",             len(reviewed_pubs))

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
            icon   = "🟢" if r["bucket"] == "Live opportunity" else "🟡"
            link   = r.get("link", "")
            title  = str(r["title"])[:90]
            status = reviews.get(str(r["pub_num"]), "")
            status_badge = f" · *{status}*" if status else ""
            st.markdown(
                f"- {icon} **[{title}]({link})**{status_badge} "
                f"— deadline **{r['deadline']}** | score {r['score']}"
            )
        st.divider()

# ── SIDEBAR ───────────────────────────────────────────────────
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
    st.caption(f"🔄 {in_process_count} in process · ❌ {no_match_count} no match")
    if st.button("Clear all reviews", type="secondary"):
        st.session_state.reviews = {}
        save_reviews({})
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
        view = view[~view["pub_num"].astype(str).isin(reviewed_pubs)]
    if sort_by == "Score (high→low)":
        view = view.sort_values("score", ascending=False)
    elif sort_by == "Newest fetch":
        view = view.sort_values("fetched_date", ascending=False)
    elif sort_by == "Deadline" and "deadline" in view.columns:
        view = view[view["deadline"] != "—"].sort_values("deadline")
    return view.reset_index(drop=True)

# ── COLUMN CONFIGS ────────────────────────────────────────────
def col_config_main(df):
    cfg = {
        "reviewed": st.column_config.CheckboxColumn("✓", default=False, width="small"),
        "link":     st.column_config.LinkColumn("Link", display_text="View ↗"),
        "score":    st.column_config.NumberColumn("Score", format="%d ⭐"),
    }
    if "value" in df.columns:
        cfg["value"] = st.column_config.NumberColumn("Value", format="€%,.0f")
    return cfg

def col_config_reviewed(df):
    cfg = {
        "in_review":  st.column_config.CheckboxColumn("Keep", default=True, width="small"),
        "status":     st.column_config.SelectboxColumn(
                          "Status", options=STATUS_OPTIONS, default="Reviewed", width="medium"),
        "link":       st.column_config.LinkColumn("Link", display_text="View ↗"),
        "score":      st.column_config.NumberColumn("Score", format="%d ⭐"),
    }
    if "value" in df.columns:
        cfg["value"] = st.column_config.NumberColumn("Value", format="€%,.0f")
    return cfg

# ── DISPLAY COLUMNS ───────────────────────────────────────────
base_cols = [c for c in
    ["reviewed", "score", "bucket", "deadline", "title", "buyer", "country",
     "value", "currency", "duration", "languages",
     "notice_type", "t1_hits", "description", "link"]
    if c in df.columns or c == "reviewed"]

intel_cols = [c for c in
    ["reviewed", "score", "deadline", "title", "buyer", "country",
     "value", "currency", "notice_type", "t1_hits", "link"]
    if c in df.columns or c == "reviewed"]

reviewed_cols = [c for c in
    ["in_review", "status", "score", "bucket", "deadline", "title", "buyer",
     "country", "value", "currency", "notice_type", "t1_hits", "description", "link"]
    if c in df.columns or c in ("in_review", "status")]

def prep_description(view: pd.DataFrame) -> pd.DataFrame:
    if "description" in view.columns:
        view = view.copy()
        view["description"] = view["description"].fillna("").apply(
            lambda x: x[:200] + "…" if len(x) > 200 else x
        )
    return view

# ── MAIN TABLE (with review checkbox) ────────────────────────
def show_table(view: pd.DataFrame, cols: list, tab_key: str):
    if view.empty:
        st.info("No notices match your filters. Try lowering the minimum score.")
        return
    view = view.copy()
    view["reviewed"] = view["pub_num"].astype(str).isin(reviewed_pubs)
    display_cols = [c for c in cols if c in view.columns]

    edited = st.data_editor(
        prep_description(view)[display_cols].reset_index(drop=True),
        column_config=col_config_main(view),
        disabled=[c for c in display_cols if c != "reviewed"],
        use_container_width=True,
        height=520,
        key=f"editor_{tab_key}",
    )

    # Apply checkbox changes
    if "reviewed" in edited.columns:
        pub_nums = view["pub_num"].astype(str).tolist()
        changed = False
        for i, is_reviewed in enumerate(edited["reviewed"]):
            if i >= len(pub_nums):
                break
            pn = pub_nums[i]
            was_reviewed = pn in reviews
            if is_reviewed and not was_reviewed:
                reviews[pn] = "Reviewed"
                changed = True
            elif not is_reviewed and was_reviewed:
                del reviews[pn]
                changed = True
        if changed:
            save_reviews(reviews)
            st.rerun()

# ── REVIEWED TABLE (with status dropdown) ────────────────────
def show_reviewed_table(view: pd.DataFrame, tab_key: str):
    if view.empty:
        st.info("No reviewed notices yet. Check the ✓ box on any notice to move it here.")
        return
    view = view.copy()
    view["in_review"] = True
    view["status"]    = view["pub_num"].astype(str).map(reviews).fillna("Reviewed")
    display_cols = [c for c in reviewed_cols if c in view.columns]

    edited = st.data_editor(
        prep_description(view)[display_cols].reset_index(drop=True),
        column_config=col_config_reviewed(view),
        disabled=[c for c in display_cols if c not in ("in_review", "status")],
        use_container_width=True,
        height=520,
        key=f"editor_{tab_key}",
    )

    # Apply status and removal changes
    if "status" in edited.columns or "in_review" in edited.columns:
        pub_nums = view["pub_num"].astype(str).tolist()
        changed = False
        for i in range(len(edited)):
            if i >= len(pub_nums):
                break
            pn  = pub_nums[i]
            keep = edited["in_review"].iloc[i] if "in_review" in edited.columns else True
            new_status = edited["status"].iloc[i] if "status" in edited.columns else reviews.get(pn, "Reviewed")
            if not keep and pn in reviews:
                del reviews[pn]
                changed = True
            elif keep and new_status and reviews.get(pn) != new_status:
                reviews[pn] = new_status
                changed = True
        if changed:
            save_reviews(reviews)
            st.rerun()

# ── TABS ──────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    f"📋 Planning ({len(planning)})",
    f"🟢 Open ({len(open_)})",
    f"📁 Closed ({len(closed)})",
    f"✓ Reviewed ({len(reviewed_pubs)})",
])

# ── TAB 1: PLANNING ───────────────────────────────────────────
with tab1:
    view = apply_filters(planning)
    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.caption(
            f"Showing **{len(view)}** of {len(planning)} planning notices "
            f"— no submission deadline set (PIN / prior information notices)"
        )
    with col_b:
        if not view.empty:
            st.download_button("⬇️ Download CSV",
                data=view.to_csv(index=False).encode(),
                file_name=f"ted_planning_{today}.csv", mime="text/csv")

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
            st.download_button("⬇️ Download CSV",
                data=view.to_csv(index=False).encode(),
                file_name=f"ted_open_{today}.csv", mime="text/csv")

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
            view = view[~view["pub_num"].astype(str).isin(reviewed_pubs)]

        st.caption(f"Showing **{len(view)}** awarded contracts — buyer research & budget benchmarking")

        if "value" in view.columns and view["value"].notna().any():
            v1, v2, v3 = st.columns(3)
            v1.metric("Avg contract value", f"€{view['value'].mean():,.0f}")
            v2.metric("Max contract value", f"€{view['value'].max():,.0f}")
            v3.metric("Total awarded value", f"€{view['value'].sum():,.0f}")
            st.write("")

        show_table(view, intel_cols, "closed")

        if not view.empty:
            st.download_button("⬇️ Download CSV",
                data=view.to_csv(index=False).encode(),
                file_name=f"ted_closed_{today}.csv", mime="text/csv")

# ── TAB 4: REVIEWED ───────────────────────────────────────────
with tab4:
    # Sub-filter by status
    status_filter = st.radio(
        "Show",
        ["All", "Reviewed", "In process of applying", "Not a match"],
        horizontal=True
    )

    # Pull all reviewed notices from the main dataframe
    rev_df = df[df["pub_num"].astype(str).isin(reviewed_pubs)].copy()

    if not rev_df.empty:
        if status_filter != "All":
            rev_df = rev_df[
                rev_df["pub_num"].astype(str).map(reviews) == status_filter
            ]
        if search:
            mask = (
                rev_df["title"].str.contains(search, case=False, na=False) |
                rev_df["buyer"].str.contains(search, case=False, na=False)
            )
            rev_df = rev_df[mask]
        if country_filt != "All" and "country" in rev_df.columns:
            rev_df = rev_df[rev_df["country"] == country_filt]

    # Summary counts
    c1, c2, c3 = st.columns(3)
    c1.metric("🔵 Reviewed",              sum(1 for s in reviews.values() if s == "Reviewed"))
    c2.metric("🔄 In process of applying", in_process_count)
    c3.metric("❌ Not a match",             no_match_count)
    st.write("")

    st.caption(
        "Change status using the **Status** dropdown. "
        "Uncheck **Keep** to remove a notice from this list."
    )

    show_reviewed_table(rev_df, "reviewed")

    if not rev_df.empty:
        st.download_button("⬇️ Download CSV",
            data=rev_df.to_csv(index=False).encode(),
            file_name=f"ted_reviewed_{today}.csv", mime="text/csv")
