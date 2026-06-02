
import requests, time, os
import pandas as pd
from datetime import datetime, timedelta, timezone


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

DAYS_BACK          = int(os.environ.get("DAYS_BACK", "1"))
PAGE_SIZE          = 250
MAX_PAGES          = 999
MIN_SCORE          = 3
DEADLINE_WARN_DAYS = 14

TODAY           = datetime.now(timezone.utc)
DEADLINE_CUTOFF = TODAY - timedelta(hours=24)

SEARCH_URL        = "https://api.ted.europa.eu/v3/notices/search"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")


RESPONSE_FIELDS = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "notice-type",
    "classification-cpv",
    "deadline-receipt-tender-date-lot",
    "BT-131(d)-Lot",
    "deadline-date-lot",
    "BT-13(t)-Part",
    "description-lot",               # full lot description — used by AI filter
    "estimated-value-lot",           # contract budget
    "estimated-value-cur-lot",       # currency (EUR, NOK etc)
    "submission-language",           # languages accepted
    "contract-duration-period-lot",  # contract length in months
    "buyer-country",                 # ISO country code of buyer
]

CPV_CODES = {
    "73200000": "R&D consultancy services",
    "79410000": "Business & mgmt consultancy",
    "79411100": "Business development consultancy",
    "79419000": "Evaluation consultancy",
    
}

CPV_PREFIXES = {
    "7320":  "R&D consultancy",
    "79410": "Business & mgmt consultancy",
    
}

BROAD_SEARCH_TERMS = [
    "commercialisation",
    "valorisation",
    "market study",
    "market research",
    "exploitation of results",
    "startup",
    "deep tech",
    "horizon europe",
    "eic accelerator",
    "investor readiness",
    "investment readiness",
    "go-to-market",
    "spin-off",
    "deeptech",
    "deep-tech",
    "knowledge valorisation",      # ← add
    "pre-commercial",              # ← add (catches PCP, pre-commercial procurement)
    "deep tech",  
]

TIER1 = [
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
    "eic accelerator", "eic business acceleration", "eic bas",
    "eic transition", "eic pathfinder", "eic t2m",
    "business acceleration service",
    "eit digital", "eit manufacturing", "eit health",
    "eit urban mobility", "eit food", "eit rawmaterials",
    "eurostars", "eureka cluster",
    "diana programme", "diana accelerator",
    "nato innovation fund", "defence innovation accelerator",
    "venture building", "venture creation", "venture support",
    "startup support services", "startup acceleration",
    "deep tech",
    "spinout support", "spin-out support",
    "investor readiness", "investment readiness",
    "scale-up support", "scaleup support",
    "go-to-market strategy", "go-to-market support",
    "product-market fit", "market validation",
    "innovation ecosystem", "ecosystem orchestration",
    "consortium commercialisation", "project commercialisation",
    "innovation management support",
    "innovation support", "innovation advisory",
]

TIER2 = [
    "horizon europe", "knowledge transfer", "technology transfer",
    "pre-commercial procurement", "innovation partnership",
    "spin-off", "spinout", "spin-out",
    "dual-use technology", "dual use technology", "dual use", "dual-use",
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

BUYER_SIGNALS = [
    "universit", "institute",
    "accelerator", "incubator",
    "eit", "eic", "diana",
    "nwo", "anr", "bpifrance",
    "vinnova", "innovate uk",
    "enterprise ireland",
    "rvo", "ffg", "ncbr",
    "tekes", "business finland",
    "eureka", "eurostars",
    "interreg",
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
    "refrigerating and freezing", "cryogenic", "hardwarekomponenten",
    "satellite hardware", "bodenstationsnetzwerk", "ground station network",
    "suministro, instalación", "beschaffung von hardware",
    "site design services", "web portal development", "e-learning platform",
    "bridge cover", "bridge deck", "procurement of a bridge",
    "design and execution of research", "implementation of research",
    "development of software", "software development services",
    "hardware development", "system integration",
    "maritime network", "link integration network",
    "cybersecurity research", "security score",
    "protected area management", "marine observation",
    "open source maintenance", "linux kernel", "open digital infrastructure",
    "sovereign tech",
    "dna extraction", "sequencing", "genomics", "microbial", "cell culture",
    "chromatography", "mass spectrometry", "laboratory equipment",
    "postal service", "postal services", "purchase of postal",
    "noise pollution", "noise software", "noise measurement",
    "apartment defect", "defects remediation", "building defect",
    "energy lift", "grid connection works", "district heating",
    "ecological survey", "habitat survey", "biodiversity survey",
    "carbon certification", "blue carbon",
    "web interviewing", "survey of elderly", "social mapping",
    "questionnaire", "data collection survey",
    "clinical trial", "randomised controlled", "pharmaceutical supply",
    "it infrastructure", "network installation", "server procurement",
    "temporary staffing", "interim staff", "recruitment services",
    "translation services", "interpretation services",
    "communication campaign", "press office",
    "construction works", "civil engineering", "road works",
    "evaluation of programme", "policy evaluation", "impact assessment",
    "audit", "legal services", "communication services",
    "event management", "training services",
]

INTEL_TYPES = {"can-standard", "can-social", "can-desg", "can-tran", "can-modif"}


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

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


def score_notice(title: str, buyer: str, ntype: str,
                 cpv_list: list = None, description: str = ""):
    text        = f"{title} {buyer} {description}".lower()
    buyer_low   = buyer.lower()
    title_buyer = f"{title} {buyer}".lower()

    if any(neg in title_buyer for neg in NEGATIVES):
        return -999, "skip", [], []

    t1 = [t for t in TIER1 if t in text]
    t2 = [t for t in TIER2 if t in text]
    buyer_boost = 2 if any(sig in buyer_low for sig in BUYER_SIGNALS) else 0
    cpv_hits = [
        c for c in (cpv_list or [])
        if c in CPV_CODES or any(c.startswith(p) for p in CPV_PREFIXES)
    ]
    cpv_boost = 3 * len(cpv_hits)
    sc = 7 * len(t1) + 3 * len(t2) + buyer_boost + cpv_boost
    intel = ntype in INTEL_TYPES
    if intel: sc -= 5
    threshold = 1 if intel else MIN_SCORE   # intel just needs any keyword hit
    if sc < threshold: return sc, "skip", t1, t2
    

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

    val_raw  = raw.get("estimated-value-lot")
    value    = float(val_raw[0]) if isinstance(val_raw, list) and val_raw else None
    cur_raw  = raw.get("estimated-value-cur-lot")
    currency = cur_raw[0] if isinstance(cur_raw, list) and cur_raw else ""

    lang_raw  = raw.get("submission-language") or []
    languages = ", ".join(lang_raw) if isinstance(lang_raw, list) else str(lang_raw)

    dur_raw  = raw.get("contract-duration-period-lot")
    duration = "—"
    if isinstance(dur_raw, list) and dur_raw:
        d = dur_raw[0]
        if isinstance(d, dict):
            duration = f"{d.get('value','?')} {d.get('unit','').lower()}"

    cty_raw = raw.get("buyer-country") or []
    country = cty_raw[0] if isinstance(cty_raw, list) and cty_raw else ""

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
# STEP 1 — FETCH
# ═══════════════════════════════════════════════════════════════

def make_query(days_back=DAYS_BACK):
    since     = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    cpv_codes = list(CPV_CODES.keys())
    cpv_part  = " OR ".join(f'classification-cpv = "{c}"' for c in cpv_codes)
    kw_part   = " OR ".join(f'FT ~ "{k}"' for k in BROAD_SEARCH_TERMS)
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
    n_expired = n_no_dl = n_future = n_neg = n_low = n_lang = 0

    for raw in all_notices:
        e     = extract(raw)
        langs = e.get("languages", "").upper()
        if langs and "ENG" not in langs and "NLD" not in langs:
            n_lang += 1
            continue

        dt = e["deadline_dt"]
        if dt is None:             n_no_dl   += 1
        elif dt < DEADLINE_CUTOFF: n_expired += 1; continue
        else:                      n_future  += 1

        cpv_list = [c.strip() for c in e.get("cpv", "").split(",") if c.strip()]
        sc, bucket, t1, t2 = score_notice(
            e["title"], e["buyer"], e["notice_type"],
            cpv_list, e.get("description", "")
        )
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
    print(f"Filtered : {n_lang:,} non-English/Dutch language")
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
# STEP 2 — EXPORT
# ═══════════════════════════════════════════════════════════════

def export(live: pd.DataFrame, intel: pd.DataFrame,
           filename: str = "ted_tenders.xlsx"):
    if live.empty and intel.empty: print("Nothing to export."); return
    live_cols  = ["score", "bucket", "deadline", "title", "buyer", "country",
                  "value", "currency", "duration", "languages",
                  "notice_type", "t1_hits", "t2_hits", "description", "link"]
    intel_cols = ["score", "deadline", "title", "buyer", "country",
                  "value", "currency", "notice_type", "t1_hits", "link"]
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
                    max(len(str(c.value or "")) for c in col) + 4, 60)
    print(f"Exported → {filename}")
    print(f"  Live Opportunities  : {len(live)}")
    print(f"  Market Intelligence : {len(intel)}")
    return filename


# ═══════════════════════════════════════════════════════════════
# STEP 3 — SAVE TO CSV
# ═══════════════════════════════════════════════════════════════

def save_to_csv(live: pd.DataFrame, intel: pd.DataFrame,
                csv_file: str = "ted_results.csv"):
    if live.empty and intel.empty:
        print("Nothing to save.")
        return
    today  = datetime.now().strftime("%Y-%m-%d")
    frames = []
    if not live.empty:
        live_out = live.copy(); live_out["fetched_date"] = today
        frames.append(live_out)
    if not intel.empty:
        intel_out = intel.copy(); intel_out["fetched_date"] = today
        frames.append(intel_out)

    new_rows = pd.concat(frames, ignore_index=True)
    try:
        existing = pd.read_csv(csv_file)
        combined = pd.concat([existing, new_rows], ignore_index=True)
        combined = combined.drop_duplicates(subset=["pub_num"], keep="last")
    except FileNotFoundError:
        combined = new_rows

    combined = combined.sort_values(
        ["fetched_date", "score"], ascending=[False, False]
    ).reset_index(drop=True)
    combined.to_csv(csv_file, index=False)
    print(f"Saved → {csv_file}  ({len(combined):,} total rows, {len(new_rows)} new today)")


# ═══════════════════════════════════════════════════════════════
# STEP 4 — SLACK DIGEST
# ═══════════════════════════════════════════════════════════════

def send_slack_digest(live: pd.DataFrame, intel: pd.DataFrame):
    if not SLACK_WEBHOOK_URL:
        print("No SLACK_WEBHOOK_URL set — skipping Slack digest.")
        return

    today           = datetime.now().strftime("%Y-%m-%d")
    deadline_cutoff = (datetime.now() + timedelta(days=DEADLINE_WARN_DAYS)).strftime("%Y-%m-%d")

    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"🔍 TED Tender Intelligence — {today}"}},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": (
             f"*{len(live)}* live/possible opportunities  |  "
             f"*{len(intel)}* awarded contracts"
         )}},
        {"type": "divider"},
    ]

    urgent_pub_nums = set()

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
                        f"Buyer: {r['buyer']}  |  Score: {r['score']}  |  "
                        f"Deadline: *{r['deadline']}*"
                    )}})
            blocks.append({"type": "divider"})

    if not live.empty:
        top = live[~live["pub_num"].isin(urgent_pub_nums)].head(5)
        if not top.empty:
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                "text": ":green_circle: *Top Opportunities*"}})
            for _, r in top.iterrows():
                dl  = r.get("deadline", "—")
                val = f"  |  €{r['value']:,.0f}" if pd.notna(r.get("value")) else ""
                blocks.append({"type": "section", "text": {"type": "mrkdwn",
                    "text": (
                        f"*<{r.get('link','')}|{str(r['title'])[:80]}>*\n"
                        f"Buyer: {r['buyer']}  |  Score: {r['score']}  |  "
                        f"Deadline: {dl}{val}"
                    )}})

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
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    live, intel = fetch()
    save_to_csv(live, intel)
    export(live, intel)
    send_slack_digest(live, intel)
