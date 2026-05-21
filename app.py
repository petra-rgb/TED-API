import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="TED Intelligence — DevelopMinded", layout="wide")
st.logo("logo.png", size="large")

st.markdown("""
<style>
    .stApp { background-color: #F2F2F2 !important; }
    [data-testid="stSidebar"] { background-color: #FFFFFF !important; }
    h1, h2, h3 { color: #F5C518 !important; }
    [data-testid="stMetricLabel"] { color: #F5C518 !important; }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #F5C518 !important;
        border-bottom: 3px solid #F5C518 !important;
    }
    .stButton > button, .stDownloadButton > button {
        background-color: #F5C518 !important;
        color: #1A1A1A !important;
        border: none !important;
        border-radius: 6px !important;
    }
    .stSlider [data-baseweb="slider"] [role="slider"] {
        background-color: #F5C518 !important;
    }
    a { color: #F5C518 !important; }
    .stApp, p, span, label { color: #1A1A1A !important; }
    [data-testid="stDataEditor"] {
        border: 1px solid #E0E0E0 !important;
        border-radius: 8px !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 2rem !important;
        font-weight: 700 !important;
        color: #1A1A1A !important;
    }
    [data-testid="stAlert"] {
        border-left: 4px solid #F5C518 !important;
        background-color: #FFFBE6 !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("# TED Tender Opportunities")

CSV_FILE       = "ted_results.csv"
AI_CSV_FILE    = "ted_results_ai.csv"
REVIEWS_FILE   = "reviews.csv"
WARN_DAYS      = 14
STATUS_OPTIONS = ["Reviewed", "Not a match", "In process of applying"]


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


@st.cache_data(ttl=300)
def load_ai_data():
    try:
        df = pd.read_csv(AI_CSV_FILE)
        df["fetched_date"] = pd.to_datetime(df["fetched_date"], errors="coerce")
        if "value" in df.columns:
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
        if "score" in df.columns:
            df["score"] = pd.to_numeric(df["score"], errors="coerce")
        if "ai_reason" in df.columns:
            df = df[~df["ai_reason"].str.contains("429|API error|Max retries", na=False)]
        return df
    except FileNotFoundError:
        return pd.DataFrame()


def load_reviews() -> tuple[dict, dict]:
    try:
        rv = pd.read_csv(REVIEWS_FILE)
        statuses = dict(zip(rv["pub_num"].astype(str), rv.get("status", pd.Series(["Reviewed"] * len(rv)))))
        notes = dict(zip(rv["pub_num"].astype(str), rv["notes"].fillna(""))) if "notes" in rv.columns else {}
        return statuses, notes
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return {}, {}


def save_reviews(reviews: dict, notes: dict):
    pd.DataFrame([
        {"pub_num": k, "status": v, "notes": notes.get(k, "")}
        for k, v in reviews.items()
    ]).to_csv(REVIEWS_FILE, index=False)


df    = load_data()
df_ai = load_ai_data()

if df.empty:
    st.warning("No data yet. The daily fetch has not run or the CSV is missing.")
    st.stop()

if "reviews" not in st.session_state or "notes" not in st.session_state:
    st.session_state.reviews, st.session_state.notes = load_reviews()

reviews = st.session_state.reviews
notes   = st.session_state.notes

today       = datetime.now().strftime("%Y-%m-%d")
warn_cutoff = (pd.Timestamp.now() + pd.Timedelta(days=WARN_DAYS)).strftime("%Y-%m-%d")

live_possible = df[df["bucket"].isin(["Live opportunity", "Possible opportunity"])].copy()
planning      = live_possible[live_possible["deadline"] == "—"].copy()
open_         = live_possible[live_possible["deadline"] != "—"].copy()
closed        = df[df["bucket"] == "Market intelligence"].copy()

ai_live     = pd.DataFrame()
ai_planning = pd.DataFrame()
ai_open_    = pd.DataFrame()
if not df_ai.empty:
    ai_lp       = df_ai[df_ai["bucket"].isin(["Live opportunity", "Possible opportunity"])].copy()
    ai_live     = ai_lp.copy()
    ai_planning = ai_lp[ai_lp["deadline"] == "—"].copy()
    ai_open_    = ai_lp[ai_lp["deadline"] != "—"].copy()

all_planning = pd.concat([planning, ai_planning]).drop_duplicates(subset=["pub_num"]) if not ai_planning.empty else planning
all_open     = pd.concat([open_, ai_open_]).drop_duplicates(subset=["pub_num"]) if not ai_open_.empty else open_

all_open_active = all_open[
    (all_open["deadline"] == "—") | (all_open["deadline"] >= today)
] if "deadline" in all_open.columns else all_open

ai_live_active = ai_live[
    (ai_live["deadline"] == "—") | (ai_live["deadline"] >= today)
] if not ai_live.empty and "deadline" in ai_live.columns else ai_live

reviewed_pubs    = set(reviews.keys())
in_process_count = sum(1 for s in reviews.values() if s == "In process of applying")
no_match_count   = sum(1 for s in reviews.values() if s == "Not a match")

open_deadlines = all_open[
    (all_open["deadline"] != "—") & (all_open["deadline"] >= today)
] if "deadline" in all_open.columns else pd.DataFrame()
urgent_count = len(open_deadlines[open_deadlines["deadline"] <= warn_cutoff])

last_run     = df["fetched_date"].max()
last_run_str = last_run.strftime("%Y-%m-%d") if pd.notna(last_run) else "—"
st.caption(f"Last updated: **{last_run_str}**")

k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
k1.metric("Planning",             len(all_planning))
k2.metric("Open",                 len(all_open_active))
k3.metric("Closed",               len(closed))
k4.metric(f"Deadline within {WARN_DAYS}d", urgent_count)
k5.metric("AI Relevant",          len(ai_live_active))
k6.metric("In process",           in_process_count)
k7.metric("Reviewed",             len(reviewed_pubs))

st.divider()

if "deadline" in open_.columns:
    urgent_regular = open_[
        (open_["deadline"] != "—") &
        (open_["deadline"] <= warn_cutoff) &
        (open_["deadline"] >= today)
    ].copy()
    urgent_regular["source"] = "keyword"

    urgent_ai = pd.DataFrame()
    if not ai_live.empty and "deadline" in ai_live.columns:
        urgent_ai = ai_live[
            (ai_live["deadline"] != "—") &
            (ai_live["deadline"] <= warn_cutoff) &
            (ai_live["deadline"] >= today)
        ].copy()
        urgent_ai["source"] = "ai"

    urgent = (
        pd.concat([urgent_regular, urgent_ai], ignore_index=True)
        .drop_duplicates(subset=["pub_num"])
        .sort_values("deadline")
    )

    if not urgent.empty:
        st.warning(f"{len(urgent)} opportunity/ies with deadline within {WARN_DAYS} days")
        for _, r in urgent.iterrows():
            is_ai        = r.get("source") == "ai"
            status_badge = f" · *{reviews.get(str(r['pub_num']), '')}*" if str(r["pub_num"]) in reviews else ""
            score_str    = f" | score {int(r['score'])}" if "score" in r and pd.notna(r.get("score")) else ""
            ai_badge     = " · *AI verified*" if is_ai else ""
            st.markdown(
                f"- **[{str(r['title'])[:90]}]({r.get('link', '')})**"
                f"{status_badge}{ai_badge} "
                f"— deadline **{r['deadline']}**{score_str}"
            )
        st.divider()

with st.sidebar:
    st.markdown("## Filters")
    new_today = st.toggle("New today only", value=False)
    search    = st.text_input("Search title / buyer")
    min_score = st.slider("Min score", 0, 30, 0)

    all_countries = pd.concat([
        df["country"] if "country" in df.columns else pd.Series(),
        df_ai["country"] if not df_ai.empty and "country" in df_ai.columns else pd.Series(),
    ]).dropna().replace("", pd.NA).dropna().unique().tolist()

    country_filt = st.selectbox("Country", ["All"] + sorted(all_countries))

    date_opts = ["All time"] + sorted(
        df["fetched_date"].dt.date.astype(str).unique().tolist(), reverse=True
    )
    date_filt     = st.selectbox("Fetched on", date_opts)
    sort_by       = st.selectbox("Sort by", ["Score (high to low)", "Newest fetch", "Deadline"])
    hide_reviewed = st.toggle("Hide reviewed", value=False)

    st.divider()
    st.caption(f"{in_process_count} in process · {no_match_count} no match")
    if st.button("Clear all reviews", type="secondary"):
        st.session_state.reviews = {}
        st.session_state.notes   = {}
        save_reviews({}, {})
        st.rerun()


def apply_filters(view: pd.DataFrame) -> pd.DataFrame:
    if view.empty:
        return view
    if "score" in view.columns:
        view = view[(view["score"] >= min_score) | view["score"].isna()].copy()
    else:
        view = view.copy()
    if new_today:
        view = view[view["fetched_date"].dt.date == pd.Timestamp.now().date()]
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
    if sort_by == "Score (high to low)" and "score" in view.columns:
        view = view.sort_values("score", ascending=False)
    elif sort_by == "Newest fetch":
        view = view.sort_values("fetched_date", ascending=False)
    elif sort_by == "Deadline" and "deadline" in view.columns:
        view = view[view["deadline"] != "—"].sort_values("deadline")
    return view.reset_index(drop=True)


def merge_sources(kw_df: pd.DataFrame, ai_df: pd.DataFrame):
    if kw_df.empty and ai_df.empty:
        return pd.DataFrame(), 0
    if kw_df.empty:
        out = ai_df.copy()
        out["title"] = "🤖 " + out["title"].astype(str)
        return out, 0
    if ai_df.empty:
        return kw_df.copy(), 0

    kw_pubs  = set(kw_df["pub_num"].astype(str))
    ai_pubs  = set(ai_df["pub_num"].astype(str))
    overlap  = kw_pubs & ai_pubs

    kw_out = kw_df.copy()
    kw_out.loc[kw_out["pub_num"].astype(str).isin(ai_pubs), "title"] = \
        "🤖 " + kw_out.loc[kw_out["pub_num"].astype(str).isin(ai_pubs), "title"].astype(str)

    ai_only = ai_df[~ai_df["pub_num"].astype(str).isin(kw_pubs)].copy()
    ai_only["title"] = "🤖 " + ai_only["title"].astype(str)
    if "score" in ai_only.columns:
        ai_only["score"] = pd.NA

    return pd.concat([kw_out, ai_only], ignore_index=True), len(overlap)


def prep_description(view: pd.DataFrame) -> pd.DataFrame:
    view = view.copy()
    if "description" in view.columns:
        view["description"] = view["description"].fillna("").apply(
            lambda x: x[:200] + "..." if len(x) > 200 else x
        )
    for col in ["value", "currency", "languages", "duration"]:
        if col in view.columns:
            view[col] = view[col].fillna("—").replace("", "—")
    return view
def show_cards(view: pd.DataFrame, tab_key: str):
    if view.empty:
        st.info("No notices match your filters.")
        return

    for i, (_, row) in enumerate(view.iterrows()):
        is_reviewed = str(row["pub_num"]) in reviewed_pubs
        col_check, col_main, col_right = st.columns([0.3, 5, 1.5])

        with col_check:
            checked = st.checkbox("", value=is_reviewed, key=f"card_{tab_key}_{i}")
            if checked != is_reviewed:
                if checked:
                    reviews[str(row["pub_num"])] = "Reviewed"
                else:
                    reviews.pop(str(row["pub_num"]), None)
                save_reviews(reviews, notes)
                st.rerun()

        with col_main:
            title = str(row.get("title", ""))
            link  = row.get("link", "")
            st.markdown(f"**[{title}]({link})**")
            
            meta_parts = [
                row.get("buyer", ""),
                row.get("country", ""),
            ]
            if row.get("deadline") and row.get("deadline") != "—":
                meta_parts.append(f"Deadline: {row['deadline']}")
            st.caption("  ·  ".join(p for p in meta_parts if p))

            desc = str(row.get("description", ""))
            if desc and desc != "nan":
                st.markdown(
                    f"<p style='color:#555;font-size:0.85rem;margin-top:4px'>{desc[:250]}...</p>",
                    unsafe_allow_html=True
                )

        with col_right:
            if pd.notna(row.get("score")):
                st.metric("Score", int(row["score"]))
            elif "🤖" in title:
                st.markdown("**AI verified**")
            if pd.notna(row.get("value")):
                st.metric("Value", f"€{row['value']:,.0f}")

        st.divider()

def col_config_main(df):
    cfg = {
        "reviewed": st.column_config.CheckboxColumn("Done", default=False, width="small"),
        "link":     st.column_config.LinkColumn("Link", display_text="View"),
        "score":    st.column_config.NumberColumn("Score", format="%d"),
    }
    if "value" in df.columns:
        cfg["value"] = st.column_config.NumberColumn("Value", format="€%,.0f")
    return cfg


def show_copy_brief(view: pd.DataFrame, key: str):
    if view.empty:
        return
    st.divider()
    st.caption("Copy tender brief")
    titles   = ["— select a notice —"] + view["title"].astype(str).tolist()
    selected = st.selectbox("", titles, key=f"copy_select_{key}", label_visibility="collapsed")
    if selected == "— select a notice —":
        return
    row       = view[view["title"].astype(str) == selected].iloc[0]
    value_str = f"€{row['value']:,.0f}" if pd.notna(row.get("value")) else "—"
    brief = f"""{row['title']}

Buyer:    {row['buyer']}
Country:  {row.get('country', '—')}
Deadline: {row.get('deadline', '—')}
Value:    {value_str}

{str(row.get('description', ''))[:500]}

{row.get('link', '')}"""
    st.code(brief, language=None)


def show_table(view: pd.DataFrame, cols: list, tab_key: str):
    if view.empty:
        st.info("No notices match your filters.")
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

    if "reviewed" in edited.columns:
        pub_nums = view["pub_num"].astype(str).tolist()
        changed  = False
        for i, is_reviewed in enumerate(edited["reviewed"]):
            if i >= len(pub_nums):
                break
            pn = pub_nums[i]
            if is_reviewed and pn not in reviews:
                reviews[pn] = "Reviewed"
                changed = True
            elif not is_reviewed and pn in reviews:
                del reviews[pn]
                changed = True
        if changed:
            save_reviews(reviews, notes)
            st.rerun()


def show_reviewed_table(view: pd.DataFrame, tab_key: str):
    if view.empty:
        st.info("No reviewed notices yet.")
        return
    view = view.copy()
    view["in_review"] = True
    view["status"]    = view["pub_num"].astype(str).map(reviews).fillna("Reviewed")
    view["notes"]     = view["pub_num"].astype(str).map(notes).fillna("")
    display_cols      = [c for c in reviewed_cols if c in view.columns]

    edited = st.data_editor(
        prep_description(view)[display_cols].reset_index(drop=True),
        column_config={
            "in_review": st.column_config.CheckboxColumn("Keep", default=True, width="small"),
            "status":    st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS, default="Reviewed", width="medium"),
            "notes":     st.column_config.TextColumn("Notes", width="large"),
            "link":      st.column_config.LinkColumn("Link", display_text="View"),
            "score":     st.column_config.NumberColumn("Score", format="%d"),
            "value":     st.column_config.NumberColumn("Value", format="€%,.0f"),
        },
        disabled=[c for c in display_cols if c not in ("in_review", "status", "notes")],
        use_container_width=True,
        height=520,
        key=f"editor_{tab_key}",
    )

    pub_nums = view["pub_num"].astype(str).tolist()
    changed  = False
    for i in range(len(edited)):
        if i >= len(pub_nums):
            break
        pn         = pub_nums[i]
        keep       = edited["in_review"].iloc[i] if "in_review" in edited.columns else True
        new_status = edited["status"].iloc[i] if "status" in edited.columns else reviews.get(pn, "Reviewed")
        new_note   = edited["notes"].iloc[i] if "notes" in edited.columns else ""
        if not keep and pn in reviews:
            del reviews[pn]
            notes.pop(pn, None)
            changed = True
        elif keep:
            if reviews.get(pn) != new_status:
                reviews[pn] = new_status
                changed = True
            if notes.get(pn, "") != (new_note or ""):
                notes[pn] = new_note or ""
                changed = True
    if changed:
        save_reviews(reviews, notes)
        st.rerun()


planning_cols = [c for c in
    ["reviewed", "score", "title", "buyer", "country", "value", "description", "link"]
    if c in df.columns or c == "reviewed"]

base_cols = [c for c in
    ["reviewed", "score", "deadline", "title", "buyer", "country", "value", "description", "link"]
    if c in df.columns or c == "reviewed"]

intel_cols = [c for c in
    ["title", "buyer", "country", "value", "link"]
    if c in df.columns]

reviewed_cols = [c for c in
    ["in_review", "status", "notes", "score", "deadline", "title", "buyer",
     "country", "value", "description", "link"]
    if c in df.columns or c in ("in_review", "status", "notes")]


tab1, tab2, tab3, tab4, tab5 = st.tabs([
    f"Planning ({len(all_planning)})",
    f"Open ({len(all_open_active)})",
    f"Closed ({len(closed)})",
    f"Reviewed ({len(reviewed_pubs)})",
    f"AI Filtered ({len(ai_live_active)})",
])

with tab1:
    combined_planning, planning_overlap = merge_sources(planning, ai_planning)
    view = apply_filters(combined_planning)

    ai_count     = view["title"].astype(str).str.startswith("🤖").sum() if not view.empty else 0
    overlap_note = f" · {planning_overlap} appear in both keyword and AI" if planning_overlap else ""
    ai_note      = f" · {ai_count} AI filtered" if ai_count else ""

    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.caption(f"Showing **{len(view)}** of {len(combined_planning)} planning notices — no deadline set{overlap_note}{ai_note}")
    with col_b:
        if not view.empty:
            st.download_button("Download CSV",
                data=view.to_csv(index=False).encode(),
                file_name=f"ted_planning_{today}.csv", mime="text/csv")
    show_cards(view, "planning")
    show_copy_brief(view, "planning")


with tab2:
    combined_open, open_overlap = merge_sources(open_, ai_open_)
    view = apply_filters(combined_open)
    if "deadline" in view.columns:
        view = view[(view["deadline"] == "—") | (view["deadline"] >= today)].reset_index(drop=True)

    if not view.empty and "deadline" in view.columns:
        upcoming = view[view["deadline"] != "—"].copy()
        upcoming = upcoming[upcoming["deadline"] >= today].sort_values("deadline").head(5)
        if not upcoming.empty:
            st.caption("Next deadlines")
            cols = st.columns(len(upcoming))
            for i, (_, r) in enumerate(upcoming.iterrows()):
                days_left = (pd.to_datetime(r["deadline"]) - pd.Timestamp.now()).days
                cols[i].metric(
                    label=str(r["title"])[:40] + "...",
                    value=r["deadline"],
                    delta=f"{days_left}d left",
                    delta_color="inverse"
                )
            st.write("")

    ai_count     = view["title"].astype(str).str.startswith("🤖").sum() if not view.empty else 0
    overlap_note = f" · {open_overlap} appear in both keyword and AI" if open_overlap else ""
    ai_note      = f" · {ai_count} AI filtered" if ai_count else ""

    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.caption(f"Showing **{len(view)}** of {len(combined_open)} open opportunities{overlap_note}{ai_note}")
    with col_b:
        if not view.empty:
            st.download_button("Download CSV",
                data=view.to_csv(index=False).encode(),
                file_name=f"ted_open_{today}.csv", mime="text/csv")
    show_cards(view, "open")
    show_copy_brief(view, "open")


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

        st.caption(f"Showing **{len(view)}** awarded contracts — buyer research and budget benchmarking")

        if "value" in view.columns and view["value"].notna().any():
            v1, v2, v3 = st.columns(3)
            v1.metric("Avg contract value",  f"€{view['value'].mean():,.0f}")
            v2.metric("Max contract value",  f"€{view['value'].max():,.0f}")
            v3.metric("Total awarded value", f"€{view['value'].sum():,.0f}")
            st.write("")

        display_cols = [c for c in intel_cols if c in view.columns]
        st.dataframe(
            prep_description(view)[display_cols].reset_index(drop=True),
            column_config={
                "link":  st.column_config.LinkColumn("Link", display_text="View"),
                "value": st.column_config.NumberColumn("Value", format="€%,.0f"),
            },
            use_container_width=True,
            height=520,
        )


with tab4:
    status_filter = st.radio(
        "Show", ["All", "Reviewed", "In process of applying", "Not a match"],
        horizontal=True
    )
    rev_df = df[df["pub_num"].astype(str).isin(reviewed_pubs)].copy()
    if not rev_df.empty:
        if status_filter != "All":
            rev_df = rev_df[rev_df["pub_num"].astype(str).map(reviews) == status_filter]
        if search:
            mask = (
                rev_df["title"].str.contains(search, case=False, na=False) |
                rev_df["buyer"].str.contains(search, case=False, na=False)
            )
            rev_df = rev_df[mask]
        if country_filt != "All" and "country" in rev_df.columns:
            rev_df = rev_df[rev_df["country"] == country_filt]

    c1, c2, c3 = st.columns(3)
    c1.metric("Reviewed",              sum(1 for s in reviews.values() if s == "Reviewed"))
    c2.metric("In process",            in_process_count)
    c3.metric("Not a match",           no_match_count)
    st.write("")
    st.caption("Change status with the Status dropdown. Uncheck Keep to remove.")
    show_reviewed_table(rev_df, "reviewed")
    if not rev_df.empty:
        st.download_button("Download CSV",
            data=rev_df.to_csv(index=False).encode(),
            file_name=f"ted_reviewed_{today}.csv", mime="text/csv")


with tab5:
    if df_ai.empty:
        st.info("No AI data yet. Commit ted_results_ai.csv to the repo and it will load automatically.")
    else:
        ai_live_tab = df_ai[df_ai["bucket"].isin(["Live opportunity", "Possible opportunity"])].copy()
        ai_last     = df_ai["fetched_date"].max()
        st.caption(
            f"AI last run: **{ai_last.strftime('%Y-%m-%d') if pd.notna(ai_last) else '—'}** "
            f"· Only notices Claude judged relevant for DevelopMinded"
        )

        view = apply_filters(ai_live_tab)
        if "deadline" in view.columns:
            view = view[(view["deadline"] == "—") | (view["deadline"] >= today)].reset_index(drop=True)

        a1, a2, a3, a4 = st.columns(4)
        a1.metric("AI Planning",    len(ai_live_tab[ai_live_tab["deadline"] == "—"]))
        a2.metric("AI Open",        len(ai_live_tab[ai_live_tab["deadline"] != "—"]))
        a3.metric("After filters",  len(view))
        days_covered = (
            (df_ai["fetched_date"].max() - df_ai["fetched_date"].min()).days + 1
            if df_ai["fetched_date"].notna().any() else 0
        )
        a4.metric("Days covered", days_covered)

        col_a, col_b = st.columns([3, 1])
        with col_b:
            if not view.empty:
                st.download_button("Download CSV",
                    data=view.to_csv(index=False).encode(),
                    file_name=f"ted_ai_{today}.csv", mime="text/csv")

        if not view.empty and "ai_reason" in view.columns:
            with st.expander("Claude reasoning for top 10", expanded=False):
                for _, r in view.head(10).iterrows():
                    st.markdown(f"**{str(r['title'])[:90]}**  \n_{r.get('ai_reason', '—')}_")
                    st.divider()

        tab_ai_cols = [c for c in
            ["reviewed", "deadline", "title", "buyer", "country",
             "value", "ai_reason", "description", "link"]
            if c in view.columns or c == "reviewed"]

        show_table(view, tab_ai_cols, "ai_filtered")
