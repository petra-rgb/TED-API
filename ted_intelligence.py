
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
MIN_SCORE        = 4
AI_MAX_NOTICES   = 20   # at current signal quality we rarely exceed 5–10 results
AI_WORKERS       = 4

TODAY            = datetime.now(timezone.utc)
DEADLINE_CUTOFF  = TODAY - timedelta(hours=24)

SEARCH_URL   = "https://api.ted.europa.eu/v3/notices/search"
CLAUDE_URL   = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Anthropic API key — set as env var in GitHub Actions / Streamlit secrets
# Or paste directly here for local use
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

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
    "notice-type",
    "classification-cpv",
    "deadline-receipt-tender-date-lot",   # tender submission deadline (date)
    "BT-131(d)-Lot",                      # same field, BT designation
    "deadline-date-lot",                  # fallback
    "BT-13(t)-Part",                      # part-level fallback
]

# ── CPV codes — queried directly, guaranteed fetch regardless of keywords ──
CPV_CODES = {
    "73200000": "R&D consultancy services",
    "79410000": "Business & mgmt consultancy",
    "79411100": "Business development consultancy",
    "79419000": "Evaluation consultancy",
}

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
DEADLINE_WARN_DAYS = 7   # flag notices with deadline within this many days

# ── Broad search terms — determines what gets FETCHED from TED ───
# Keep tight: every term here pulls thousands of notices.
# "research" and "consultancy" alone = 80%+ of TED volume — excluded.
# CPV codes handle the R&D consultancy fetch; keywords handle the rest.
BROAD_SEARCH_TERMS = [
    "commercialisation",        # core DM term, specific enough
    "valorisation",             # EU R&I jargon for exploiting results
    "technology transfer",      # specific two-word phrase
    "market study",             # specific two-word phrase
    "knowledge transfer",       # specific two-word phrase
    "exploitation of results",  # Horizon Europe standard phrase
    "startup",                  # specific enough in EU procurement context
    "deep tech",                # specific two-word phrase
    "horizon europe",           # specific programme name
    "eic accelerator",          # specific programme name
    "investor readiness",       # specific phrase
    "investment readiness",     # specific phrase
    "go-to-market",             # specific phrase
    "spin-off",                 # specific phrase
]

# ── Tier 1: DM core language — +7 per hit ────────────────────────
# Rules: no redundant pairs where shorter subsumes longer.
# "deep tech" kept, "deeptech" removed (never used in formal EU procurement).
# "innovation support" kept, "innovation support services" removed (subsumed).
# Terms are ordered from most specific to most general within each group.
TIER1 = [
    # Technology commercialisation — DM's core offering
    "technology valorisation", "tech valorisation",
    "technology commercialisation", "tech commercialisation",
    "commercialisation of research", "commercialisation of innovation",
    "research commercialisation", "ip commercialisation",
    "commercialisation support", "commercialisation services",
    "commercialisation strategy", "commercialisation roadmap",
    "exploitation of results", "exploitation of project results",
    "exploitation and dissemination", "dissemination and exploitation",
    "exploitation support", "exploitation services",
    "technology transfer office", "ip to market",
    "market uptake", "market adoption",
    "technology-to-market", "tech-to-market",
    # EIC / EIT / EU innovation programmes — primary buyer universe
    "eic accelerator", "eic business acceleration", "eic bas",
    "eic transition", "eic pathfinder", "eic t2m",
    "business acceleration service",
    "eit digital", "eit manufacturing", "eit health",
    "eit urban mobility", "eit food", "eit rawmaterials",
    "eurostars", "eureka cluster",
    # Defence innovation (DIANA, NATO) — growing adjacent market
    "diana programme", "diana accelerator",
    "nato innovation fund", "defence innovation accelerator",
    # Venture & startup support
    "venture building", "venture creation", "venture support",
    "startup support services", "startup acceleration",
    "deep tech",
    "spinout support", "spin-out support",
    # Investment & scale-up
    "investor readiness", "investment readiness",
    "scale-up support", "scaleup support",
    "go-to-market strategy", "go-to-market support",
    # Market intelligence & validation
    "product-market fit", "market validation",
    # Innovation support (broad but still TIER1-worthy in procurement context)
    "innovation ecosystem", "ecosystem orchestration",
    "consortium commercialisation", "project commercialisation",
    "innovation management support",
    "innovation support", "innovation advisory",
]

# ── Tier 2: Contextual service terms — +3 per hit ────────────────
# Rule: ONLY service-context terms here — not technology-domain terms.
# "artificial intelligence", "quantum", "cybersecurity" etc. removed:
# they boost scores for actual R&D execution contracts (building AI systems,
# quantum hardware) which are not DM's market. The signal must be the
# *type of service*, not the subject matter of the research.
TIER2 = [
    # EU programme context
    "horizon europe", "knowledge transfer", "technology transfer",
    "pre-commercial procurement", "innovation partnership",
    "spin-off", "spinout", "spin-out",
    "dual-use technology", "dual use technology", "dual use", "dual-use",
    # Core service terms — what DM actually does
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
    "pitch deck", "financial modelling", "investor outreach",
    "partnership strategy", "commercial strategy",
    "due diligence", "scale-up",
]

# ── Buyer signals — +2 if buyer name contains any of these ───────
# Removed: "innovation", "research", "agency" — far too generic.
# "innovation" matches investment banks; "research" matches lab equipment
# buyers; "agency" matches road agencies, tax agencies, border agencies.
# Kept: specific programme names, known innovation funders, known bodies.
BUYER_SIGNALS = [
    "universit", "institute",           # universities and research institutes
    "accelerator", "incubator",         # startup ecosystem orgs
    "eit", "eic", "diana",              # EU/NATO innovation bodies
    "nwo", "anr", "bpifrance",          # national R&I funders
    "vinnova", "innovate uk",           # national innovation agencies
    "enterprise ireland",               # Irish startup/innovation funder
    "rvo",                              # Dutch innovation & enterprise agency
    "ffg",                              # Austrian R&I funding agency
    "ncbr",                             # Polish R&I centre
    "tekes", "business finland",        # Finnish innovation agencies
    "eureka", "eurostars",              # pan-European innovation programmes
    "interreg",                         # EU cross-border cooperation
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
    # Actual R&D execution (not consultancy)
    "design and execution of research", "implementation of research",
    "development of software", "software development services",
    "hardware development", "system integration",
    "maritime network", "link integration network",
    "cybersecurity research", "security score",
    "protected area management", "marine observation",
    # Open source software maintenance (Sovereign Tech Agency type)
    "open source maintenance", "linux kernel", "open digital infrastructure",
    "sovereign tech",
    # Lab / life science execution (not commercialisation support)
    "dna extraction", "sequencing", "genomics", "microbial", "cell culture",
    "chromatography", "mass spectrometry", "laboratory equipment",
    # Postal / logistics
    "postal service", "postal services", "purchase of postal",
    # Noise / environmental monitoring
    "noise pollution", "noise software", "noise measurement",
    # Apartment / housing defects
    "apartment defect", "defects remediation", "building defect",
    # Energy infrastructure (not cleantech commercialisation)
    "energy lift", "grid connection works", "district heating",
    # Ecological / environmental surveys (not innovation advisory)
    "ecological survey", "habitat survey", "biodiversity survey",
    "carbon certification", "blue carbon",
    # Academic data collection / surveys
    "web interviewing", "survey of elderly", "social mapping",
    "questionnaire", "data collection survey",
    # Clinical / pharmaceutical execution (not commercialisation advisory)
    "clinical trial", "randomised controlled", "pharmaceutical supply",
    # IT / software execution (not advisory)
    "it infrastructure", "network installation", "server procurement",
    # Staffing / recruitment (not DM's market)
    "temporary staffing", "interim staff", "recruitment services",
    # Communications / translation (dissemination ≠ EU R&I dissemination)
    "translation services", "interpretation services",
    "communication campaign", "press office",
    # Construction / civil works catching TIER2 terms
    "construction works", "civil engineering", "road works",
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
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d%z", "%Y-%m-%d"):
        try:
            # TED returns dates like "2026-06-05+02:00" — strip tz for date-only formats
            s = raw[:25]
            if fmt == "%Y-%m-%d%z" and len(raw) > 10:
                s = raw  # keep full string for tz-aware date parse
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


# CPV prefix map: notices use specific sub-codes (e.g. 73210000) not just
# the parent (73200000). Prefix matching catches the full sub-tree.
CPV_PREFIXES = {
    "7320": "R&D consultancy",           # 73200000–73299999
    "79410": "Business & mgmt consultancy", # 79410000–79419999
}

def score_notice(title: str, buyer: str, ntype: str, cpv_list: list = None):
    title_low = title.lower()
    text      = f"{title} {buyer}".lower()
    buyer_low = buyer.lower()
    # Negatives checked against title AND buyer (not just title)
    full_text_low = f"{title} {buyer}".lower()
    if any(neg in full_text_low for neg in NEGATIVES):
        return -999, "skip", [], []
    t1 = [t for t in TIER1 if t in text]
    t2 = [t for t in TIER2 if t in text]
    buyer_boost = 2 if any(sig in buyer_low for sig in BUYER_SIGNALS) else 0
    # CPV: exact match on known codes + prefix match for sub-codes
    cpv_hits = [
        c for c in (cpv_list or [])
        if c in CPV_CODES or any(c.startswith(p) for p in CPV_PREFIXES)
    ]
    cpv_boost = 3 * len(cpv_hits)
    sc = 7 * len(t1) + 3 * len(t2) + buyer_boost + cpv_boost
    if ntype in INTEL_TYPES: sc -= 5
    if sc < MIN_SCORE: return sc, "skip", t1, t2
    # Bucket logic: CPV-only hit → "Possible opportunity", not "Live"
    # "Live opportunity" requires at least one TIER1 keyword hit
    if ntype in INTEL_TYPES:           bucket = "Market intelligence"
    elif t1:                           bucket = "Live opportunity"
    elif len(t2) >= 2 and buyer_boost: bucket = "Live opportunity"
    elif len(t2) >= 3:                 bucket = "Possible opportunity"
    elif cpv_hits:                     bucket = "Possible opportunity"
    else:                              bucket = "skip"
    return sc, bucket, t1, t2


def extract(raw: dict) -> dict:
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
    return {
        "pub_num":     pub,
        "title":       title,
        "buyer":       buyer,
        "notice_type": ntype,
        "cpv":         ", ".join(cpv_list[:4]),
        "deadline_dt": dl_dt,
        "deadline":    dl_dt.strftime("%Y-%m-%d") if dl_dt else "—",
        "link":        f"https://ted.europa.eu/en/notice/-/detail/{pub}" if pub != "—" else "",
    }

# ═══════════════════════════════════════════════════════════════
# STEP 1 — FETCH
# ═══════════════════════════════════════════════════════════════

def make_query(days_back=DAYS_BACK):
    since    = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    # CPV prefix matching via OR on exact codes AND known sub-code prefixes
    cpv_codes  = list(CPV_CODES.keys())
    cpv_part   = " OR ".join(f'classification-cpv = "{c}"' for c in cpv_codes)
    # All BROAD_SEARCH_TERMS — no slice; add terms deliberately, not by index
    kw_part    = " OR ".join(f'FT ~ "{k}"' for k in BROAD_SEARCH_TERMS)
    return f"(({cpv_part}) OR ({kw_part})) AND publication-date >= {since}"


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

    query = make_query(days_back)
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
        cpv_list = [c.strip() for c in e.get("cpv", "").split(",") if c.strip()]
        sc, bucket, t1, t2 = score_notice(e["title"], e["buyer"], e["notice_type"], cpv_list)
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
# STEP 4 — SLACK DIGEST
# ═══════════════════════════════════════════════════════════════

def send_slack_digest(live: pd.DataFrame, intel: pd.DataFrame):
    if not SLACK_WEBHOOK_URL:
        print("No SLACK_WEBHOOK_URL set — skipping Slack digest.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    deadline_cutoff = (datetime.now() + timedelta(days=DEADLINE_WARN_DAYS)).strftime("%Y-%m-%d")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"TED Tender Intelligence — {today}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": (
            f"*{len(live)}* live opportunities  |  "
            f"*{len(intel)}* market intelligence entries"
        )}},
        {"type": "divider"},
    ]

    urgent_pub_nums = set()

    # Deadline-urgent notices first (cap at 5 to keep message readable)
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
                urgent_pub_nums.add(r.get("pub_num", ""))
                blocks.append({"type": "section", "text": {"type": "mrkdwn",
                    "text": (
                        f"*<{r.get('link','')}|{str(r['title'])[:80]}>*\n"
                        f"Buyer: {r['buyer']}  |  Score: {r['score']}  |  Deadline: {r['deadline']}"
                    )
                }})

    # Top live opportunities — exclude any already shown in urgent block
    if not live.empty:
        top = live[~live["pub_num"].isin(urgent_pub_nums)].head(5)
        if not top.empty:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": ":green_circle: *Top Live Opportunities*"}})
            for _, r in top.iterrows():
                dl = r.get("deadline", "—")
                blocks.append({"type": "section", "text": {"type": "mrkdwn",
                    "text": (
                        f"*<{r.get('link','')}|{str(r['title'])[:80]}>*\n"
                        f"Buyer: {r['buyer']}  |  Score: {r['score']}  |  Deadline: {dl}"
                    )
                }})

    blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": "DevelopMinded TED Intelligence — automated daily fetch"}
    ]})

    try:
        r = requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks}, timeout=15)
        if r.status_code == 200:
            print("Slack digest sent ✓")
        else:
            print(f"Slack error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"Slack send failed: {e}")


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
        # Dedup on pub_num alone — same notice on multiple days = keep latest score
        combined = combined.drop_duplicates(subset=["pub_num"], keep="last")
    except FileNotFoundError:
        combined = new_rows

    combined = combined.sort_values(
        ["fetched_date", "score"], ascending=[False, False]
    ).reset_index(drop=True)

    combined.to_csv(csv_file, index=False)
    print(f"Saved → {csv_file}  ({len(combined):,} total rows, {len(new_rows)} new today)")

if __name__ == "__main__":
    live, intel = fetch()
    if ANTHROPIC_API_KEY:
        live = ai_filter(live)   # runs when ANTHROPIC_API_KEY is set (GitHub Actions + local)
    save_to_csv(live, intel)     # appends to ted_results.csv (committed to repo)
    export(live, intel)          # also writes ted_tenders.xlsx as backup artifact
    send_slack_digest(live, intel)
