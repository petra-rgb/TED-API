import requests, time, os
import pandas as pd
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

DAYS_BACK          = int(os.environ.get("DAYS_BACK", "1"))
PAGE_SIZE          = 250
MAX_PAGES          = 999
AI_WORKERS         = 1
DEADLINE_WARN_DAYS = 7

TODAY           = datetime.now(timezone.utc)
DEADLINE_CUTOFF = TODAY - timedelta(hours=24)

SEARCH_URL        = "https://api.ted.europa.eu/v3/notices/search"
CLAUDE_URL        = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-haiku-4-5-20251001"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

DM_PROFILE = """
DevelopMinded is a technology commercialisation consultancy that supports deep tech spinouts,
EIC/Horizon Europe grantees, and research-based ventures. Our core services are:
- Technology commercialisation and exploitation of research results
- Go-to-market strategy and market intelligence (market sizing, segmentation, competitive analysis)
- Investment readiness and fundraising support (pitch decks, financial modelling, investor targeting)
- EU tender bid preparation (e.g. HADEA, EIC, Horizon Europe procurements)
- Partnership strategy and stakeholder outreach
- Regulatory pathway analysis for market entry
- Talent strategy and HR roadmap for scaling ventures
- Evaluation and assessment of investor readiness, innovation programmes, and startup competitions

Ideal clients: EIC Accelerator / EIC Transition / EIC Pathfinder grantees, university spinouts,
deep tech companies (biotech, medtech, cleantech, agtech, defence tech) at TRL 4-7 needing
commercial and strategic support to reach the market.

NOT relevant: running clinical trials, lab/research execution, software development,
infrastructure/construction management, policy research, academic surveys, open source
maintenance, ecological studies, or procurements for physical goods/equipment.
"""

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
]
CPV_CODES = {
    "73200000": "R&D consultancy services",
    "79410000": "Business & mgmt consultancy",
    "79411100": "Business development consultancy",
    "79419000": "Evaluation consultancy",
}

BROAD_SEARCH_TERMS = [
    "commercialisation", "valorisation", "market study", "market research",
    "exploitation of results", "startup", "deep tech", "horizon europe",
    "eic accelerator", "investor readiness", "investment readiness",
    "go-to-market", "spin-off", "deeptech", "deep-tech",
]
INTEL_TYPES = {"can-standard", "can-social", "can-desg", "can-tran", "can-modif"}
def flat(v) -> str:
    if not v: return ""
    if isinstance(v, str): return v.strip()
    if isinstance(v, list):
        return " | ".join(p for p in [flat(i) for i in v] if p)
    if isinstance(v, dict):
        for k in ("eng", "ENG", "fra", "FRA", "nld", "NLD", "deu", "DEU"):
            if k in v and v[k]: return flat(v[k])
        for val in v.values():
            s = flat(val)
            if s: return s
    return str(v).strip() if v else ""


def parse_deadline(raw):
    if not raw: return None
    if isinstance(raw, list): raw = raw[0] if raw else None
    if isinstance(raw, dict): raw = next(iter(raw.values()), None)
    if not raw or not isinstance(raw, str): return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d%z", "%Y-%m-%d"):
        try:
            s = raw[:25]
            if fmt == "%Y-%m-%d%z" and len(raw) > 10:
                s = raw
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def is_negative(title: str, buyer: str) -> bool:
    text = f"{title} {buyer}".lower()
    return any(neg in text for neg in NEGATIVES)


def get_bucket(ntype: str) -> str:
    return "Market intelligence" if ntype in INTEL_TYPES else "Live opportunity"


def extract(raw):
    pub   = flat(raw.get("publication-number")) or "—"
    title = flat(raw.get("notice-title"))       or "—"
    buyer = flat(raw.get("buyer-name"))         or "—"
    ntype = flat(raw.get("notice-type"))        or "—"
    dl_dt = (
        parse_deadline(raw.get("deadline-receipt-tender-date-lot"))
        or parse_deadline(raw.get("BT-131(d)-Lot"))
        or parse_deadline(raw.get("deadline-date-lot"))
        or parse_deadline(raw.get("BT-13(t)-Part"))
    )
    cpv_raw  = raw.get("classification-cpv") or []
    cpv_list = list(dict.fromkeys(cpv_raw)) if isinstance(cpv_raw, list) else ([cpv_raw] if cpv_raw else [])
    val_raw  = raw.get("estimated-value-lot")
    value    = float(val_raw[0]) if isinstance(val_raw, list) and val_raw else None
    cur_raw  = raw.get("estimated-value-cur-lot")
    currency = cur_raw[0] if isinstance(cur_raw, list) and cur_raw else ""
    lang_raw = raw.get("submission-language") or []
    languages = ", ".join(lang_raw) if isinstance(lang_raw, list) else str(lang_raw)
    dur_raw  = raw.get("contract-duration-period-lot")
    duration = "—"
    if isinstance(dur_raw, list) and dur_raw:
        d = dur_raw[0]
        if isinstance(d, dict):
            duration = f"{d.get('value','?')} {d.get('unit','').lower()}"
    cty_raw  = raw.get("buyer-country") or []
    country  = cty_raw[0] if isinstance(cty_raw, list) and cty_raw else ""
    desc_raw = raw.get("description-lot") or {}
    if isinstance(desc_raw, dict):
        description = (desc_raw.get("eng") or desc_raw.get("ENG") or
                       next(iter(desc_raw.values()), None))
        if isinstance(description, list): description = " ".join(description)
    elif isinstance(desc_raw, list):
        description = " ".join(str(x) for x in desc_raw)
    else:
        description = str(desc_raw) if desc_raw else ""
    description = (description or "")[:3000]
    return {
        "pub_num":     pub,
        "title":       title,
        "buyer":       buyer,
        "notice_type": ntype,
        "cpv":         ", ".join(cpv_list[:4]),
        "deadline_dt": dl_dt,
        "deadline":    dl_dt.strftime("%Y-%m-%d") if dl_dt else "—",
        "link":        f"https://ted.europa.eu/en/notice/-/detail/{pub}" if pub != "—" else "",
        "value":       value,
        "currency":    currency,
        "languages":   languages,
        "duration":    duration,
        "country":     country,
        "description": description,
    }


# ═══════════════════════════════════════════════════════════════
# FETCH
# ═══════════════════════════════════════════════════════════════

def make_query(days_back=DAYS_BACK):
    since    = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    cpv_part = " OR ".join(f'classification-cpv = "{c}"' for c in CPV_CODES)
    kw_part  = " OR ".join(f'FT ~ "{k}"' for k in BROAD_SEARCH_TERMS)
    return f"(({cpv_part}) OR ({kw_part})) AND publication-date >= {since}"


def _fetch_page(payload):
    for attempt in range(3):
        try:
            r = requests.post(SEARCH_URL, json=payload, timeout=60)
        except requests.RequestException as e:
            return None, str(e), None, "?"
        if r.status_code == 200:
            d = r.json()
            return (d.get("notices", []), None,
                    d.get("iterationNextToken"), d.get("totalNoticeCount", "?"))
        elif r.status_code == 429:
            wait = 35 * (attempt + 1)
            print(f"Rate limited — waiting {wait}s...")
            time.sleep(wait)
        else:
            return None, f"{r.status_code}: {r.text[:100]}", None, "?"
    return None, "Max retries", None, "?"


def fetch(days_back=DAYS_BACK):
    print("=" * 64)
    print(f"  TED Intelligence AI — DevelopMinded")
    print(f"  {datetime.now():%Y-%m-%d %H:%M UTC}")
    print(f"  Window: last {days_back} day(s)")
    print("=" * 64)
    query = make_query(days_back)
    print(f"\nQuery:\n{query}\n")

    all_notices, token, page, t0 = [], None, 0, time.time()
    while page < MAX_PAGES:
        payload = {
            "query": query, "fields": RESPONSE_FIELDS,
            "limit": PAGE_SIZE, "scope": "ACTIVE",
            "checkQuerySyntax": False,
            "paginationMode": "ITERATION",
            "onlyLatestVersions": True,
        }
        if token: payload["iterationNextToken"] = token
        notices, err, token, total = _fetch_page(payload)
        if err: print(f"\nError: {err}"); break
        if not notices: break
        all_notices.extend(notices)
        page += 1
        print(f"  Page {page:3d} | +{len(notices):3d} | {len(all_notices):,} / {total:,}", end="\r")
        if not token: print(f"  Page {page:3d} | done ✓" + " " * 30); break
        if page % 10 == 0: time.sleep(0.5)

    print(f"\n\nFetched {len(all_notices):,} notices in {time.time()-t0:.0f}s\n")
    if not all_notices: return pd.DataFrame(), pd.DataFrame()

    live_rows, intel_rows = [], []
    n_expired = n_no_dl = n_future = n_neg = n_lang = 0
    english_countries = {"IRL", "GBR", "MLT", "CYP"}

    for raw in all_notices:
        e = extract(raw)

        # Language filter
        langs = e.get("languages", "").upper()
        if langs and "ENG" not in langs and "NLD" not in langs:
            if e.get("country", "") not in english_countries:
                n_lang += 1; continue

        # Deadline filter
        dt = e["deadline_dt"]
        if dt is None:             n_no_dl   += 1
        elif dt < DEADLINE_CUTOFF: n_expired += 1; continue
        else:                      n_future  += 1

        # Negative filter
        if is_negative(e["title"], e["buyer"]):
            n_neg += 1; continue

        bucket = get_bucket(e["notice_type"])
        row    = {k: v for k, v in e.items() if k != "deadline_dt"}
        row["bucket"] = bucket
        (live_rows if bucket != "Market intelligence" else intel_rows).append(row)

    def to_df(rows):
        if not rows: return pd.DataFrame()
        return pd.DataFrame(rows).reset_index(drop=True)

    live, intel = to_df(live_rows), to_df(intel_rows)

    print("=" * 64)
    print(f"Language : {n_lang:,} filtered (non-ENG/NLD)")
    print(f"Deadline : {n_future:,} future | {n_no_dl:,} none | {n_expired:,} expired")
    print(f"Negatives: {n_neg:,} dropped")
    print(f"Sending  : {len(live):,} to Claude | {len(intel):,} market intel (skipped)\n")
    return live, intel


# ═══════════════════════════════════════════════════════════════
# AI FILTER
# ═══════════════════════════════════════════════════════════════

def _ask_claude(title, buyer, notice_text):
    if not ANTHROPIC_API_KEY:
        return True, "No API key — kept"
    prompt = f"""You are evaluating whether a public procurement tender is relevant for DevelopMinded.

{DM_PROFILE}

TENDER TITLE: {title}
BUYER: {buyer}
NOTICE TEXT:
{notice_text or "(not available — judge on title and buyer only)"}

Is this tender genuinely relevant for DevelopMinded?
Answer in exactly this format:
RELEVANT: YES or NO
REASON: one sentence"""
    for attempt in range(4):
        try:
            r = requests.post(
                CLAUDE_URL,
                headers={"x-api-key":         ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type":      "application/json"},
                json={"model": CLAUDE_MODEL, "max_tokens": 150,
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
                wait = 30 * (attempt + 1)
                print(f"    Rate limited — waiting {wait}s (attempt {attempt+1}/4)...")
                time.sleep(wait)
            else:
                return True, f"API error {r.status_code} — kept"
        except Exception as e:
            return True, f"Error: {e} — kept"
    return True, "Max retries (429) — kept"


def _check_one(row):
    rel, why = _ask_claude(
        row.get("title", ""),
        row.get("buyer", ""),
        row.get("description", "") or ""
    )
    return {**row, "ai_relevant": rel, "ai_reason": why}


def ai_filter(live):
    if live.empty: print("Nothing to filter."); return live
    print(f"\n{'='*64}\nAI filter — checking {len(live)} notices\n{'='*64}\n")
    rows, results = live.to_dict("records"), []
    with ThreadPoolExecutor(max_workers=AI_WORKERS) as pool:
        futures = {pool.submit(_check_one, r): i for i, r in enumerate(rows)}
        done = 0
        for fut in as_completed(futures):
            res = fut.result(); done += 1
            icon = "✅" if res["ai_relevant"] else "❌"
            print(f"  [{done:2d}/{len(rows)}] {icon}  {str(res.get('title',''))[:65]}")
            results.append(res)
    df      = pd.DataFrame(results)
    kept    = df[df["ai_relevant"]].reset_index(drop=True)
    removed = df[~df["ai_relevant"]]
    print(f"\n✅ Kept {len(kept)}  |  ❌ Removed {len(removed)}")
    for _, r in removed.iterrows():
        print(f"  ❌ {str(r['title'])[:70]}\n     → {r['ai_reason']}")
    return kept


# ═══════════════════════════════════════════════════════════════
# SAVE & EXPORT
# ═══════════════════════════════════════════════════════════════

def save_to_csv(live, intel, csv_file="ted_results_ai.csv"):
    if live.empty and intel.empty: print("Nothing to save."); return
    today  = datetime.now().strftime("%Y-%m-%d")
    frames = []
    if not live.empty:
        o = live.copy(); o["fetched_date"] = today; frames.append(o)
    if not intel.empty:
        o = intel.copy(); o["fetched_date"] = today; frames.append(o)
    new_rows = pd.concat(frames, ignore_index=True)
    try:
        existing = pd.read_csv(csv_file)
        combined = pd.concat([existing, new_rows], ignore_index=True)
        combined = combined.drop_duplicates(subset=["pub_num"], keep="last")
    except FileNotFoundError:
        combined = new_rows
    combined = combined.sort_values("fetched_date", ascending=False).reset_index(drop=True)
    combined.to_csv(csv_file, index=False)
    print(f"Saved → {csv_file}  ({len(combined):,} total rows, {len(new_rows)} new today)")


def export(live, intel, filename="ted_tenders_ai.xlsx"):
    if live.empty and intel.empty: print("Nothing to export."); return
    live_cols  = ["deadline", "title", "buyer", "country", "value", "currency",
                  "duration", "cpv", "notice_type", "ai_reason", "description", "link"]
    intel_cols = ["deadline", "title", "buyer", "country", "value", "currency",
                  "notice_type", "link"]
    with pd.ExcelWriter(filename, engine="openpyxl") as w:
        for df, sheet, cols in [(live,  "AI Relevant",        live_cols),
                                 (intel, "Market Intelligence", intel_cols)]:
            if df.empty: continue
            out = df[[c for c in cols if c in df.columns]]
            out.to_excel(w, index=False, sheet_name=sheet)
            ws = w.sheets[sheet]
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    max(len(str(c.value or "")) for c in col) + 4, 60)
    print(f"Exported → {filename}  |  AI Relevant: {len(live)}  |  Intel: {len(intel)}")


# ═══════════════════════════════════════════════════════════════
# SLACK
# ═══════════════════════════════════════════════════════════════

def send_slack_digest(live, intel):
    if not SLACK_WEBHOOK_URL:
        print("No SLACK_WEBHOOK_URL — skipping Slack.")
        return
    today           = datetime.now().strftime("%Y-%m-%d")
    deadline_cutoff = (datetime.now() + timedelta(days=DEADLINE_WARN_DAYS)).strftime("%Y-%m-%d")
    blocks = [
        {"type": "header", "text": {"type": "plain_text",
            "text": f"TED AI Intelligence — {today}"}},
        {"type": "section", "text": {"type": "mrkdwn",
            "text": f"*{len(live)}* AI-relevant opportunities  |  *{len(intel)}* market intel"}},
        {"type": "divider"},
    ]
    urgent_pubs = set()
    if not live.empty and "deadline" in live.columns:
        urgent = live[
            (live["deadline"] != "—") &
            (live["deadline"] <= deadline_cutoff) &
            (live["deadline"] >= today)
        ].sort_values("deadline").head(5)
        if not urgent.empty:
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                "text": f":alarm_clock: *Deadlines within {DEADLINE_WARN_DAYS} days*"}})
            for _, r in urgent.iterrows():
                urgent_pubs.add(r.get("pub_num", ""))
                blocks.append({"type": "section", "text": {"type": "mrkdwn",
                    "text": (f"*<{r.get('link','')}|{str(r['title'])[:80]}>*\n"
                             f"Buyer: {r['buyer']}  |  Deadline: {r['deadline']}\n"
                             f"_{r.get('ai_reason', '')}_")}})
    if not live.empty:
        top = live[~live["pub_num"].isin(urgent_pubs)].head(5)
        if not top.empty:
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                "text": ":green_circle: *Top AI-Relevant Opportunities*"}})
            for _, r in top.iterrows():
                blocks.append({"type": "section", "text": {"type": "mrkdwn",
                    "text": (f"*<{r.get('link','')}|{str(r['title'])[:80]}>*\n"
                             f"Buyer: {r['buyer']}  |  Deadline: {r.get('deadline','—')}\n"
                             f"_{r.get('ai_reason', '')}_")}})
    blocks += [
        {"type": "divider"},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": "DevelopMinded TED AI Intelligence — automated daily fetch"}
        ]},
    ]
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks}, timeout=15)
        print("Slack digest sent ✓" if r.status_code == 200 else f"Slack error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"Slack send failed: {e}")


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    live, intel = fetch()
    live = ai_filter(live)
    save_to_csv(live, intel)
    export(live, intel)
    send_slack_digest(live, intel)
