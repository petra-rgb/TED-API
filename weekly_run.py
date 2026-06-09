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

import calendar
import os
import re
from datetime import UTC, datetime
from datetime import date as _date
from pathlib import Path

import pandas as pd

import evaluate
import scraper

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
    today = datetime.now(UTC).date()
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


# ── Pipeline stages ─────────────────────────────────────────────────────────────
_PLACEHOLDER_COLS = ["id", "source", "title", "url", "deadline", "fit",
                     "score", "fit_reason", "fit_match", "call_summary", "call_deadline"]


def _find_new(all_raw: list[dict], verbose: bool) -> list[dict]:
    """Tenders whose id is not already in the master raw CSV."""
    known_ids: set[str] = set()
    if MASTER_RAW_CSV.exists():
        known_ids = set(pd.read_csv(MASTER_RAW_CSV)["id"].astype(str))
    new_raw = [t for t in all_raw if t["id"] not in known_ids]
    if verbose:
        print(f"     {len(new_raw)} new tender(s) not seen before")
    return new_raw


def _evaluate_new(new_raw: list[dict], api_key: str | None, verbose: bool) -> list[dict]:
    if not new_raw:
        if verbose:
            print("3/4  No new tenders — skipping Claude evaluation")
        return []
    if verbose:
        print(f"3/4  Evaluating {len(new_raw)} new tender(s) with Claude …")
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("Set ANTHROPIC_API_KEY or pass api_key= to weekly_run.run()")
    return evaluate.evaluate_all(new_raw, api_key=key, verbose=verbose)


def _append_master_raw(new_raw: list[dict], verbose: bool) -> None:
    if not new_raw:
        return
    df_raw = pd.read_csv(MASTER_RAW_CSV) if MASTER_RAW_CSV.exists() else pd.DataFrame()
    df_raw = pd.concat([df_raw, pd.DataFrame(new_raw)], ignore_index=True)
    df_raw.to_csv(MASTER_RAW_CSV, index=False)
    if verbose:
        print(f"     Master raw updated: {len(df_raw)} total tenders")


def _append_master_eval(new_evaluated: list[dict], verbose: bool) -> pd.DataFrame:
    df_eval = pd.read_csv(MASTER_EVAL_CSV) if MASTER_EVAL_CSV.exists() else pd.DataFrame()
    if new_evaluated:
        df_eval = pd.concat([df_eval, pd.DataFrame(new_evaluated)], ignore_index=True)
        df_eval.to_csv(MASTER_EVAL_CSV, index=False)
        if verbose:
            print(f"     Master eval updated: {len(df_eval)} total evaluated")
    return df_eval


def _rebuild_active(df_eval: pd.DataFrame, verbose: bool) -> None:
    if df_eval.empty:
        return
    active = [r for r in df_eval.to_dict("records") if not _is_expired(r)]
    pd.DataFrame(active).to_csv(ACTIVE_CSV, index=False)
    if verbose:
        print(f"     Active tenders (Streamlit): {len(active)}")


def _write_new_week(new_evaluated: list[dict]) -> None:
    active_new = [r for r in new_evaluated if not _is_expired(r)] if new_evaluated else []
    if active_new:
        pd.DataFrame(active_new).to_csv(NEW_WEEK_CSV, index=False)
    else:
        # No new active tenders — write a header-only file so the Streamlit page loads.
        pd.DataFrame(columns=_PLACEHOLDER_COLS).to_csv(NEW_WEEK_CSV, index=False)


def _notify(new_evaluated: list[dict], run_time: str, verbose: bool) -> None:
    slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    relevant = [r for r in new_evaluated
                if r.get("fit") in ("YES", "MAYBE") and not _is_expired(r)]
    if relevant:
        notify_slack(slack_url, relevant, run_time[:10])
        if verbose:
            print(f"     Slack notification sent: {len(relevant)} relevant tender(s)")
    elif verbose and slack_url:
        print("     Slack: no new active relevant tenders this week — notification skipped")


def _safe_len(path) -> int:
    try:
        return len(pd.read_csv(path))
    except Exception:
        return 0


def _print_summary(run_time: str, new_raw: list[dict]) -> None:
    print()
    print(f"✅  Done — {run_time}")
    print(f"    New tenders found       : {len(new_raw)}")
    print(f"    New active this week    : {_safe_len(NEW_WEEK_CSV)}")
    print(f"    Total active (Streamlit): {_safe_len(ACTIVE_CSV)}")
    print(f"    Master raw total        : {_safe_len(MASTER_RAW_CSV)}")


# ── Main weekly runner ────────────────────────────────────────────────────────
def run(api_key: str | None = None, verbose: bool = True) -> list[dict]:
    """
    Run the weekly pipeline.
    Returns the list of newly evaluated tender dicts (empty if no new tenders).
    """
    _seed_if_needed()
    run_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if verbose:
        print("─" * 55)
        print(f"EIT Weekly Run  —  {run_time}")
        print("─" * 55)
        print("1/4  Scraping all EIT KIC sites …")

    all_raw = scraper.run_all()
    if verbose:
        print(f"     {len(all_raw)} tenders found across all sites")
        print("2/4  Checking against master list …")
    new_raw = _find_new(all_raw, verbose)
    new_evaluated = _evaluate_new(new_raw, api_key, verbose)

    if verbose:
        print("4/4  Updating master files and Streamlit views …")
    _append_master_raw(new_raw, verbose)
    df_eval = _append_master_eval(new_evaluated, verbose)
    _rebuild_active(df_eval, verbose)
    _write_new_week(new_evaluated)
    _notify(new_evaluated, run_time, verbose)

    if verbose:
        _print_summary(run_time, new_raw)
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
        notify_slack(slack_url, relevant, datetime.now(UTC).strftime("%Y-%m-%d"))
