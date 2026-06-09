"""
TED Tender Search — self-serve client portal
Invite-code protected. Client enters their company profile,
gets AI-filtered EU tenders on screen + CSV download.
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

import pandas as pd
import requests
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ted_core

st.set_page_config(page_title="TED Tender Search", layout="wide")

# Path to EIT evaluated master (relative to repo root or absolute fallback)
EIT_CSV = os.path.join(os.path.dirname(__file__), "..", "eit_tenders.csv")

# ─────────────────────────────────────────────────────────────
# BRANDING
# ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #F2F2F2 !important; }
    [data-testid="stSidebar"] { background-color: #FFFFFF !important; }
    h1, h2, h3 { color: #F5C518 !important; }
    .stButton > button, .stDownloadButton > button {
        background-color: #F5C518 !important;
        color: #1A1A1A !important;
        border: none !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
    }
    a { color: #F5C518 !important; }
    [data-testid="stAlert"] {
        border-left: 4px solid #F5C518 !important;
        background-color: #FFFBE6 !important;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# INVITE CODES  (store in Streamlit secrets as a list)
# secrets.toml:
#   [access]
#   codes = ["CLIENT001", "PARTNER42", "DEMO2026"]
# ─────────────────────────────────────────────────────────────
def get_valid_codes() -> set:
    try:
        codes = st.secrets["access"]["codes"]
        return {c.strip().upper() for c in codes}
    except Exception:
        return {"DEMO2026"}   # fallback for local dev


# ─────────────────────────────────────────────────────────────
# ACCESS GATE
# ─────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("# 🔍 TED Tender Intelligence")
    st.markdown("Enter your invite code to access the tender search.")
    col1, col2 = st.columns([2, 1])
    with col1:
        code_input = st.text_input("Invite code", type="password", placeholder="e.g. CLIENT001")
    with col2:
        st.write("")
        st.write("")
        if st.button("Access", use_container_width=True):
            if code_input.strip().upper() in get_valid_codes():
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Invalid code. Please contact DevelopMinded.")
    st.stop()


# ─────────────────────────────────────────────────────────────
# TED FETCH CONSTANTS  (shared logic lives in ted_core)
# ─────────────────────────────────────────────────────────────
CLAUDE_URL   = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5"
MAX_PAGES    = 20        # cap pages to keep runtime reasonable
AI_WORKERS   = 3
INTEL_TYPES  = ted_core.INTEL_TYPES

# Client portal casts a wider net than the daily DM runs.
BROAD_SEARCH_TERMS = [
    "commercialisation", "valorisation", "market study", "market research",
    "exploitation of results", "startup", "deep tech", "horizon europe",
    "eic accelerator", "investor readiness", "investment readiness",
    "go-to-market", "spin-off", "deeptech", "deep-tech",
    "knowledge valorisation", "pre-commercial", "technology transfer",
    "innovation support", "venture", "spinout",
]


# ─────────────────────────────────────────────────────────────
# FETCH  (uses ted_core; no negative filter, no live/intel split)
# ─────────────────────────────────────────────────────────────
def fetch_notices(days_back: int, status_box) -> list[dict]:
    query = ted_core.make_query(days_back, search_terms=BROAD_SEARCH_TERMS)
    notices, error = ted_core.paginate(
        query, max_pages=MAX_PAGES, progress=status_box.info
    )
    if error:
        status_box.warning(f"Fetch error: {error}")
        return []

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    rows = []
    for raw in notices:
        e = ted_core.extract(raw, desc_limit=2000, include_winner=False)
        if not ted_core.passes_language(e):
            continue
        if ted_core.is_expired_open(e, skip_intel_deadline=True, cutoff=cutoff):
            continue
        rows.append({k: v for k, v in e.items() if k != "deadline_dt"})
    return rows


# ─────────────────────────────────────────────────────────────
# AI FILTER (uses client's company profile)
# ─────────────────────────────────────────────────────────────
def _ask_claude(api_key: str, company_profile: str, title: str,
                buyer: str, description: str) -> tuple[bool, str]:
    prompt = f"""You are evaluating whether a public EU procurement tender is relevant for this company.

COMPANY PROFILE:
{company_profile}

TENDER:
Title: {title}
Buyer: {buyer}
Description: {description or "(not available)"}

Is this tender genuinely relevant for this company?
Answer in exactly this format:
RELEVANT: YES or NO
REASON: one sentence"""

    for attempt in range(3):
        try:
            r = requests.post(
                CLAUDE_URL,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": CLAUDE_MODEL, "max_tokens": 100,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=30,
            )
            if r.status_code == 200:
                text     = r.json()["content"][0]["text"].strip()
                relevant = "RELEVANT: YES" in text.upper()
                reason   = next((l[7:].strip() for l in text.split("\n")
                                 if l.upper().startswith("REASON:")), "")
                return relevant, reason
            elif r.status_code == 429:
                time.sleep(30 * (attempt + 1))
            else:
                return True, f"API error {r.status_code} — kept"
        except Exception as e:
            return True, f"Error: {e} — kept"
    return True, "Max retries — kept"


def load_eit_tenders() -> pd.DataFrame:
    """Load EIT tenders: only YES/MAYBE fit, and not expired."""
    try:
        df = pd.read_csv(EIT_CSV)

        # Keep only YES and MAYBE
        df = df[df["fit"].isin(["YES", "MAYBE"])].copy()

        # Drop rows where deadline has clearly passed
        def is_expired(dl):
            if not dl or pd.isna(dl):
                return False  # no deadline = keep
            dl = str(dl).strip()
            # try ISO format first
            try:
                return pd.to_datetime(dl, dayfirst=False, errors="raise") < pd.Timestamp.now()
            except Exception:
                pass
            # try day-first formats like "15 May 2026"
            try:
                return pd.to_datetime(dl, dayfirst=True, errors="raise") < pd.Timestamp.now()
            except Exception:
                pass
            return False  # can't parse = keep to be safe

        expired_mask = df["call_deadline"].apply(is_expired)
        df = df[~expired_mask].reset_index(drop=True)
        return df
    except FileNotFoundError:
        return pd.DataFrame()


def ai_filter_eit(eit_df: pd.DataFrame, company_profile: str,
                  api_key: str, progress_bar) -> pd.DataFrame:
    """Re-evaluate EIT tenders against the client's profile using Haiku."""
    if eit_df.empty:
        return pd.DataFrame()

    rows    = eit_df.to_dict("records")
    results = []

    def check_one(row):
        desc = str(row.get("call_summary") or row.get("description") or "")[:1000]
        rel, why = _ask_claude(
            api_key, company_profile,
            str(row.get("title", "")),
            str(row.get("source", "")),
            desc,
        )
        return {**row, "ai_reason": why, "relevant": rel}

    with ThreadPoolExecutor(max_workers=AI_WORKERS) as pool:
        futures = {pool.submit(check_one, r): i for i, r in enumerate(rows)}
        for done, fut in enumerate(as_completed(futures), start=1):
            res = fut.result()
            progress_bar.progress(done / len(rows),
                                  text=f"Checking EIT tenders {done}/{len(rows)}...")
            if res["relevant"]:
                results.append(res)

    return pd.DataFrame(results).reset_index(drop=True) if results else pd.DataFrame()


def ai_filter(rows: list[dict], company_profile: str,
              api_key: str, progress_bar, status_box) -> list[dict]:
    results = []
    def check_one(row):
        rel, why = _ask_claude(
            api_key, company_profile,
            row.get("title", ""), row.get("buyer", ""), row.get("description", "")
        )
        return {**row, "ai_reason": why, "relevant": rel}

    with ThreadPoolExecutor(max_workers=AI_WORKERS) as pool:
        futures = {pool.submit(check_one, r): i for i, r in enumerate(rows)}
        for done, fut in enumerate(as_completed(futures), start=1):
            res = fut.result()
            progress_bar.progress(done / len(rows), text=f"AI checking {done}/{len(rows)}...")
            if res["relevant"]:
                results.append(res)

    return results


# ─────────────────────────────────────────────────────────────
# MAIN UI
# ─────────────────────────────────────────────────────────────
st.markdown("# 🔍 TED Tender Intelligence")
st.markdown("Describe your company and we'll find relevant EU public tenders for you.")
st.divider()

col1, col2 = st.columns([3, 1])

with col1:
    company_profile = st.text_area(
        "Your company profile",
        height=220,
        placeholder=(
            "Describe what your company does, which services you offer, "
            "and what kinds of public contracts you want to win.\n\n"
            "Example:\n"
            "We are a biotech consultancy specialising in regulatory strategy "
            "and market access for medical devices at TRL 5-8. We help companies "
            "navigate MDR/IVDR approval and develop go-to-market plans for the EU.\n\n"
            "NOT relevant: construction, IT infrastructure, laboratory equipment procurement."
        ),
    )

with col2:
    days_back = st.slider("Days to look back", min_value=1, max_value=30, value=7)
    include_awarded = st.toggle("Include awarded contracts", value=True,
                                help="Show contracts already awarded (useful for competitor/buyer research)")
    st.write("")
    run_search = st.button("🔍 Find tenders", use_container_width=True, type="primary")

if run_search:
    if not company_profile.strip():
        st.error("Please enter your company profile first.")
        st.stop()

    # Get API key from secrets
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        st.error("API key not configured. Contact DevelopMinded.")
        st.stop()

    with st.spinner(""):
        status_box   = st.empty()
        progress_bar = st.progress(0, text="Starting fetch...")

        # Step 1: fetch
        status_box.info("📡 Fetching TED notices...")
        all_rows = fetch_notices(days_back, status_box)

        if not all_rows:
            st.warning("No notices fetched. Try increasing the days range.")
            st.stop()

        # Filter out awarded if not wanted
        if not include_awarded:
            all_rows = [r for r in all_rows if r["notice_type"] not in INTEL_TYPES]

        status_box.info(f"✅ Fetched {len(all_rows):,} notices. Running AI filter...")
        progress_bar.progress(0, text=f"AI checking 0/{len(all_rows)}...")

        # Step 2: AI filter
        relevant = ai_filter(all_rows, company_profile.strip(), api_key,
                             progress_bar, status_box)

        progress_bar.empty()
        status_box.empty()

    if not relevant:
        st.warning("No relevant tenders found. Try a broader company description or more days.")
        st.stop()

    # ── Results ──────────────────────────────────────────────
    df = pd.DataFrame(relevant)
    today = datetime.now().strftime("%Y-%m-%d")

    open_df   = df[~df["notice_type"].isin(INTEL_TYPES)].copy()
    closed_df = df[df["notice_type"].isin(INTEL_TYPES)].copy()

    st.success(f"Found **{len(relevant)}** relevant tenders ({len(open_df)} open · {len(closed_df)} awarded)")

    # Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total relevant",   len(relevant))
    m2.metric("Open tenders",     len(open_df))
    m3.metric("Awarded contracts", len(closed_df))
    has_value = df["value"].notna().any()
    m4.metric("Avg value", f"€{df['value'].mean():,.0f}" if has_value else "—")

    st.divider()

    DISPLAY_COLS = ["title", "buyer", "country", "deadline", "value", "ai_reason", "link"]

    if not open_df.empty:
        st.markdown("### 🟢 Open Opportunities")
        open_df = open_df.sort_values("deadline")
        cols    = [c for c in DISPLAY_COLS if c in open_df.columns]
        st.dataframe(
            open_df[cols].reset_index(drop=True),
            column_config={
                "link":     st.column_config.LinkColumn("Link", display_text="View"),
                "value":    st.column_config.NumberColumn("Value", format="€%,.0f"),
                "ai_reason": st.column_config.TextColumn("Why relevant", width="large"),
            },
            use_container_width=True,
            height=400,
        )

    if not closed_df.empty and include_awarded:
        st.markdown("### 📊 Awarded Contracts (market intelligence)")
        cols = [c for c in DISPLAY_COLS if c in closed_df.columns]
        st.dataframe(
            closed_df[cols].reset_index(drop=True),
            column_config={
                "link":      st.column_config.LinkColumn("Link", display_text="View"),
                "value":     st.column_config.NumberColumn("Value", format="€%,.0f"),
                "ai_reason": st.column_config.TextColumn("Why relevant", width="large"),
            },
            use_container_width=True,
            height=400,
        )

    # ── EIT Comparison ───────────────────────────────────────────
    eit_raw = load_eit_tenders()
    if not eit_raw.empty:
        st.divider()
        st.markdown("### 🌐 EIT Tenders — comparison")
        st.caption(f"{len(eit_raw)} EIT tenders on file · re-filtering against your profile...")

        eit_progress = st.progress(0, text="Checking EIT tenders...")
        eit_relevant = ai_filter_eit(eit_raw, company_profile.strip(), api_key, eit_progress)
        eit_progress.empty()

        if eit_relevant.empty:
            st.info("No EIT tenders matched your profile.")
        else:
            st.success(f"Found **{len(eit_relevant)}** relevant EIT tenders")
            eit_display_cols = [c for c in
                ["title", "source", "deadline", "call_deadline", "score",
                 "ai_reason", "call_summary", "url"]
                if c in eit_relevant.columns]
            st.dataframe(
                eit_relevant[eit_display_cols].reset_index(drop=True),
                column_config={
                    "url":          st.column_config.LinkColumn("Link", display_text="View"),
                    "score":        st.column_config.NumberColumn("Score", format="%d"),
                    "ai_reason":    st.column_config.TextColumn("Why relevant", width="large"),
                    "call_summary": st.column_config.TextColumn("Summary", width="large"),
                },
                use_container_width=True,
                height=400,
            )
            # merge into combined download
            eit_export = eit_relevant.copy()
            eit_export["notice_type"] = "EIT"
            eit_export = eit_export.rename(columns={"url": "link"})
            df = pd.concat([df, eit_export], ignore_index=True)

    # Download
    st.divider()
    st.download_button(
        "⬇️ Download all results as CSV",
        data=df.drop(columns=["relevant"], errors="ignore").to_csv(index=False).encode(),
        file_name=f"ted_tenders_{today}.csv",
        mime="text/csv",
        use_container_width=True,
    )
