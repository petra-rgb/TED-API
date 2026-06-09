"""
Shared core for the TED (Tenders Electronic Daily) intelligence pipeline.

Single source of truth for everything the two daily cron scripts
(ted_intelligence.py, ted_intelligence_ai.py) and the Streamlit client portal
(pages/3_Tender_Search.py) used to copy-paste: the TED API query/pagination,
notice extraction, the language/deadline/negative filters, the Claude relevance
filters, and the CSV/XLSX/Slack outputs.

The callers differ only in a few parameters (which this module exposes):
  * skip_intel_deadline — keyword run keeps awarded contracts regardless of
    deadline; the AI run applies the deadline filter uniformly.
  * the DM profile text passed to the AI relevance prompt.
  * the save layout (one combined file vs. live/awarded split).
"""
from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

import anthropic
import pandas as pd
import requests

# ── Configuration ───────────────────────────────────────────────────────────────
DAYS_BACK = int(os.environ.get("DAYS_BACK", "1"))
PAGE_SIZE = 250
MAX_PAGES = 999
DEADLINE_WARN_DAYS = 7

TODAY = datetime.now(UTC)
DEADLINE_CUTOFF = TODAY - timedelta(hours=24)

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
CLAUDE_MODEL = "claude-sonnet-4-6"
INTEL_MODEL = "claude-haiku-4-5"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

ENGLISH_COUNTRIES = {"IRL", "GBR", "MLT", "CYP"}

RESPONSE_FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "buyer-country",
    "notice-type",
    "classification-cpv",
    "description-lot",
    "estimated-value-lot",
    "estimated-value-cur-lot",
    "submission-language",
    "contract-duration-period-lot",
    "deadline-receipt-tender-date-lot",
    "BT-131(d)-Lot",
    "deadline-date-lot",
    "BT-13(t)-Part",
    "winner-name",                   # awarded contractor name(s)
]
CPV_CODES = {
    "73200000": "R&D consultancy services",
    "79410000": "Business & mgmt consultancy",
    "79411100": "Business development consultancy",
    "79419000": "Evaluation consultancy",
}
NEGATIVES = [
    "valorisation énergétique", "valorisation des déchets",
    "valorisation des boues", "valorisation des papiers",
    "valorisation des mâchefers", "valorisation des espaces",
    "valorisation des marques", "valorisation du patrimoine immobilier",
    "valorisation des certificats", "valorisation des actifs immobiliers",
    "unité de valorisation", "centre de valorisation",
    "valorisation foncière", "valorisation du patrimoine bâti",
    "commercialisation de locaux", "commercialisation du patrimoine",
    "commercialisation des actifs", "commercialisation immobilière",
    "gestion locative", "mandat de gestion",
    "locaux commerciaux", "habitations à loyer", "patrimoine résidentiel",
    "noise control", "car park", "parking lot",
    "building maintenance", "cleaning service", "catering service",
    "waste management", "refuse collection", "sludge",
    "fire alarm", "cctv installation", "security guard",
    "grounds maintenance", "road construction", "bridge construction",
    "electrical installation work", "plumbing",
    "refrigerating and freezing", "cryogenic",
    "satellite hardware", "ground station network",
    "site design services", "web portal development", "e-learning platform",
    "bridge cover", "bridge deck", "procurement of a bridge",
    "development of software", "software development services",
    "hardware development", "system integration",
    "cybersecurity research",
    "protected area management", "marine observation",
    "open source maintenance", "linux kernel", "open digital infrastructure",
    "dna extraction", "sequencing", "genomics", "microbial", "cell culture",
    "chromatography", "mass spectrometry", "laboratory equipment",
    "postal service", "postal services",
    "noise pollution", "noise measurement",
    "apartment defect", "defects remediation", "building defect",
    "energy lift", "grid connection works", "district heating",
    "ecological survey", "habitat survey", "biodiversity survey",
    "carbon certification", "blue carbon",
    "web interviewing", "questionnaire", "data collection survey",
    "clinical trial", "randomised controlled", "pharmaceutical supply",
    "it infrastructure", "network installation", "server procurement",
    "temporary staffing", "interim staff", "recruitment services",
    "translation services", "interpretation services",
    "communication campaign", "press office",
    "construction works", "civil engineering", "road works",
]
BROAD_SEARCH_TERMS = [
    "commercialisation", "valorisation", "market study", "market research",
    "exploitation of results", "startup", "deep tech", "horizon europe",
    "eic accelerator", "investor readiness", "investment readiness",
    "go-to-market", "spin-off", "deeptech", "deep-tech",
]
INTEL_TYPES = {"can-standard", "can-social", "can-desg", "can-tran", "can-modif"}

TIER1_INTEL = [
    "technology valorisation", "tech valorisation",
    "technology commercialisation", "tech commercialisation",
    "exploitation of results", "exploitation of project results",
    "exploitation and dissemination", "dissemination and exploitation",
    "eic accelerator", "eic transition", "eic pathfinder",
    "eit digital", "eit manufacturing", "eit health",
    "eit urban mobility", "eit food", "eit rawmaterials",
    "venture building", "venture creation", "startup support services",
    "startup acceleration", "deep tech",
    "investor readiness", "investment readiness",
    "go-to-market strategy", "go-to-market support",
    "innovation ecosystem", "innovation management support",
    "innovation support", "innovation advisory",
]
TIER2_INTEL = [
    "horizon europe", "knowledge transfer", "technology transfer",
    "spin-off", "spinout", "spin-out", "commercialisation", "valorisation",
    "go-to-market", "market intelligence", "market study", "market analysis",
    "competitive analysis", "technology assessment", "feasibility study",
    "business model", "advisory services", "strategic advisory",
    "fundraising support", "market entry", "technology roadmap",
    "innovation strategy", "pitch deck", "investor outreach",
    "partnership strategy", "commercial strategy", "scale-up",
]


# ── Field-level helpers ─────────────────────────────────────────────────────────
def flat(v) -> str:
    """Flatten the TED API's nested string / list / localized-dict values to text."""
    if not v:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return " | ".join(p for p in [flat(i) for i in v] if p)
    if isinstance(v, dict):
        for k in ("eng", "ENG", "fra", "FRA", "nld", "NLD", "deu", "DEU"):
            if v.get(k):
                return flat(v[k])
        for val in v.values():
            s = flat(val)
            if s:
                return s
    return str(v).strip() if v else ""


def parse_deadline(raw):
    """Parse a TED deadline value (str / list / dict) into a tz-aware datetime, or None."""
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if isinstance(raw, dict):
        raw = next(iter(raw.values()), None)
    if not raw or not isinstance(raw, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d%z", "%Y-%m-%d"):
        try:
            s = raw[:25]
            if fmt == "%Y-%m-%d%z" and len(raw) > 10:
                s = raw
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return None


def is_negative(title: str, buyer: str) -> bool:
    text = f"{title} {buyer}".lower()
    return any(neg in text for neg in NEGATIVES)


def get_bucket(ntype: str) -> str:
    return "Market intelligence" if ntype in INTEL_TYPES else "Live opportunity"


def _first(seq, default=""):
    """First element of a non-empty list, else `default`."""
    return seq[0] if isinstance(seq, list) and seq else default


def _cpv_list(cpv_raw) -> list:
    if isinstance(cpv_raw, list):
        return list(dict.fromkeys(cpv_raw))
    return [cpv_raw] if cpv_raw else []


def _languages(lang_raw) -> str:
    return ", ".join(lang_raw) if isinstance(lang_raw, list) else str(lang_raw or [])


def _duration(dur_raw) -> str:
    d = _first(dur_raw, None)
    if isinstance(d, dict):
        return f"{d.get('value', '?')} {d.get('unit', '').lower()}"
    return "—"


def _value(val_raw):
    v = _first(val_raw, None)
    return float(v) if v is not None else None


def _description(desc_raw, limit: int) -> str:
    if isinstance(desc_raw, dict):
        text = desc_raw.get("eng") or desc_raw.get("ENG") or next(iter(desc_raw.values()), None)
        if isinstance(text, list):
            text = " ".join(text)
    elif isinstance(desc_raw, list):
        text = " ".join(str(x) for x in desc_raw)
    else:
        text = str(desc_raw) if desc_raw else ""
    return (text or "")[:limit]


def _deadline(raw: dict):
    """First parseable deadline across the four TED deadline fields, or None."""
    for field in ("deadline-receipt-tender-date-lot", "BT-131(d)-Lot",
                  "deadline-date-lot", "BT-13(t)-Part"):
        dt = parse_deadline(raw.get(field))
        if dt:
            return dt
    return None


def _winner(winner_raw) -> str:
    if isinstance(winner_raw, dict):
        names = winner_raw.get("eng") or winner_raw.get("ENG") or next(iter(winner_raw.values()), [])
        if isinstance(names, str):
            names = [names]
    elif isinstance(winner_raw, list):
        names = winner_raw
    else:
        names = []
    return " | ".join(str(n).strip() for n in names if n) or ""


def extract(raw: dict, *, desc_limit: int = 3000, include_winner: bool = True) -> dict:
    """Map one raw TED notice to the flat row dict used downstream.

    `desc_limit`/`include_winner` reproduce the small differences between the cron
    scripts (3000 chars + winner) and the client portal (2000 chars, no winner).
    """
    pub = flat(raw.get("publication-number")) or "—"
    dl_dt = _deadline(raw)
    row = {
        "pub_num":     pub,
        "title":       flat(raw.get("notice-title")) or "—",
        "buyer":       flat(raw.get("buyer-name")) or "—",
        "notice_type": flat(raw.get("notice-type")) or "—",
        "cpv":         ", ".join(_cpv_list(raw.get("classification-cpv") or [])[:4]),
        "deadline_dt": dl_dt,
        "deadline":    dl_dt.strftime("%Y-%m-%d") if dl_dt else "—",
        "link":        f"https://ted.europa.eu/en/notice/-/detail/{pub}" if pub != "—" else "",
        "value":       _value(raw.get("estimated-value-lot")),
        "currency":    _first(raw.get("estimated-value-cur-lot"), ""),
        "languages":   _languages(raw.get("submission-language") or []),
        "duration":    _duration(raw.get("contract-duration-period-lot")),
        "country":     _first(raw.get("buyer-country") or [], ""),
        "description": _description(raw.get("description-lot") or {}, desc_limit),
    }
    if include_winner:
        row["winner"] = _winner(raw.get("winner-name") or {})
    return row


# ── Query + pagination ──────────────────────────────────────────────────────────
def make_query(days_back: int = DAYS_BACK, *,
               search_terms: Sequence[str] = BROAD_SEARCH_TERMS,
               cpv_codes: Iterable[str] = CPV_CODES) -> str:
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    cpv_part = " OR ".join(f'classification-cpv = "{c}"' for c in cpv_codes)
    kw_part = " OR ".join(f'FT ~ "{k}"' for k in search_terms)
    return f"(({cpv_part}) OR ({kw_part})) AND publication-date >= {since}"


def _fetch_page(payload: dict):
    """One TED search page → (notices, error, next_token, total). Retries 429 thrice."""
    for attempt in range(3):
        try:
            r = requests.post(SEARCH_URL, json=payload, timeout=60)
        except requests.RequestException as e:
            return None, str(e), None, "?"
        if r.status_code == 200:
            d = r.json()
            return (d.get("notices", []), None,
                    d.get("iterationNextToken"), d.get("totalNoticeCount", "?"))
        if r.status_code == 429:
            time.sleep(35 * (attempt + 1))
        else:
            return None, f"{r.status_code}: {r.text[:100]}", None, "?"
    return None, "Max retries", None, "?"


def paginate(query: str, *, page_size: int = PAGE_SIZE, max_pages: int = MAX_PAGES,
             progress: Callable[[str], None] | None = None) -> tuple[list[dict], str | None]:
    """Iterate the TED search API until exhausted/capped. Returns (notices, error)."""
    all_notices: list[dict] = []
    token, page = None, 0
    while page < max_pages:
        payload = {
            "query": query, "fields": RESPONSE_FIELDS,
            "limit": page_size, "scope": "ACTIVE",
            "checkQuerySyntax": False,
            "paginationMode": "ITERATION",
            "onlyLatestVersions": True,
        }
        if token:
            payload["iterationNextToken"] = token
        notices, err, token, total = _fetch_page(payload)
        if err:
            return all_notices, err
        if not notices:
            break
        all_notices.extend(notices)
        page += 1
        if progress:
            progress(f"Fetched {len(all_notices):,} / {total} notices...")
        if not token:
            break
        if page % 10 == 0:
            time.sleep(0.5)
    return all_notices, None


# ── Filtering ───────────────────────────────────────────────────────────────────
def passes_language(e: dict) -> bool:
    """Keep ENG/NLD notices, plus any notice from a primarily-English-speaking country."""
    langs = e.get("languages", "").upper()
    if langs and "ENG" not in langs and "NLD" not in langs:
        return e.get("country", "") in ENGLISH_COUNTRIES
    return True


def is_expired_open(e: dict, *, skip_intel_deadline: bool, cutoff: datetime = DEADLINE_CUTOFF) -> bool:
    """True if the notice should be dropped for a past deadline.

    Awarded/intel notices have deadlines in the past by nature; when
    `skip_intel_deadline` is set they bypass this check (keyword run behaviour).
    Long-running callers (the Streamlit portal) pass a fresh `cutoff` per request;
    the short-lived cron scripts use the import-time default.
    """
    if skip_intel_deadline and e["notice_type"] in INTEL_TYPES:
        return False
    dt = e["deadline_dt"]
    return dt is not None and dt < cutoff


def _to_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).reset_index(drop=True) if rows else pd.DataFrame()


def fetch_ted(days_back: int = DAYS_BACK, *, skip_intel_deadline: bool,
              progress: Callable[[str], None] | None = None
              ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch + filter + split TED notices into (live opportunities, market intel)."""
    query = make_query(days_back)
    notices, error = paginate(query, progress=progress)
    if error and progress:
        progress(f"Error: {error}")
    if not notices:
        return pd.DataFrame(), pd.DataFrame()

    live_rows, intel_rows = [], []
    for raw in notices:
        e = extract(raw)
        if not passes_language(e):
            continue
        if is_expired_open(e, skip_intel_deadline=skip_intel_deadline):
            continue
        if is_negative(e["title"], e["buyer"]):
            continue
        row = {k: v for k, v in e.items() if k != "deadline_dt"}
        row["bucket"] = get_bucket(e["notice_type"])
        (intel_rows if row["bucket"] == "Market intelligence" else live_rows).append(row)
    return _to_df(live_rows), _to_df(intel_rows)


# ── Claude relevance filters ────────────────────────────────────────────────────
_clients: dict[str, anthropic.Anthropic] = {}


def claude_client(api_key: str) -> anthropic.Anthropic:
    """A cached Anthropic SDK client per key (the SDK handles 429/5xx retries)."""
    if api_key not in _clients:
        _clients[api_key] = anthropic.Anthropic(api_key=api_key, max_retries=4)
    return _clients[api_key]


def _relevance_reason(text: str) -> tuple[bool, str]:
    relevant = "RELEVANT: YES" in text.upper()
    reason = next((line[7:].strip() for line in text.split("\n")
                   if line.upper().startswith("REASON:")), "")
    return relevant, reason


def _ask_claude(profile: str, title: str, buyer: str, notice_text: str, *,
                api_key: str = ANTHROPIC_API_KEY, model: str = CLAUDE_MODEL):
    """Ask Claude whether a tender is relevant. Returns (relevant, reason).

    Keeps the tender on any API failure (never silently drops). The stable
    instruction+profile prefix is cached, so a whole run pays for it once.
    """
    if not api_key:
        return True, "No API key — kept"
    system = [{
        "type": "text",
        "text": ("You are evaluating whether a public procurement tender is relevant "
                 f"for DevelopMinded.\n\n{profile}\n\nAnswer in exactly this format:\n"
                 "RELEVANT: YES or NO\nREASON: one sentence"),
        "cache_control": {"type": "ephemeral"},
    }]
    user = (f"TENDER TITLE: {title}\nBUYER: {buyer}\nNOTICE TEXT:\n"
            f"{notice_text or '(not available — judge on title and buyer only)'}\n\n"
            "Is this tender genuinely relevant for DevelopMinded?")
    try:
        resp = claude_client(api_key).messages.create(
            model=model, max_tokens=150, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return _relevance_reason(resp.content[0].text.strip())
    except anthropic.RateLimitError:
        return True, "Max retries (429) — kept"
    except anthropic.APIStatusError as e:
        return True, f"API error {e.status_code} — kept"
    except Exception as e:
        return True, f"Error: {e} — kept"


def ai_filter(live: pd.DataFrame, *, profile: str, api_key: str = ANTHROPIC_API_KEY,
              model: str = CLAUDE_MODEL, workers: int = 1,
              log: Callable[[str], None] = print) -> pd.DataFrame:
    """Keep only AI-relevant live opportunities, adding ai_relevant / ai_reason."""
    if live.empty:
        log("Nothing to filter.")
        return live

    def check_one(row):
        rel, why = _ask_claude(profile, row.get("title", ""), row.get("buyer", ""),
                               row.get("description", "") or "", api_key=api_key, model=model)
        return {**row, "ai_relevant": rel, "ai_reason": why}

    rows, results = live.to_dict("records"), []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check_one, r): i for i, r in enumerate(rows)}
        for done, fut in enumerate(as_completed(futures), start=1):
            res = fut.result()
            icon = "✅" if res["ai_relevant"] else "❌"
            log(f"  [{done:2d}/{len(rows)}] {icon}  {str(res.get('title', ''))[:65]}")
            results.append(res)
    df = pd.DataFrame(results)
    kept = df[df["ai_relevant"]].reset_index(drop=True)
    log(f"\n✅ Kept {len(kept)}  |  ❌ Removed {len(df) - len(kept)}")
    return kept


def _raw_score_intel(row) -> int:
    text = f"{row.get('title', '')} {row.get('buyer', '')} {row.get('description', '')}".lower()
    t1 = sum(1 for t in TIER1_INTEL if t in text)
    t2 = sum(1 for t in TIER2_INTEL if t in text)
    return 7 * t1 + 3 * t2


def _parse_response(text: str) -> dict:
    text = re.sub(r"```json\s*|\s*```", "", text).strip()
    return json.loads(text)


def ai_filter_intel(intel: pd.DataFrame, *, api_key: str = ANTHROPIC_API_KEY,
                    model: str = INTEL_MODEL, log: Callable[[str], None] = print) -> pd.DataFrame:
    """Filter awarded-contract rows with a keyword pre-filter + Haiku relevance check."""
    if intel.empty:
        log("No intel rows to filter.")
        return intel
    if not api_key:
        log("No ANTHROPIC_API_KEY — skipping intel AI filter, keeping all intel rows.")
        return intel

    candidates = intel[intel.apply(_raw_score_intel, axis=1) >= 3].copy()
    log(f"Intel AI filter — {len(candidates)} candidates "
        f"(skipped {len(intel) - len(candidates)} below keyword threshold)")
    if candidates.empty:
        return pd.DataFrame()

    client = claude_client(api_key)
    results = []
    for i, (_, row) in enumerate(candidates.iterrows()):
        relevant = _intel_relevant(client, model, row, i, log)
        if relevant:
            results.append(row)
    out = pd.DataFrame(results).reset_index(drop=True) if results else pd.DataFrame()
    log(f"✅ Intel kept: {len(out)}  |  ❌ Removed: {len(candidates) - len(out)}")
    return out


def _intel_relevant(client, model, row, i, log) -> bool:
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=60,
            messages=[{"role": "user", "content": (
                "Is this EU awarded contract relevant for a tech commercialisation "
                "consultancy (EIC/Horizon spinouts, investor readiness, go-to-market, deep tech)?\n"
                f"Title: {str(row['title'])[:200]}\n"
                f"Buyer: {str(row['buyer'])[:100]}\n"
                'Reply JSON only: {"relevant":true} or {"relevant":false}'
            )}],
        )
        return _parse_response(resp.content[0].text).get("relevant", False)
    except Exception as e:
        log(f"  Row {i}: {e} — keeping row")
        return True  # keep on error to avoid silent drops


# ── Output: CSV / XLSX / Slack ──────────────────────────────────────────────────
def _merge_csv(csv_file: str, new_rows: pd.DataFrame, log: Callable[[str], None]) -> None:
    try:
        existing = pd.read_csv(csv_file)
        combined = pd.concat([existing, new_rows], ignore_index=True)
        combined = combined.drop_duplicates(subset=["pub_num"], keep="last")
    except FileNotFoundError:
        combined = new_rows
    combined = combined.sort_values("fetched_date", ascending=False).reset_index(drop=True)
    combined.to_csv(csv_file, index=False)
    log(f"Saved → {csv_file}  ({len(combined):,} total rows, {len(new_rows)} new today)")


def _stamp(df: pd.DataFrame, today: str) -> pd.DataFrame:
    out = df.copy()
    out["fetched_date"] = today
    return out


def save_results(live: pd.DataFrame, intel: pd.DataFrame, *, csv_file: str,
                 intel_file: str | None = None, log: Callable[[str], None] = print) -> None:
    """Persist results.

    intel_file is None -> live + intel concatenated into csv_file (AI run layout).
    intel_file given   -> live -> csv_file, intel -> intel_file (keyword run layout).
    """
    if live.empty and intel.empty:
        log("Nothing to save.")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    if intel_file is None:
        frames = [_stamp(df, today) for df in (live, intel) if not df.empty]
        _merge_csv(csv_file, pd.concat(frames, ignore_index=True), log)
    else:
        if not live.empty:
            _merge_csv(csv_file, _stamp(live, today), log)
        if not intel.empty:
            _merge_csv(intel_file, _stamp(intel, today), log)


def export_xlsx(live: pd.DataFrame, intel: pd.DataFrame, filename: str = "ted_tenders_ai.xlsx",
                log: Callable[[str], None] = print) -> None:
    if live.empty and intel.empty:
        log("Nothing to export.")
        return
    live_cols = ["deadline", "title", "buyer", "country", "value", "currency",
                 "duration", "cpv", "notice_type", "ai_reason", "description", "link"]
    intel_cols = ["deadline", "title", "buyer", "winner", "country", "value", "currency",
                  "notice_type", "link"]
    with pd.ExcelWriter(filename, engine="openpyxl") as w:
        for df, sheet, cols in [(live, "AI Relevant", live_cols),
                                (intel, "Market Intelligence", intel_cols)]:
            if df.empty:
                continue
            out = df[[c for c in cols if c in df.columns]]
            out.to_excel(w, index=False, sheet_name=sheet)
            ws = w.sheets[sheet]
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    max(len(str(c.value or "")) for c in col) + 4, 60)
    log(f"Exported → {filename}  |  AI Relevant: {len(live)}  |  Intel: {len(intel)}")


def _urgent_block(live: pd.DataFrame, today: str, cutoff: str) -> tuple[list, set]:
    blocks, urgent_pubs = [], set()
    if live.empty or "deadline" not in live.columns:
        return blocks, urgent_pubs
    urgent = live[
        (live["deadline"] != "—") & (live["deadline"] <= cutoff) & (live["deadline"] >= today)
    ].sort_values("deadline").head(5)
    if urgent.empty:
        return blocks, urgent_pubs
    blocks.append(_section(f":alarm_clock: *Deadlines within {DEADLINE_WARN_DAYS} days*"))
    for _, r in urgent.iterrows():
        urgent_pubs.add(r.get("pub_num", ""))
        blocks.append(_tender_block(r, r["deadline"]))
    return blocks, urgent_pubs


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _tender_block(r, deadline) -> dict:
    return _section(
        f"*<{r.get('link', '')}|{str(r['title'])[:80]}>*\n"
        f"Buyer: {r['buyer']}  |  Deadline: {deadline}\n"
        f"_{r.get('ai_reason', '')}_"
    )


def send_slack_digest(live: pd.DataFrame, intel: pd.DataFrame, *,
                      webhook_url: str = SLACK_WEBHOOK_URL,
                      log: Callable[[str], None] = print) -> None:
    if not webhook_url:
        log("No SLACK_WEBHOOK_URL — skipping Slack.")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() + timedelta(days=DEADLINE_WARN_DAYS)).strftime("%Y-%m-%d")
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"TED AI Intelligence — {today}"}},
        _section(f"*{len(live)}* AI-relevant opportunities  |  *{len(intel)}* market intel"),
        {"type": "divider"},
    ]
    urgent_blocks, urgent_pubs = _urgent_block(live, today, cutoff)
    blocks += urgent_blocks
    if not live.empty:
        top = live[~live["pub_num"].isin(urgent_pubs)].head(5)
        if not top.empty:
            blocks.append(_section(":green_circle: *Top AI-Relevant Opportunities*"))
            blocks += [_tender_block(r, r.get("deadline", "—")) for _, r in top.iterrows()]
    blocks += [
        {"type": "divider"},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": "DevelopMinded TED AI Intelligence — automated daily fetch"}
        ]},
    ]
    try:
        r = requests.post(webhook_url, json={"blocks": blocks}, timeout=15)
        log("Slack digest sent ✓" if r.status_code == 200 else f"Slack error {r.status_code}: {r.text}")
    except Exception as e:
        log(f"Slack send failed: {e}")
