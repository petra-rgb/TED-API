
import requests, re, time, os
import pandas as pd
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# How far back to look. Default = 1 day for the daily runner.
# Set to 90 for a full backfill when running manually.
DAYS_BACK        = int(os.environ.get("DAYS_BACK", "1"))

PAGE_SIZE        = 250
MAX_PAGES        = 999
MIN_SCORE        = 3
AI_MAX_NOTICES   = 50
AI_WORKERS       = 4

TODAY            = datetime.now(timezone.utc)
DEADLINE_CUTOFF  = TODAY - timedelta(hours=24)

SEARCH_URL   = "https://api.ted.europa.eu/v3/notices/search"
CLAUDE_URL   = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Anthropic API key — set as env var in GitHub Actions / Streamlit secrets
# Or paste directly here for local use
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

RESPONSE_FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "notice-type",
    "BT-13(t)-Part",
]

# ── Broad search terms (cast wide net, score locally) ────────────
BROAD_SEARCH_TERMS = [
    "innovation", "commercialisation", "valorisation",
    "technology transfer", "advisory", "market study",
    "consultancy", "knowledge transfer", "exploitation",
    "research", "startup", "deep tech",
    "horizon europe", "dissemination",
]

# ── Tier 1: DM core language — +7 per hit ────────────────────────
TIER1 = [
    "technology valorisation", "tech valorisation",
    "technology commercialisation", "tech commercialisation",
    "exploitation of results", "exploitation and dissemination",
    "dissemination and exploitation",
    "commercialisation of research", "commercialisation of innovation",
    "technology transfer office", "research commercialisation",
    "ip commercialisation", "ip to market",
    "market uptake", "market adoption",
    "eic accelerator", "eic business acceleration",
    "eic bas", "business acceleration service",
    "eurostars", "eureka cluster",
    "eit digital", "eit manufacturing", "eit health",
    "eit urban mobility", "eit food", "eit rawmaterials",
    "diana programme", "diana accelerator",
    "nato innovation fund", "defence innovation accelerator",
    "venture building", "venture creation", "venture support",
    "startup support services", "startup acceleration",
    "deeptech", "deep tech",
    "spinout support", "spin-out support",
    "investor readiness", "investment readiness",
    "innovation ecosystem", "ecosystem orchestration",
    "consortium commercialisation", "project commercialisation",
    "innovation management support", "innovation support services",
    "scale-up support", "scaleup support",
    "product-market fit", "market validation",
]

# ── Tier 2: Contextual terms — +3 per hit ────────────────────────
TIER2 = [
    "horizon europe", "knowledge transfer", "technology transfer",
    "pre-commercial procurement", "innovation partnership",
    "spin-off", "spinout", "spin-out",
    "dual-use technology", "dual use technology",
    "commercialisation", "valorisation", "go-to-market",
    "market intelligence", "market study", "market analysis",
    "competitive analysis", "landscape analysis",
    "technology assessment", "feasibility study",
    "business model", "value proposition",
    "stakeholder mapping", "ecosystem mapping",
    "advisory services", "strategic advisory",
    "fundraising support", "funding strategy",
    "regulatory strategy", "regulatory navigation",
    "market entry", "market access",
    "technology roadmap", "innovation strategy",
    "dual use", "dual-use",
    "artificial intelligence", "machine learning",
    "cybersecurity", "digital twin",
    "quantum", "photonics", "semiconductor",
    "advanced materials", "energy storage",
    "autonomous systems", "robotics",
    "smart grid", "critical infrastructure",
    "space technology", "satellite",
]

BUYER_SIGNALS = [
    "innovation", "research", "universit", "institute",
    "agency", "accelerator", "incubator", "eit", "eic",
    "diana", "science", "nwo", "anr", "bpifrance",
    "vinnova", "enterprise ireland", "innovate uk",
    "rvo", "ffg", "ncbr", "enabel", "tekes",
    "business finland", "horizon", "eureka", "interreg",
]

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
    "locaux commerciaux", "habitations à loyer",
    "patrimoine résidentiel",
    "noise control", "baulärm", "car park", "parking lot",
    "building maintenance", "cleaning service", "catering service",
    "waste management", "refuse collection", "sludge",
    "urée", "déchets ménagers", "bacs roulants", "incineration",
    "fire alarm", "cctv installation", "security guard",
    "grounds maintenance", "road construction", "bridge construction",
    "electrical installation work", "plumbing",
    # Physical science equipment (Horizon funding ≠ advisory work)
    "refrigerating and freezing", "cryogenic", "hardwarekomponenten",
    "satellite hardware", "bodenstationsnetzwerk", "ground station network",
    "suministro, instalación", "beschaffung von hardware",
    # Website / platform build (knowledge transfer hub ≠ advisory)
    "site design services", "web portal development", "e-learning platform",
    # Physical bridge / infrastructure (innovation partnership mechanism ≠ advisory)
    "bridge cover", "bridge deck", "procurement of a bridge",
]

LIVE_TYPES  = {"cn-standard","cn-social","cn-desg","cn-tran",
               "pin-cfc-standard","pin-cfc-social","pin-only"}
INTEL_TYPES = {"can-standard","can-social","can-desg",
               "can-tran","can-modif"}



def flat(v) -> str:
    if not v: return ""
    if isinstance(v, str): return v.strip()
    if isinstance(v, list):
        return " | ".join(p for p in [flat(i) for i in v] if p)
    if isinstance(v, dict):
        for k in ("eng","ENG","fra","FRA","nld","NLD","deu","DEU"):
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
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw[:25], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def score_notice(title: str, buyer: str, ntype: str):
    title_low = title.lower()
    text      = f"{title} {buyer}".lower()
    buyer_low = buyer.lower()
    if any(neg in title_low for neg in NEGATIVES):
        return -999, "skip", [], []
    t1 = [t for t in TIER1 if t in text]
    t2 = [t for t in TIER2 if t in text]
    buyer_boost = 2 if any(sig in buyer_low for sig in BUYER_SIGNALS) else 0
    sc = 7 * len(t1) + 3 * len(t2) + buyer_boost
    if ntype in INTEL_TYPES: sc -= 5
    if sc < MIN_SCORE: return sc, "skip", t1, t2
    if ntype in INTEL_TYPES:           bucket = "Market intelligence"
    elif t1:                           bucket = "Live opportunity"
    elif len(t2) >= 2 and buyer_boost: bucket = "Live opportunity"
    elif len(t2) >= 3:                 bucket = "Possible opportunity"
    else:                              bucket = "skip"
    return sc, bucket, t1, t2


def extract(raw: dict) -> dict:
    pub   = flat(raw.get("publication-number")) or "—"
    title = flat(raw.get("notice-title"))       or "—"
    buyer = flat(raw.get("buyer-name"))         or "—"
    ntype = flat(raw.get("notice-type"))        or "—"
    dl_dt = parse_deadline(raw.get("BT-13(t)-Part"))
    return {
        "pub_num":     pub,
        "title":       title,
        "buyer":       buyer,
        "notice_type": ntype,
        "deadline_dt": dl_dt,
        "deadline":    dl_dt.strftime("%Y-%m-%d") if dl_dt else "—",
        "link":        f"https://ted.europa.eu/en/notice/-/detail/{pub}" if pub != "—" else "",
    }

# ═══════════════════════════════════════════════════════════════
# STEP 1 — FETCH
# ═══════════════════════════════════════════════════════════════

def make_query():
    parts = " OR ".join(f'FT ~ "{k}"' for k in BROAD_SEARCH_TERMS[:14])
    since = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%Y%m%d")
    return f"({parts}) AND publication-date >= {since}"


def _fetch_page(payload) -> tuple:
    for attempt in range(3):
        try:
            r = requests.post(SEARCH_URL, json=payload, timeout=60)
        except requests.RequestException as e:
            return None, str(e), None, "?"
        if r.status_code == 200:
            d = r.json()
            return (d.get("notices", []), None,
                    d.get("iterationNextToken"),
                    d.get("totalNoticeCount", "?"))
        elif r.status_code == 429:
            wait = 35 * (attempt + 1)
            print(f"\n  Rate limited — waiting {wait}s...")
            time.sleep(wait)
        else:
            return None, f"{r.status_code}: {r.text[:100]}", None, "?"
    return None, "Max retries", None, "?"


def fetch(days_back: int = DAYS_BACK) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("=" * 64)
    print(f"  TED Intelligence — DevelopMinded")
    print(f"  {datetime.now():%Y-%m-%d %H:%M UTC}")
    print(f"  Window: last {days_back} day(s)")
    print("=" * 64)

    # Override DAYS_BACK if passed explicitly
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    parts = " OR ".join(f'FT ~ "{k}"' for k in BROAD_SEARCH_TERMS[:14])
    query = f"({parts}) AND publication-date >= {since}"
    print(f"\nQuery:\n{query}\n")
    print("Fetching all pages...\n")

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
        if err: print(f"\n  Error: {err}"); break
        if not notices: break
        all_notices.extend(notices)
        page += 1
        print(f"  Page {page:3d} | +{len(notices):3d} | {len(all_notices):,} / {total:,}", end="\r")
        if not token: print(f"  Page {page:3d} | done ✓" + " " * 30); break
        if page % 10 == 0: time.sleep(0.5)

    print(f"\n\nFetched {len(all_notices):,} notices in {time.time()-t0:.0f}s\n")
    if not all_notices: return pd.DataFrame(), pd.DataFrame()

    live_rows, intel_rows = [], []
    n_expired = n_no_dl = n_future = n_neg = n_low = 0

    for raw in all_notices:
        e  = extract(raw)
        dt = e["deadline_dt"]
        if dt is None:             n_no_dl  += 1
        elif dt < DEADLINE_CUTOFF: n_expired += 1; continue
        else:                      n_future += 1
        sc, bucket, t1, t2 = score_notice(e["title"], e["buyer"], e["notice_type"])
        if bucket == "skip":
            if sc == -999: n_neg += 1
            else:          n_low += 1
            continue
        row = {k: v for k, v in e.items() if k != "deadline_dt"}
        row.update(score=sc, bucket=bucket,
                   t1_hits=", ".join(t1), t2_hits=", ".join(t2[:4]))
        (live_rows if bucket != "Market intelligence" else intel_rows).append(row)

    def to_df(rows):
        if not rows: return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)

    live, intel = to_df(live_rows), to_df(intel_rows)

    print("=" * 64)
    print(f"Deadline : {n_future:,} future | {n_no_dl:,} none | {n_expired:,} expired (dropped)")
    print(f"Scoring  : {n_neg:,} negative | {n_low:,} below threshold")
    print(f"Results  : 🟢 {len(live):,} live | 📊 {len(intel):,} market intel\n")

    if not live.empty:
        print("── LIVE OPPORTUNITIES ──")
        print(live[["score","bucket","deadline","title","buyer","t1_hits"]].to_string(index=False))
    if not intel.empty:
        print("\n── MARKET INTELLIGENCE ──")
        print(intel[["score","deadline","title","buyer","t1_hits"]].to_string(index=False))

    return live, intel

# ═══════════════════════════════════════════════════════════════
# STEP 2 — AI FILTER (optional — needs ANTHROPIC_API_KEY)
# ═══════════════════════════════════════════════════════════════

def _fetch_notice_text(pub_num: str) -> str:
    try:
        r = requests.get(
            f"https://ted.europa.eu/en/notice/{pub_num}/html",
            timeout=20, headers={"Accept-Language": "en"})
        if r.status_code != 200: return ""
        text = re.sub(r'<[^>]+>', ' ', r.text)
        return re.sub(r'\s+', ' ', text).strip()[:3000]
    except Exception:
        return ""


def _ask_claude(title: str, buyer: str, notice_text: str) -> tuple[bool, str]:
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
    try:
        r = requests.post(
            CLAUDE_URL,
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={"model": CLAUDE_MODEL, "max_tokens": 150,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        if r.status_code != 200: return True, f"API error {r.status_code} — kept"
        text     = r.json()["content"][0]["text"].strip()
        relevant = "RELEVANT: YES" in text.upper()
        reason   = next((l[7:].strip() for l in text.split("\n")
                         if l.upper().startswith("REASON:")), "")
        return relevant, reason
    except Exception as e:
        return True, f"Error: {e} — kept"


def _check_one(row: dict) -> dict:
    text     = _fetch_notice_text(row.get("pub_num",""))
    rel, why = _ask_claude(row.get("title",""), row.get("buyer",""), text)
    return {**row, "ai_relevant": rel, "ai_reason": why}


def ai_filter(live: pd.DataFrame, max_notices: int = AI_MAX_NOTICES) -> pd.DataFrame:
    if live.empty: print("Nothing to filter."); return live
    to_check = live.head(max_notices)
    print(f"\n{'='*64}")
    print(f"AI filter — checking {len(to_check)} notices")
    print("=" * 64 + "\n")
    rows, results = to_check.to_dict("records"), []
    with ThreadPoolExecutor(max_workers=AI_WORKERS) as pool:
        futures = {pool.submit(_check_one, r): i for i, r in enumerate(rows)}
        done = 0
        for fut in as_completed(futures):
            res = fut.result(); done += 1
            icon = "✅" if res["ai_relevant"] else "❌"
            print(f"  [{done:2d}/{len(rows)}] {icon}  {str(res.get('title',''))[:65]}")
            results.append(res)
    df   = pd.DataFrame(results)
    kept = df[df["ai_relevant"]].sort_values("score", ascending=False).reset_index(drop=True)
    removed = df[~df["ai_relevant"]]
    print(f"\n✅ Kept {len(kept)}  |  ❌ Removed {len(removed)}")
    if not removed.empty:
        for _, r in removed.iterrows():
            print(f"  ❌ {str(r['title'])[:70]}\n     → {r['ai_reason']}")
    return kept

# ═══════════════════════════════════════════════════════════════
# STEP 3 — EXPORT
# ═══════════════════════════════════════════════════════════════

def export(live: pd.DataFrame, intel: pd.DataFrame,
           filename: str = "ted_tenders.xlsx"):
    if live.empty and intel.empty: print("Nothing to export."); return
    live_cols  = ["score","bucket","deadline","title","buyer",
                  "notice_type","t1_hits","ai_reason","link"]
    intel_cols = ["score","deadline","title","buyer",
                  "notice_type","t1_hits","link"]
    with pd.ExcelWriter(filename, engine="openpyxl") as w:
        for df, sheet, cols in [
            (live,  "Live Opportunities",  live_cols),
            (intel, "Market Intelligence", intel_cols),
        ]:
            if df.empty: continue
            out = df[[c for c in cols if c in df.columns]]
            out.to_excel(w, index=False, sheet_name=sheet)
            ws = w.sheets[sheet]
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    max(len(str(c.value or "")) for c in col)+4, 60)
    print(f"Exported → {filename}")
    print(f"  Live Opportunities  : {len(live)}")
    print(f"  Market Intelligence : {len(intel)}")
    return filename

# ═══════════════════════════════════════════════════════════════
# ENTRY POINT — called by GitHub Actions
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# APPEND TO CSV  (replaces export() for the daily GitHub run)
# ═══════════════════════════════════════════════════════════════

def save_to_csv(live: pd.DataFrame, intel: pd.DataFrame,
                csv_file: str = "ted_results.csv"):
    """
    Append today's results to the cumulative CSV.
    Deduplicates on pub_num so re-runs don't create duplicates.
    """
    if live.empty and intel.empty:
        print("Nothing to save.")
        return

    # Tag rows with today's date and bucket
    today = datetime.now().strftime("%Y-%m-%d")
    frames = []
    if not live.empty:
        live_out = live.copy()
        live_out["fetched_date"] = today
        frames.append(live_out)
    if not intel.empty:
        intel_out = intel.copy()
        intel_out["fetched_date"] = today
        frames.append(intel_out)

    new_rows = pd.concat(frames, ignore_index=True)

    # Load existing CSV and append, deduplicating on pub_num + fetched_date
    try:
        existing = pd.read_csv(csv_file)
        combined = pd.concat([existing, new_rows], ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["pub_num", "fetched_date"], keep="last")
    except FileNotFoundError:
        combined = new_rows

    combined = combined.sort_values(
        ["fetched_date", "score"], ascending=[False, False]
    ).reset_index(drop=True)

    combined.to_csv(csv_file, index=False)
    print(f"Saved → {csv_file}  ({len(combined):,} total rows, {len(new_rows)} new today)")

if __name__ == "__main__":
    live, intel = fetch()
    # Uncomment to enable AI filter (needs ANTHROPIC_API_KEY env var):
    # live = ai_filter(live)
    save_to_csv(live, intel)   # appends to ted_results.csv (committed to repo)
    export(live, intel)        # also writes ted_tenders.xlsx as backup artifact
