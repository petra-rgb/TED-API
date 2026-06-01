#!/usr/bin/env python3
"""
Weekly EIT tender runner — DevelopMinded
Scrapes all EIT KIC sites, finds tenders not yet in the master list,
evaluates only NEW ones with Claude, and updates the Streamlit data files.

From Jupyter:
    import importlib, weekly_run
    importlib.reload(weekly_run)
    results = weekly_run.run(api_key="sk-ant-...")

From command line:
    python weekly_run.py
    python weekly_run.py sk-ant-...      # pass key as argument
"""

import importlib
import os
import re
import calendar
import pandas as pd
from datetime import datetime, timezone, date as _date
from pathlib import Path

import scraper
import evaluate

importlib.reload(scraper)
importlib.reload(evaluate)

# ── File paths ────────────────────────────────────────────────────────────────
OUTPUT          = Path("output")
MASTER_RAW_CSV  = OUTPUT / "all_tenders_master.csv"   # every tender ever scraped (raw)
MASTER_EVAL_CSV = OUTPUT / "evaluated_master.csv"     # every evaluated tender
ACTIVE_CSV      = OUTPUT / "active_tenders.csv"       # open + evaluated → Streamlit main view
NEW_WEEK_CSV    = OUTPUT / "new_this_week.csv"        # new this run → Streamlit "new" section

OUTPUT.mkdir(exist_ok=True)

# ── Enhanced deadline parser (handles Claude's output formats) ────────────────
_MONTHS_RE = (
    "January|February|March|April|May|June|July|August|"
    "September|October|November|December"
)

def _smart_parse(text) -> "_date | None":
    """Parse a deadline string → date, with extra handling for edge cases."""
    if not text or str(text).strip() in ("", "nan"):
        return None
    text = str(text).strip()
    # "End of [Month] [Year]" → last day of that month
    m = re.search(rf"[Ee]nd\s+of\s+({_MONTHS_RE})\s+(\d{{4}})", text)
    if m:
        try:
            mo = datetime.strptime(m.group(1), "%B").month
            last_day = calendar.monthrange(int(m.group(2)), mo)[1]
            return _date(int(m.group(2)), mo, last_day)
        except Exception:
            pass
    # "DD/DD Month YYYY" range (e.g. "15/22 May 2026") → take the later date
    m = re.search(rf"(\d{{1,2}})/(\d{{1,2}})\s+({_MONTHS_RE})\s+(\d{{4}})", text)
    if m:
        try:
            return datetime.strptime(f"{m.group(2)} {m.group(3)} {m.group(4)}", "%d %B %Y").date()
        except Exception:
            pass
    return scraper.parse_deadline(text)


def _is_expired(row: dict) -> bool:
    """Return True if the tender has a confirmed past deadline."""
    today = datetime.now(timezone.utc).date()
    for col in ("deadline", "call_deadline"):
        val = str(row.get(col, "") or "").strip()
        if val and val != "nan":
            parsed = _smart_parse(val)
            if parsed and parsed < today:
                return True
    return False


# ── First-run: seed master CSVs from existing output files ───────────────────
def _seed_if_needed():
    """On first run, seed master CSVs from whatever CSVs already exist."""
    if not MASTER_RAW_CSV.exists():
        # Find most recent tenders_*.csv (raw scrape)
        candidates = sorted(OUTPUT.glob("tenders_*.csv"))
        if candidates:
            src = candidates[-1]
            pd.read_csv(src).to_csv(MASTER_RAW_CSV, index=False)
            n = len(pd.read_csv(MASTER_RAW_CSV))
            print(f"  ↳ Seeded master raw from {src.name}  ({n} rows)")
        else:
            print("  ↳ No existing raw CSV found — master will be built from scratch")

    if not MASTER_EVAL_CSV.exists():
        # Find most recent evaluated_tenders_*.csv (not _final or _active)
        candidates = sorted([
            f for f in OUTPUT.glob("evaluated_tenders_*.csv")
            if "_final" not in f.name and "_active" not in f.name
        ])
        if candidates:
            src = candidates[-1]
            pd.read_csv(src).to_csv(MASTER_EVAL_CSV, index=False)
            n = len(pd.read_csv(MASTER_EVAL_CSV))
            print(f"  ↳ Seeded master eval from {src.name}  ({n} rows)")
        else:
            print("  ↳ No existing evaluated CSV found — will evaluate all on first run")


# ── Main weekly runner ────────────────────────────────────────────────────────
def run(api_key: str = None, verbose: bool = True) -> list[dict]:
    """
    Run the weekly pipeline.
    Returns the list of newly evaluated tender dicts (empty if no new tenders).
    """
    _seed_if_needed()
    run_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── 1. Scrape all sites ───────────────────────────────────────────────────
    if verbose:
        print("─" * 55)
        print(f"EIT Weekly Run  —  {run_time}")
        print("─" * 55)
        print("1/4  Scraping all EIT KIC sites …")
    all_raw = scraper.run_all()
    if verbose:
        print(f"     {len(all_raw)} tenders found across all sites")

    # ── 2. Find tenders not in master list ────────────────────────────────────
    if verbose:
        print("2/4  Checking against master list …")
    known_ids: set[str] = set()
    if MASTER_RAW_CSV.exists():
        known_ids = set(pd.read_csv(MASTER_RAW_CSV)["id"].astype(str))
    new_raw = [t for t in all_raw if t["id"] not in known_ids]
    if verbose:
        print(f"     {len(new_raw)} new tender(s) not seen before")

    # ── 3. Evaluate only new tenders with Claude ──────────────────────────────
    new_evaluated: list[dict] = []
    if new_raw:
        if verbose:
            print(f"3/4  Evaluating {len(new_raw)} new tender(s) with Claude …")
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("Set ANTHROPIC_API_KEY or pass api_key= to weekly_run.run()")
        new_evaluated = evaluate.evaluate_all(new_raw, api_key=key, verbose=verbose)
    else:
        if verbose:
            print("3/4  No new tenders — skipping Claude evaluation")

    # ── 4. Update master CSVs and rebuild Streamlit views ────────────────────
    if verbose:
        print("4/4  Updating master files and Streamlit views …")

    # Append new raw tenders to master raw
    if new_raw:
        df_raw = pd.read_csv(MASTER_RAW_CSV) if MASTER_RAW_CSV.exists() else pd.DataFrame()
        df_raw = pd.concat([df_raw, pd.DataFrame(new_raw)], ignore_index=True)
        df_raw.to_csv(MASTER_RAW_CSV, index=False)
        if verbose:
            print(f"     Master raw updated: {len(df_raw)} total tenders")

    # Append new evaluated tenders to master eval
    df_eval = pd.read_csv(MASTER_EVAL_CSV) if MASTER_EVAL_CSV.exists() else pd.DataFrame()
    if new_evaluated:
        df_eval = pd.concat([df_eval, pd.DataFrame(new_evaluated)], ignore_index=True)
        df_eval.to_csv(MASTER_EVAL_CSV, index=False)
        if verbose:
            print(f"     Master eval updated: {len(df_eval)} total evaluated")

    # Rebuild active_tenders.csv — all evaluated tenders that aren't expired
    if not df_eval.empty:
        records = df_eval.to_dict("records")
        active  = [r for r in records if not _is_expired(r)]
        pd.DataFrame(active).to_csv(ACTIVE_CSV, index=False)
        if verbose:
            print(f"     Active tenders (Streamlit): {len(active)}")

    # Save new_this_week.csv — new evaluated tenders that aren't expired
    _placeholder_cols = ["id", "source", "title", "url", "deadline", "fit",
                         "score", "fit_reason", "fit_match", "call_summary", "call_deadline"]
    if new_evaluated:
        active_new = [r for r in new_evaluated if not _is_expired(r)]
        if active_new:
            pd.DataFrame(active_new).to_csv(NEW_WEEK_CSV, index=False)
        else:
            # All new tenders were expired — write header-only file
            pd.DataFrame(columns=_placeholder_cols).to_csv(NEW_WEEK_CSV, index=False)
    else:
        pd.DataFrame(columns=_placeholder_cols).to_csv(NEW_WEEK_CSV, index=False)

    # ── Slack notification ────────────────────────────────────────────────────
    slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    relevant_active = [
        r for r in new_evaluated
        if r.get("fit") in ("YES", "MAYBE") and not _is_expired(r)
    ]
    if relevant_active:
        notify_slack(slack_url, relevant_active, run_time[:10])
        if verbose:
            print(f"     Slack notification sent: {len(relevant_active)} relevant tender(s)")
    elif verbose and slack_url:
        print("     Slack: no new active relevant tenders this week — notification skipped")

    # ── Summary ───────────────────────────────────────────────────────────────
    if verbose:
        def _safe_len(path):
            try:
                return len(pd.read_csv(path))
            except Exception:
                return 0
        n_active     = _safe_len(ACTIVE_CSV)
        n_new_active = _safe_len(NEW_WEEK_CSV)
        print()
        print(f"✅  Done — {run_time}")
        print(f"    New tenders found       : {len(new_raw)}")
        print(f"    New active this week    : {n_new_active}")
        print(f"    Total active (Streamlit): {n_active}")
        print(f"    Master raw total        : {_safe_len(MASTER_RAW_CSV)}")

    return new_evaluated


# ── Slack notification ────────────────────────────────────────────────────────
def notify_slack(webhook_url: str, new_relevant: list[dict], run_date: str):
    """
    Post new YES/MAYBE tenders to Slack via an incoming webhook.
    Set SLACK_WEBHOOK_URL in GitHub Secrets (and Streamlit Secrets if needed).
    """
    if not webhook_url or not new_relevant:
        return
    try:
        import requests as _req
    except ImportError:
        print("  requests not installed — skipping Slack notification")
        return

    lines = [
        f"🏛️ *EIT Weekly Update — {run_date}*",
        f"{len(new_relevant)} new relevant tender(s) found\n",
    ]
    for r in new_relevant[:10]:
        fit     = str(r.get("fit", ""))
        score   = r.get("score", 0)
        title   = str(r.get("title", ""))
        source  = str(r.get("source", ""))
        url     = str(r.get("url", ""))
        dl      = str(r.get("call_deadline") or r.get("deadline") or "unknown")
        summary = str(r.get("call_summary", "") or "")
        badge   = "✅" if fit == "YES" else "🟡"

        lines.append(f"{badge} *{fit} {score}/10* — <{url}|{title}>")
        lines.append(f"_{source}_ · 📅 {dl}")
        if summary and summary != "nan":
            lines.append(f">{summary[:220]}")
        lines.append("")

    try:
        resp = _req.post(webhook_url, json={"text": "\n".join(lines)}, timeout=10)
        resp.raise_for_status()
        print(f"  Slack notification sent ({len(new_relevant)} tender(s))")
    except Exception as e:
        print(f"  Slack notification failed: {e}")


if __name__ == "__main__":
    import sys
    key         = sys.argv[1] if len(sys.argv) > 1 else None
    slack_url   = os.environ.get("SLACK_WEBHOOK_URL", "")
    results     = run(api_key=key)
    # Notify Slack about new YES/MAYBE tenders
    relevant = [r for r in results if r.get("fit") in ("YES", "MAYBE")]
    if relevant:
        notify_slack(slack_url, relevant, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
