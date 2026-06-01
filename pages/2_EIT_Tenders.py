"""
EIT Tender Intelligence — DevelopMinded
Matches the TED Opportunity Search visual style.
Data is refreshed weekly by GitHub Actions (weekly_run.py).
"""

import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime

st.set_page_config(page_title="EIT Tenders", page_icon="🏛️", layout="wide")
st.logo("logo.png", size="large")

# ── Same theme as the TED app ─────────────────────────────────────────────────
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
    a { color: #F5C518 !important; }
    .stApp, p, span, label { color: #1A1A1A !important; }
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

st.markdown("# EIT Tender Intelligence")

# ── Paths ─────────────────────────────────────────────────────────────────────
OUTPUT       = Path("output")
ACTIVE_CSV   = OUTPUT / "active_tenders.csv"
NEW_WEEK_CSV = OUTPUT / "new_this_week.csv"
today_str    = datetime.now().strftime("%Y-%m-%d")

FIT_ORDER = {"YES": 0, "MAYBE": 1, "NO": 2, "ERROR": 3}
FIT_BADGE = {"YES": "YES", "MAYBE": " MAYBE", "NO": " NO", "ERROR": " ERROR"}


# ── Load CSVs ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=600)
def load_csv(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists() or p.stat().st_size < 10:
        return pd.DataFrame()
    df = pd.read_csv(p)
    if "score" in df.columns:
        df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0).astype(int)
    return df


df_active = load_csv(str(ACTIVE_CSV))
df_new    = load_csv(str(NEW_WEEK_CSV))

if ACTIVE_CSV.exists():
    mtime = datetime.fromtimestamp(ACTIVE_CSV.stat().st_mtime)
    st.caption(f"Last updated: **{mtime.strftime('%d %B %Y, %H:%M')}** — refreshed every Monday via GitHub Actions")


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Filters")

    fit_filter = st.multiselect(
        "Fit", ["YES", "MAYBE", "NO"],
        default=["YES", "MAYBE"],
    )
    min_score = st.slider("Min score", 0, 10, 0)

    sources = ["All sources"]
    if not df_active.empty and "source" in df_active.columns:
        sources += sorted(df_active["source"].dropna().unique().tolist())
    sel_source = st.selectbox("Source (KIC)", sources)

    search = st.text_input("Search title")

    st.divider()
    st.caption(
        "Scrapes 8 EIT KIC websites weekly.\n\n"
        "Only tenders **not seen before** are sent to Claude — ~$0.03 per run."
    )


# ── Metrics row ───────────────────────────────────────────────────────────────
if not df_active.empty:
    n_yes   = int((df_active["fit"] == "YES").sum())
    n_maybe = int((df_active["fit"] == "MAYBE").sum())
    n_no    = int((df_active["fit"] == "NO").sum())
    n_new   = len(df_new) if not df_new.empty else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Open Tenders",    len(df_active))
    m2.metric("Strong Match ", n_yes)
    m3.metric("Possible ",    n_maybe)
    m4.metric("No Match ",     n_no)
    m5.metric("New This Week",   n_new)
    st.write("")


# ── Data helpers ──────────────────────────────────────────────────────────────
def _best_deadline(row) -> str:
    for col in ("call_deadline", "deadline"):
        v = str(row.get(col, "") or "").strip()
        if v and v != "nan":
            return v
    return "—"


def prep(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["best_deadline"] = df.apply(_best_deadline, axis=1)
    df["fit_badge"]     = df["fit"].map(FIT_BADGE).fillna(df.get("fit", ""))
    df["summary"]       = df.get("call_summary", pd.Series(dtype=str)).fillna("").apply(
        lambda x: (x[:200] + "…") if len(x) > 200 else x
    )
    df["reason"]        = df.get("fit_reason", pd.Series(dtype=str)).fillna("").apply(
        lambda x: (x[:160] + "…") if len(x) > 160 else x
    )
    df["_ord"] = df["fit"].map(FIT_ORDER).fillna(3)
    return df.sort_values(["_ord", "score"], ascending=[True, False]).drop(columns=["_ord"]).reset_index(drop=True)


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if fit_filter:
        df = df[df["fit"].isin(fit_filter)]
    if min_score > 0 and "score" in df.columns:
        df = df[df["score"] >= min_score]
    if sel_source != "All sources" and "source" in df.columns:
        df = df[df["source"] == sel_source]
    if search and "title" in df.columns:
        df = df[df["title"].str.contains(search, case=False, na=False)]
    return df.reset_index(drop=True)


DISPLAY_COLS = ["fit_badge", "score", "best_deadline", "title", "source", "summary", "reason", "url"]

COL_CFG = {
    "fit_badge":     st.column_config.TextColumn("Fit",        width="small"),
    "score":         st.column_config.NumberColumn("Score",    format="%d",   width="small"),
    "best_deadline": st.column_config.TextColumn("Deadline",   width="medium"),
    "title":         st.column_config.TextColumn("Title",      width="large"),
    "source":        st.column_config.TextColumn("Source",     width="medium"),
    "summary":       st.column_config.TextColumn("Summary",    width="large"),
    "reason":        st.column_config.TextColumn("Fit Reason", width="large"),
    "url":           st.column_config.LinkColumn("Link",       display_text="View ↗"),
}


def show_table(df: pd.DataFrame, tab_key: str):
    if df.empty:
        st.info("No tenders match your filters.")
        return
    cols = [c for c in DISPLAY_COLS if c in df.columns]
    st.dataframe(
        df[cols],
        column_config=COL_CFG,
        use_container_width=True,
        height=520,
        hide_index=True,
    )


def show_full_analysis(df: pd.DataFrame):
    """Expandable section with full Claude summaries for YES/MAYBE tenders."""
    relevant = df[df["fit"].isin(["YES", "MAYBE"])]
    if relevant.empty or "call_summary" not in relevant.columns:
        return
    with st.expander(f"Full Claude analysis — {len(relevant)} relevant tender(s)", expanded=False):
        for _, r in relevant.iterrows():
            badge    = r.get("fit_badge", r.get("fit", ""))
            score    = r.get("score", 0)
            title    = str(r.get("title", ""))
            url      = str(r.get("url", "#"))
            summary  = str(r.get("call_summary", "") or "")
            reason   = str(r.get("fit_reason", "") or "")
            match_sv = str(r.get("fit_match", "") or "")
            if summary and summary != "nan":
                st.markdown(f"**{badge} &nbsp; {score}/10 — [{title}]({url})**")
                st.write(summary)
                if reason and reason != "nan":
                    st.caption(f"Fit: {reason}")
                if match_sv and match_sv not in ("nan", "none", ""):
                    st.caption(f"Most relevant service: {match_sv}")
                st.divider()


# ── Stop early if no data ─────────────────────────────────────────────────────
if df_active.empty:
    st.divider()
    st.warning(
        "**No data yet.**\n\n"
        "Trigger the first run: go to your GitHub repo → **Actions** → "
        "**EIT Weekly Tender Scrape** → **Run workflow**."
    )
    st.stop()


# ── Tabs ──────────────────────────────────────────────────────────────────────
df_active_prep = prep(df_active)
df_new_prep    = prep(df_new) if not df_new.empty else pd.DataFrame()

active_view = apply_filters(df_active_prep)
new_view    = apply_filters(df_new_prep) if not df_new_prep.empty else pd.DataFrame()

tab1, tab2 = st.tabs([
    f"All Open ({len(active_view)})",
    f"New This Week ({len(new_view) if not new_view.empty else 0})",
])

with tab1:
    col_a, col_b = st.columns([4, 1])
    with col_a:
        st.caption(f"Showing **{len(active_view)}** of {len(df_active)} active EIT tenders")
    with col_b:
        if not active_view.empty:
            st.download_button(
                "Download CSV",
                data=active_view.to_csv(index=False).encode(),
                file_name=f"eit_active_{today_str}.csv",
                mime="text/csv",
            )
    show_table(active_view, "active")
    show_full_analysis(active_view)


with tab2:
    if new_view is None or new_view.empty:
        st.info(
            "No new tenders in the latest run.\n\n"
            "The scraper compares against the master list of all previously seen tenders "
            "— only genuinely new ones appear here after each Monday run."
        )
    else:
        col_a, col_b = st.columns([4, 1])
        with col_a:
            st.caption(
                f"**{len(new_view)}** new tenders found since last run "
                f"· only these were evaluated by Claude this week"
            )
        with col_b:
            if not new_view.empty:
                st.download_button(
                    "Download CSV",
                    data=new_view.to_csv(index=False).encode(),
                    file_name=f"eit_new_{today_str}.csv",
                    mime="text/csv",
                )
        show_table(new_view, "new_week")
        show_full_analysis(new_view)
