import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="DevelopMinded Intelligence", page_icon="🔍", layout="wide")
st.logo("logo.png", size="large")

st.markdown("""
<style>
    .stApp { background-color: #F2F2F2 !important; }
    [data-testid="stSidebar"] { background-color: #FFFFFF !important; }
    h1, h2, h3 { color: #F5C518 !important; }
    [data-testid="stMetricLabel"] { color: #F5C518 !important; }
    .stButton > button, .stDownloadButton > button {
        background-color: #F5C518 !important;
        color: #1A1A1A !important;
        border: none !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
        width: 100% !important;
    }
    a { color: #F5C518 !important; }
    .stApp, p, span, label { color: #1A1A1A !important; }
    [data-testid="stMetricValue"] {
        font-size: 2rem !important;
        font-weight: 700 !important;
        color: #1A1A1A !important;
    }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
    [data-testid="stAlert"] {
        border-left: 4px solid #F5C518 !important;
        background-color: #FFFBE6 !important;
    }
    div[data-testid="stVerticalBlock"] div[data-testid="stVerticalBlock"] {
        background-color: #FFFFFF;
        border-radius: 12px;
        padding: 8px;
    }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
TED_CSV     = "ted_results.csv"
TED_AI_CSV  = "ted_results_ai.csv"
EIT_ACTIVE  = Path("output/active_tenders.csv")
EIT_NEW     = Path("output/new_this_week.csv")
WARN_DAYS   = 14
today       = datetime.now().strftime("%Y-%m-%d")
today_ts    = pd.Timestamp.now()


# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_ted():
    try:
        df = pd.read_csv(TED_CSV)
        df["fetched_date"] = pd.to_datetime(df["fetched_date"], errors="coerce")
        df["score"]        = pd.to_numeric(df.get("score", 0), errors="coerce").fillna(0)
        return df
    except FileNotFoundError:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_ted_ai():
    try:
        df = pd.read_csv(TED_AI_CSV)
        df["fetched_date"] = pd.to_datetime(df["fetched_date"], errors="coerce")
        if "ai_reason" in df.columns:
            df = df[~df["ai_reason"].str.contains("429|API error|Max retries", na=False)]
        return df
    except FileNotFoundError:
        return pd.DataFrame()

@st.cache_data(ttl=600)
def load_eit(path: str):
    p = Path(path)
    if not p.exists() or p.stat().st_size < 10:
        return pd.DataFrame()
    df = pd.read_csv(p)
    if "score" in df.columns:
        df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0).astype(int)
    return df


df_ted    = load_ted()
df_ai     = load_ted_ai()
df_eit    = load_eit(str(EIT_ACTIVE))
df_eit_new = load_eit(str(EIT_NEW))


# ── TED metrics ───────────────────────────────────────────────────────────────
warn_cutoff = (today_ts + pd.Timedelta(days=WARN_DAYS)).strftime("%Y-%m-%d")

ted_last_run = "—"
ted_open = ted_planning = ted_urgent = ted_ai = 0
urgent_rows = pd.DataFrame()

if not df_ted.empty:
    ted_last_run = (df_ted["fetched_date"].max().strftime("%d %b %Y")
                    if df_ted["fetched_date"].notna().any() else "—")

    live        = df_ted[df_ted["bucket"].isin(["Live opportunity", "Possible opportunity"])]
    kw_planning = live[live["deadline"] == "—"]
    kw_open     = live[live["deadline"] != "—"]

    # Mirror TED page: merge keyword + AI, deduplicate on pub_num
    ai_planning_df = pd.DataFrame()
    ai_open_df     = pd.DataFrame()
    if not df_ai.empty:
        ai_lp          = df_ai[df_ai["bucket"].isin(["Live opportunity", "Possible opportunity"])]
        ai_planning_df = ai_lp[ai_lp["deadline"] == "—"]
        ai_open_df     = ai_lp[ai_lp["deadline"] != "—"]

    all_planning = (
        pd.concat([kw_planning, ai_planning_df]).drop_duplicates(subset=["pub_num"])
        if not ai_planning_df.empty else kw_planning
    )
    all_open = (
        pd.concat([kw_open, ai_open_df]).drop_duplicates(subset=["pub_num"])
        if not ai_open_df.empty else kw_open
    )

    # Open = active (deadline not yet passed, or no deadline)
    all_open_active = all_open[
        (all_open["deadline"] == "—") | (all_open["deadline"] >= today)
    ] if "deadline" in all_open.columns else all_open

    ted_planning = len(all_planning)
    ted_open     = len(all_open_active)

    # Urgent = open tenders with deadline within WARN_DAYS
    open_deadlines = all_open[
        (all_open["deadline"] != "—") & (all_open["deadline"] >= today)
    ] if "deadline" in all_open.columns else pd.DataFrame()
    urgent_rows = (
        open_deadlines[open_deadlines["deadline"] <= warn_cutoff].sort_values("deadline")
        if not open_deadlines.empty else pd.DataFrame()
    )
    ted_urgent = len(urgent_rows)

if not df_ai.empty:
    ai_live   = df_ai[df_ai["bucket"].isin(["Live opportunity", "Possible opportunity"])]
    ai_active = ai_live[(ai_live["deadline"] == "—") | (ai_live["deadline"] >= today)]
    ted_ai    = len(ai_active)


# ── EIT deadline parser ───────────────────────────────────────────────────────
def _eit_parse_ts(text) -> pd.Timestamp:
    if not text or str(text).strip() in ("", "nan", "—"):
        return pd.NaT
    text = str(text).strip()
    text = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[\(\[].*?[\)\]]", "", text).strip()
    text = re.sub(r"\s+at\s+\d{1,2}:\d{2}.*$", "", text, flags=re.IGNORECASE).strip()
    m = re.search(r"(\d{1,2})/(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if m:
        text = f"{m.group(2)} {m.group(3)} {m.group(4)}"
    m = re.search(r"[Ee]nd\s+of\s+([A-Za-z]+)\s+(\d{4})", text)
    if m:
        text = f"28 {m.group(1)} {m.group(2)}"
    for fmt in ("%d %B %Y", "%B %d %Y", "%B %d, %Y",
                "%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return pd.Timestamp(datetime.strptime(text[:30].strip(), fmt))
        except Exception:
            pass
    return pd.to_datetime(text, dayfirst=True, errors="coerce")


# ── EIT metrics ───────────────────────────────────────────────────────────────
eit_last_run = "—"
eit_open = eit_yes = eit_maybe = eit_new = 0
eit_urgent_rows = pd.DataFrame()

if not df_eit.empty:
    if EIT_ACTIVE.exists():
        mtime = datetime.fromtimestamp(EIT_ACTIVE.stat().st_mtime)
        eit_last_run = mtime.strftime("%d %b %Y")
    eit_open  = len(df_eit)
    eit_yes   = int((df_eit["fit"] == "YES").sum())   if "fit" in df_eit.columns else 0
    eit_maybe = int((df_eit["fit"] == "MAYBE").sum()) if "fit" in df_eit.columns else 0

    # Parse deadlines and find urgent ones
    df_eit = df_eit.copy()
    df_eit["_best_dl"] = df_eit.apply(
        lambda r: str(r.get("call_deadline") or r.get("deadline") or "").strip(), axis=1
    )
    df_eit["_dl_ts"] = df_eit["_best_dl"].apply(_eit_parse_ts)
    eit_urgent_rows = df_eit[
        df_eit["_dl_ts"].notna() &
        (df_eit["_dl_ts"] >= today_ts) &
        (df_eit["_dl_ts"] <= (today_ts + pd.Timedelta(days=WARN_DAYS)))
    ].sort_values("_dl_ts")

if not df_eit_new.empty:
    eit_new = (len(df_eit_new[df_eit_new["fit"].isin(["YES", "MAYBE"])])
               if "fit" in df_eit_new.columns else len(df_eit_new))


# ── Page header ───────────────────────────────────────────────────────────────
st.markdown("# Opportunity Search")
st.caption(f"DevelopMinded · {datetime.now().strftime('%d %B %Y')}")
st.divider()


# ── Two-column summary cards ──────────────────────────────────────────────────
col_ted, col_eit = st.columns(2, gap="large")

with col_ted:
    st.markdown("###  TED Opportunities")
    st.caption(f"Last run: **{ted_last_run}**")
    st.write("")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Open",         ted_open)
    m2.metric("Planning",     ted_planning)
    m3.metric(f"Due <{WARN_DAYS}d", ted_urgent)
    m4.metric("AI Relevant",  ted_ai)

    st.write("")
    if st.button("→ View TED Opportunities", key="btn_ted"):
        st.switch_page("pages/1_Opportunity_Search.py")

with col_eit:
    st.markdown("###  EIT Tenders")
    st.caption(f"Last run: **{eit_last_run}** · refreshed every Monday")
    st.write("")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Open",            eit_open)
    m2.metric("Strong Match ", eit_yes)
    m3.metric("Possible ",    eit_maybe)
    m4.metric("New This Week",   eit_new)

    st.write("")
    if st.button("→ View EIT Tenders", key="btn_eit"):
        st.switch_page("pages/2_EIT_Tenders.py")


# ── Urgent deadlines ──────────────────────────────────────────────────────────
st.divider()

if not urgent_rows.empty:
    st.markdown(f"###  TED Deadlines in the next {WARN_DAYS} days")
    for _, r in urgent_rows.head(8).iterrows():
        days_left = (pd.to_datetime(r["deadline"]) - today_ts).days
        delta_str = f"{days_left}d left"
        col_a, col_b = st.columns([5, 1])
        with col_a:
            st.markdown(f"**[{str(r['title'])[:85]}]({r.get('link', '#')})**  \n"
                        f"<small>{r.get('buyer', '')} &nbsp;·&nbsp; deadline "
                        f"**{r['deadline']}** &nbsp;·&nbsp; {delta_str}</small>",
                        unsafe_allow_html=True)
        with col_b:
            score = int(r.get("score", 0))
            if score:
                st.metric("Score", score)
    st.write("")

# EIT urgent deadlines
if not eit_urgent_rows.empty:
    st.markdown(f"###  EIT Deadlines in the next {WARN_DAYS} days")
    for _, r in eit_urgent_rows.iterrows():
        days_left = (r["_dl_ts"] - today_ts).days
        fit  = str(r.get("fit", ""))
        badge = ""
        col_a, col_b = st.columns([5, 1])
        with col_a:
            st.markdown(
                f"**[{str(r.get('title',''))[:85]}]({r.get('url','#')})**  \n"
                f"<small>{r.get('source','')} &nbsp;·&nbsp; deadline **{r['_best_dl']}**"
                f" &nbsp;·&nbsp; {days_left}d left &nbsp;·&nbsp; {badge} {fit}</small>",
                unsafe_allow_html=True
            )
        with col_b:
            score = int(r.get("score", 0))
            if score:
                st.metric("Score", score)
    st.write("")

# EIT strong matches if any
if not df_eit.empty and eit_yes > 0 and "fit" in df_eit.columns:
    yes_tenders = df_eit[df_eit["fit"] == "YES"]
    st.markdown("### EIT Strong Matches")
    for _, r in yes_tenders.iterrows():
        deadline = str(r.get("call_deadline") or r.get("deadline") or "")
        if not deadline or deadline == "nan":
            deadline = "deadline unknown"
        st.markdown(
            f"**[{str(r['title'])[:85]}]({r.get('url', '#')})**  \n"
            f"<small>{r.get('source', '')} &nbsp;·&nbsp;  {deadline} &nbsp;·&nbsp; "
            f"score {r.get('score', 0)}/10</small>",
            unsafe_allow_html=True,
        )
        if r.get("call_summary") and str(r.get("call_summary")) != "nan":
            st.caption(str(r["call_summary"])[:200] + "…")
        st.write("")
