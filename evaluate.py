#!/usr/bin/env python3
"""
EIT Tender Fit Evaluator — DevelopMinded
Uses the Anthropic Claude API to evaluate each scraped tender against the
DevelopMinded company profile, returning a structured fit assessment.

Usage:
    from evaluate import evaluate_all
    results = evaluate_all(tenders)           # uses ANTHROPIC_API_KEY env var
    results = evaluate_all(tenders, api_key="")

Each result dict gains four new keys:
    fit        "YES" | "MAYBE" | "NO"
    score      int 1-10  (10 = perfect fit)
    fit_reason str  one-sentence explanation
    fit_match  str  which DevelopMinded service is most relevant
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

try:
    import anthropic
except ImportError:
    print("Install anthropic: pip install anthropic", file=sys.stderr)
    raise

# ─────────────────────────────────────────────────────────────────────────────
# DevelopMinded company profile
# ─────────────────────────────────────────────────────────────────────────────

DM_PROFILE = """
DevelopMinded is a technology commercialisation consultancy that supports deep tech
spinouts, EIC/Horizon Europe grantees, and research-based ventures. Core services:

- Technology commercialisation and exploitation of research results
- Go-to-market strategy and market intelligence (market sizing, segmentation, competitive analysis)
- Investment readiness and fundraising support (pitch decks, financial modelling, investor targeting)
- EU tender bid preparation (HADEA, EIC, Horizon Europe procurements)
- Partnership strategy and stakeholder outreach
- Regulatory pathway analysis for market entry
- Talent strategy and HR roadmap for scaling ventures
- Evaluation and assessment of investor readiness, innovation programmes, and startup competitions

Ideal clients: EIC Accelerator / EIC Transition / EIC Pathfinder grantees, university spinouts,
deep tech companies (biotech, medtech, cleantech, agtech, defence tech) at TRL 4-7 needing
commercial and strategic support to reach the market.
""".strip()

EVAL_MODEL = "claude-sonnet-4-6"
MAX_CONTENT_CHARS = 4000
MAX_WORKERS = 4
MAX_TOKENS = 600   # increased to accommodate summary + deadline fields

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# PAGE FETCHER
# ─────────────────────────────────────────────────────────────────────────────

def _extract_pdf_text(raw_bytes: bytes) -> str:
    """
    Extract plain text from a PDF byte stream using pdfminer.six.

    PDFs can be very long (50-100 KB of text), so instead of truncating
    from the start we return:
      • the first 2000 chars (overview / executive summary)
      • + a targeted window around the first timeline/deadline table found
        (EIT RFPs always have a "Timelines" / "Submission Deadline" section)

    Both parts combined are kept within MAX_CONTENT_CHARS so the Claude
    call stays affordable.
    """
    try:
        import io
        from pdfminer.high_level import extract_text as _pdf_extract
        raw = _pdf_extract(io.BytesIO(raw_bytes)) or ""
        text = re.sub(r"\s{2,}", " ", raw).strip()
        if not text:
            return ""

        intro = text[:2000]

        # Find the timeline / deadline section and grab a window around it
        deadline_window = ""
        for pattern in [
            r"[Ss]ubmission [Dd]eadline",
            r"[Bb]idders submit proposals",
            r"[Dd]eadline to submit",
            r"[Dd]eadline for submitting",
            r"[Tt]imeline[s]?\b",
            r"[Pp]lanned [Dd]ate",
        ]:
            m = re.search(pattern, text)
            if m:
                start = max(0, m.start() - 200)
                end   = min(len(text), m.start() + 800)
                window = text[start:end]
                if window.strip() not in intro:
                    deadline_window = "\n\n[...TIMELINE/DEADLINE SECTION...]\n\n" + window
                break

        combined = intro + deadline_window
        return combined[:MAX_CONTENT_CHARS]

    except Exception:
        return ""


def fetch_page_text(url: str, timeout: int = 20) -> tuple[str, str]:
    """
    Fetch a URL and return (clean_text, note).
    HTML pages : extracts readable body text via BeautifulSoup.
    PDF pages  : extracts text via pdfminer.six so Claude can read the content
                 and find deadlines, deliverables, etc.
    """
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")

        if "pdf" in content_type or url.lower().endswith(".pdf"):
            text = _extract_pdf_text(resp.content)
            if text:
                return text[:MAX_CONTENT_CHARS], "PDF — text extracted"
            return "", "PDF document — text extraction failed; evaluated from title and description only"

        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", id="content")
            or soup.find("body")
        )
        text = (main or soup).get_text(" ", strip=True)
        text = re.sub(r"\s{2,}", " ", text)
        return text[:MAX_CONTENT_CHARS], ""

    except Exception as e:
        return "", f"Could not fetch page: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATOR
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = f"""You are an expert EU procurement analyst.
Evaluate whether the given tender is a good fit for the consultancy described below.

{DM_PROFILE}

Return ONLY a valid JSON object with exactly these keys:
  "fit"      : "YES" | "MAYBE" | "NO"
  "score"    : integer 1-10 (10 = perfect fit, 1 = completely irrelevant)
  "reason"   : one sentence explaining the match or mismatch
  "match"    : the single most relevant DevelopMinded service, or "none"
  "summary"  : 2-3 sentences describing (a) what this call is about and
               (b) what the contractor must concretely deliver
  "deadline" : the submission deadline date as a string extracted from the
               page content, or "" if not found

Do not add any text outside the JSON object."""


def evaluate_tender(client: "anthropic.Anthropic", tender: dict) -> dict:
    """Evaluate one tender; returns the tender dict enriched with fit fields."""
    result = tender.copy()
    result.update({
        "fit": "ERROR", "score": 0,
        "fit_reason": "", "fit_match": "",
        "call_summary": "", "call_deadline": "",
    })

    page_text, note = fetch_page_text(tender["url"])
    content_section = (
        f"Page content:\n{page_text}" if page_text
        else f"(No page content available — {note})"
    )

    user_msg = (
        f"Tender title : {tender['title']}\n"
        f"Source       : {tender['source']}\n"
        f"Deadline     : {tender['deadline'] or 'unknown'}\n"
        f"Description  : {tender['description'] or 'n/a'}\n\n"
        f"{content_section}\n\n"
        f"Is this tender a fit for DevelopMinded?"
    )

    raw = ""
    try:
        response = client.messages.create(
            model=EVAL_MODEL,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        # Claude sometimes wraps JSON in markdown fences — strip them
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw.strip())
            raw = raw.strip()
        data = json.loads(raw)
        result["fit"]          = str(data.get("fit", "NO")).upper()
        result["score"]        = int(data.get("score", 0))
        result["fit_reason"]   = str(data.get("reason", ""))
        result["fit_match"]    = str(data.get("match", ""))
        result["call_summary"] = str(data.get("summary", ""))
        # Use Claude-extracted deadline only when the scraper found nothing
        claude_dl = str(data.get("deadline", "")).strip()
        result["call_deadline"] = claude_dl if (claude_dl and not result.get("deadline")) else result.get("deadline", "")
    except json.JSONDecodeError:
        result["fit"] = "ERROR"
        result["fit_reason"] = f"Claude returned non-JSON: {raw[:120]}"
    except Exception as e:
        result["fit"] = "ERROR"
        result["fit_reason"] = str(e)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# BATCH RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_all(
    tenders: list[dict],
    api_key: str | None = None,
    max_workers: int = MAX_WORKERS,
    verbose: bool = True,
) -> list[dict]:
    """
    Evaluate all tenders against the DevelopMinded profile.
    Returns a list of tender dicts with added fit, score, fit_reason, fit_match keys.
    Runs max_workers evaluations in parallel (default 4).
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError(
            "Set ANTHROPIC_API_KEY environment variable or pass api_key= argument."
        )

    client = anthropic.Anthropic(api_key=key)
    results: list[dict | None] = [None] * len(tenders)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_idx = {
            pool.submit(evaluate_tender, client, t): i
            for i, t in enumerate(tenders)
        }
        done = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {
                    **tenders[idx],
                    "fit": "ERROR", "score": 0,
                    "fit_reason": str(e), "fit_match": "",
                }
            done += 1
            if verbose:
                t = results[idx]
                dl = t.get("call_deadline") or ""
                dl_str = f"  deadline={dl}" if dl else ""
                print(
                    f"[{done:3}/{len(tenders)}] {t['fit']:5s} "
                    f"(score {t['score']:2}) — {t['title'][:55]}{dl_str}"
                )

    return results
