#!/usr/bin/env python3
"""
EIT KIC Tender Scraper
Automatically fetches procurement tenders from EIT Knowledge and Innovation Communities.

Usage:
    python scraper.py                         # Print all tenders found
    python scraper.py --output json           # Save to output/tenders_YYYY-MM-DD.json
    python scraper.py --output csv            # Save to output/tenders_YYYY-MM-DD.csv
    python scraper.py --new-only              # Only show tenders not seen before
    python scraper.py --site climate_kic      # Run only one site
    python scraper.py --new-only --mark-seen  # Show new ones and mark them as seen

Sites covered (8 active EIT KICs):
    28digital              EIT Digital (rebranded to 28DIGITAL)
    climate_kic            EIT Climate-KIC
    eit_food               EIT Food
    eit_urban_mobility     EIT Urban Mobility
    eit_raw_materials      EIT RawMaterials
    eit_innoenergy         EIT InnoEnergy
    eit_culture_creativity EIT Culture & Creativity
    eit_water              EIT Water

Notes:
    EIT Manufacturing ceased operations on 10 April 2026 — excluded.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 25
OUTPUT_DIR = Path("output")
STATE_FILE = OUTPUT_DIR / "seen_tenders.json"

SITES = [
    {
        "id": "28digital",
        "name": "EIT Digital (28DIGITAL)",
        "url": "https://28digital.eu/our-messages/calls-tenders/",
        "base_url": "https://28digital.eu",
    },
    {
        "id": "climate_kic",
        "name": "EIT Climate-KIC",
        "url": "https://www.climate-kic.org/get-involved/procurement/",
        "base_url": "https://www.climate-kic.org",
    },
    {
        "id": "eit_food",
        "name": "EIT Food",
        "url": "https://www.eitfood.eu/open-procurements-overview",
        "base_url": "https://www.eitfood.eu",
    },
    {
        "id": "eit_urban_mobility",
        "name": "EIT Urban Mobility",
        "url": "https://www.eiturbanmobility.eu/join-us/request-for-proposals/",
        "base_url": "https://www.eiturbanmobility.eu",
    },
    {
        "id": "eit_raw_materials",
        "name": "EIT RawMaterials",
        "url": "https://www.eitrawmaterials.eu/about-us/procurement",
        "base_url": "https://www.eitrawmaterials.eu",
    },
    {
        "id": "eit_innoenergy",
        "name": "EIT InnoEnergy",
        "url": "https://www.innoenergy.com/about-us/join-us/request-for-proposal/",
        "base_url": "https://www.innoenergy.com",
    },
    {
        "id": "eit_culture_creativity",
        "name": "EIT Culture & Creativity",
        "url": "https://eit-culture-creativity.eu/your-opportunities/request-proposals",
        "base_url": "https://eit-culture-creativity.eu",
    },
    {
        "id": "eit_water",
        "name": "EIT Water",
        "url": "https://eitwater.eu/opportunities/calls-funding",
        "base_url": "https://eitwater.eu",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def fetch(url: str) -> BeautifulSoup | None:
    """Fetch a URL and return a BeautifulSoup tree, or None on error."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as e:
        print(f"  [ERROR] Could not fetch {url}: {e}", file=sys.stderr)
        return None


def make_tender(
    source: str,
    title: str,
    url: str,
    deadline: str = "",
    description: str = "",
) -> dict:
    """Build a normalised tender dict with a stable ID."""
    return {
        "id": hashlib.md5(f"{source}|{title}|{url}".encode()).hexdigest()[:12],
        "source": source,
        "title": title.strip(),
        "url": url,
        "deadline": deadline.strip(),
        "description": description.strip(),
        "scraped_at": datetime.now(UTC).isoformat(),
    }


def abs_url(base: str, href: str) -> str:
    """Turn a relative href into an absolute URL."""
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return base.rstrip("/") + href
    return base.rstrip("/") + "/" + href


def find_deadline(container) -> str:
    """Try to find a deadline/date string inside a BeautifulSoup element."""
    _FILE_EXTS = (".pdf", ".docx", ".doc", ".xlsx", ".zip", "download", "download ")
    for el in container.find_all(["time", "span", "p", "div"]):
        t = el.get_text(" ", strip=True)
        # Skip filename-like text (e.g. "RfP_BlueBook 2026 v2.docx Download")
        tl = t.lower()
        if any(ext in tl for ext in _FILE_EXTS):
            continue
        if any(
            kw in tl
            for kw in ["deadline", "by ", "until", "closes", "2025", "2026", "2027"]
        ) and len(t) < 80:
            return t
    return ""


def _extract_submission_deadline(text: str) -> str:
    """
    Extract the submission deadline date from tender page plain text.

    Handles two common layouts:
      • Separator style  : "Deadline for submitting proposals - June 7th, 2026"
      • Table style      : "Deadline for submitting proposals  30.04.2026"
        (HTML <td> cells become whitespace-only when converted with get_text)

    Falls back to any "Deadline … - date" line if the specific phrase is absent.
    Returns an empty string when nothing is found.
    """
    # ── Pattern 1: separator style (dash / en-dash / colon) ──────────────────
    m = re.search(
        r"[Dd]eadline for submitting[^–\-\n]{0,50}[–\-:]\s*([A-Za-z0-9\s,\.\/]+\d{4})",
        text,
    )
    if m:
        return m.group(1).strip().rstrip(".,")

    # ── Pattern 2: table / whitespace style ──────────────────────────────────
    # "Deadline for submitting proposals  30.04.2026"
    _date_pat = (
        r"\d{1,2}[./]\d{1,2}[./]\d{4}"              # DD.MM.YYYY or DD/MM/YYYY
        r"|\d{4}-\d{2}-\d{2}"                        # YYYY-MM-DD
        rf"|(?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}}"  # Month DD, YYYY
        rf"|\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}}"    # DD Month YYYY
        rf"|\d{{1,2}}/(?:{_MONTHS})/\d{{4}}"         # DD/Month/YYYY
    )
    m = re.search(
        rf"[Dd]eadline for submitting proposals\s+({_date_pat})",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # ── Pattern 3: generic "Deadline … - date" fallback ──────────────────────
    m = re.search(
        r"[Dd]eadline[^–\-\n]{0,50}[–\-:]\s*([A-Za-z0-9\s,\.\/]+\d{4})",
        text,
    )
    if m:
        return m.group(1).strip().rstrip(".,")

    # ── Pattern 4: "deadline … is DD Month [YYYY?]" ──────────────────────────
    # Climate-KIC card descriptions: "The new deadline for submitting applications
    # is 26 May." — no separator, no year. Inject current year if year is absent.
    m = re.search(
        rf"[Dd]eadline[^.\n]{{0,80}}?\bis\s+(\d{{1,2}})\s+(?:of\s+)?({_MONTHS})(?:\s+(\d{{4}}))?",
        text, re.IGNORECASE,
    )
    if m:
        day, month = m.group(1), m.group(2)
        year = m.group(3) or str(datetime.now(UTC).year)
        return f"{day} {month} {year}"

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# SITE SCRAPERS
# ─────────────────────────────────────────────────────────────────────────────

def scrape_28digital(site: dict) -> list[dict]:
    """
    28DIGITAL (former EIT Digital) — /our-messages/calls-tenders/
    Page is a table: each <tr> has the tender title link in one cell and a
    <span> containing exactly "Open" or "Closed" in another cell.
    We only keep rows whose status span says "Open".
    """
    tenders = []
    soup = fetch(site["url"])
    if not soup:
        return tenders

    seen = set()
    for row in soup.find_all("tr"):
        # Read the explicit status badge
        status_span = row.find("span")
        if not status_span:
            continue
        status = status_span.get_text(strip=True).lower()
        if status != "open":
            continue  # skip Closed rows entirely

        # Find the tender link inside this row
        a = row.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if href in seen:
            continue

        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        seen.add(href)
        url = abs_url(site["base_url"], href)
        tenders.append(make_tender(source=site["name"], title=title, url=url))

    return tenders


def scrape_eit_health(site: dict) -> list[dict]:
    """
    EIT Health — eithealth.eu/call-for-tenders/
    Active tenders are on the external dtvp.de platform.
    We scrape any direct links on the page, plus always add a pointer to dtvp.de.
    """
    tenders = []
    soup = fetch(site["url"])
    if not soup:
        return tenders

    seen = set()
    # Collect any direct tender links on the page itself
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 10:
            continue
        if any(kw in title.lower() for kw in ["tender", "rfp", "call for", "procurement", "request for proposal"]):
            if href not in seen:
                seen.add(href)
                url = abs_url(site["base_url"], href)
                tenders.append(make_tender(source=site["name"], title=title, url=url))

    # Always include the external portal pointer
    tenders.append(make_tender(
        source=site["name"],
        title="Active EIT Health Tenders on dtvp.de (external portal)",
        url="https://www.dtvp.de/en",
        description=(
            "EIT Health publishes its active tenders on the dtvp.de procurement platform. "
            "Search for 'EIT Health' on that site to find all current open opportunities."
        ),
    ))
    return tenders


def scrape_climate_kic(site: dict) -> list[dict]:
    """
    EIT Climate-KIC — /get-involved/procurement/
    Page uses Tailwind card layout — each card is a <div> containing:
      <h4>  title
      <p>   description (often contains "deadline ... is DD Month [YYYY]")
      <a>   "Read more" → PDF RFP document

    Deadline is extracted from the <p> description text; no need to open the PDF.
    """
    tenders = []
    soup = fetch(site["url"])
    if not soup:
        return tenders

    seen: set[str] = set()

    # Primary: find cards via <h4> headings — each is a tender card
    for h4 in soup.find_all("h4"):
        title = h4.get_text(strip=True)
        if not title or len(title) < 8:
            continue

        card = h4.find_parent("div")
        if not card:
            continue

        a = card.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        url = abs_url(site["base_url"], href)
        if url in seen:
            continue

        # Deadline from description paragraph
        deadline = ""
        desc_el = card.find("p")
        if desc_el:
            desc_text = desc_el.get_text(" ", strip=True)
            deadline = _extract_submission_deadline(desc_text)
            if not deadline:
                deadline = find_deadline(card)
        else:
            deadline = find_deadline(card)

        seen.add(url)
        desc = desc_el.get_text(strip=True)[:200] if desc_el else ""
        tenders.append(make_tender(
            source=site["name"], title=title, url=url,
            deadline=deadline, description=desc,
        ))

    # Fallback A: headings followed by links (older page layouts)
    if not tenders:
        main = soup.find("main") or soup.find("div", id="content") or soup.find("body")
        if main:
            for heading in main.find_all(["h2", "h3", "h4"]):
                title = heading.get_text(strip=True)
                if len(title) < 10:
                    continue
                link = (heading.find("a")
                        or heading.find_next_sibling("a")
                        or heading.find_next("a"))
                if link and link.get("href"):
                    href = link["href"]
                    if href not in seen:
                        seen.add(href)
                        url = abs_url(site["base_url"], href)
                        tenders.append(make_tender(source=site["name"], title=title, url=url))

    # Fallback B: direct PDF / document links
    if not tenders:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            is_doc = any(href.lower().endswith(ext) for ext in [".pdf", ".docx", ".doc"])
            is_tender_kw = any(kw in title.lower() for kw in [
                "rfp", "tender", "procurement", "call for", "request for",
            ])
            if (is_doc or is_tender_kw) and href not in seen:
                seen.add(href)
                url = abs_url(site["base_url"], href)
                tenders.append(make_tender(source=site["name"], title=title, url=url))

    return tenders


def scrape_eit_food(site: dict) -> list[dict]:
    """
    EIT Food — /open-procurements-overview
    Card/article layout. Subscribe URL: /open-calls-subscribe
    """
    tenders = []
    soup = fetch(site["url"])
    if not soup:
        return tenders

    seen = set()

    # Card containers
    containers = soup.find_all("article")
    if not containers:
        containers = soup.find_all("div", class_=lambda c: c and any(
            kw in (c if isinstance(c, str) else " ".join(c))
            for kw in ["card", "post", "call", "procurement", "item", "tender", "entry"]
        ))

    for container in containers:
        heading = container.find(["h2", "h3", "h4"])
        link = container.find("a", href=True)
        if not heading or not link:
            continue

        title = heading.get_text(strip=True)
        href = link["href"]
        if not title or len(title) < 5 or href in seen:
            continue
        seen.add(href)

        url = abs_url(site["base_url"], href)
        deadline = find_deadline(container)
        desc_el = container.find("p")
        desc = desc_el.get_text(strip=True)[:200] if desc_el else ""
        tenders.append(make_tender(source=site["name"], title=title, url=url, deadline=deadline, description=desc))

    # Fallback: keyword links
    if not tenders:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            if any(kw in title.lower() for kw in [
                "rfp", "tender", "call", "procurement", "specialist", "partner", "services",
            ]) and href not in seen:
                seen.add(href)
                url = abs_url(site["base_url"], href)
                tenders.append(make_tender(source=site["name"], title=title, url=url))

    # Remove obvious navigation items and closed tenders
    NAV_TITLES = {"procurements archive", "open calls", "past calls", "subscribe", "newsletter"}
    tenders = [
        t for t in tenders
        if t["title"].lower() not in NAV_TITLES
        and "closed" not in t["deadline"].lower()
    ]

    return tenders


def scrape_eit_urban_mobility(site: dict) -> list[dict]:
    """
    EIT Urban Mobility — /join-us/request-for-proposals/
    Items have 'Open request' or 'Closed request' status; we keep only open ones.
    Each links to /request-for-proposal/<slug>/.

    Deadlines are NOT on the listing page — they live on each individual RFP page
    in a box: "Deadline for submission: 20 May 2026" (or "Deadline for submissions:
    DD Month YYYY at HH:MM CET"). We fetch each page and use _extract_submission_deadline.
    """
    tenders = []
    soup = fetch(site["url"])
    if not soup:
        return tenders

    seen: set[str] = set()
    links: list[tuple[str, str]] = []   # (title, url)
    SKIP_LABELS = {"view more", "read more", "learn more", "apply", "download", "click here", "open"}

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/request-for-proposal/" not in href:
            continue
        if href in seen:
            continue

        parent = a.find_parent(["article", "div", "li", "section"])
        if parent:
            parent_text = parent.get_text(" ", strip=True).lower()
            if "closed" in parent_text and "open request" not in parent_text:
                continue

        # Title from heading inside the card
        title = ""
        if parent:
            h = parent.find(["h2", "h3", "h4"])
            if h:
                title = h.get_text(strip=True)
        if not title or title.lower() in SKIP_LABELS:
            link_text = a.get_text(strip=True)
            if link_text and link_text.lower() not in SKIP_LABELS and len(link_text) > 5:
                title = link_text
        if not title or title.lower() in SKIP_LABELS:
            slug = href.rstrip("/").split("/")[-1]
            title = slug.replace("-", " ").title()
        if not title:
            continue

        seen.add(href)
        links.append((title, abs_url(site["base_url"], href)))

    for title, url in links:
        deadline = ""
        detail_soup = fetch(url)
        if detail_soup:
            main = (
                detail_soup.find("main")
                or detail_soup.find("article")
                or detail_soup.find("div", id="content")
                or detail_soup.find("body")
            )
            if main:
                text = main.get_text(" ", strip=True)
                deadline = _extract_submission_deadline(text)
                if not deadline:
                    deadline = find_deadline(main)
        tenders.append(make_tender(source=site["name"], title=title, url=url, deadline=deadline))

    return tenders


def scrape_eit_raw_materials(site: dict) -> list[dict]:
    """
    EIT RawMaterials — /about-us/procurement
    Article-style listing; tender links use /articles/ or /call-for-offers/ paths.

    The listing page only shows publication dates (not submission deadlines), so
    we follow each individual tender link and extract the true submission deadline
    from the page content — looking for "Deadline for submitting proposals" lines.
    """
    tenders = []
    soup = fetch(site["url"])
    if not soup:
        return tenders

    seen = set()
    links: list[tuple[str, str]] = []   # (title, url)

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not any(path in href for path in ["/articles/", "/call-for-offers/", "/tender", "/procurement/rfp"]):
            continue
        if href in seen:
            continue

        title = a.get_text(strip=True)
        if not title or len(title) < 8:
            parent = a.find_parent(["article", "div", "li"])
            if parent:
                h = parent.find(["h2", "h3", "h4"])
                if h:
                    title = h.get_text(strip=True)

        if not title or len(title) < 5:
            continue

        seen.add(href)
        links.append((title, abs_url(site["base_url"], href)))

    for title, url in links:
        deadline = ""
        detail_soup = fetch(url)
        if detail_soup:
            main = (
                detail_soup.find("main")
                or detail_soup.find("article")
                or detail_soup.find("div", id="content")
                or detail_soup.find("body")
            )
            if main:
                text = main.get_text(" ", strip=True)
                deadline = _extract_submission_deadline(text)
                if not deadline:
                    deadline = find_deadline(main)

        tenders.append(make_tender(source=site["name"], title=title, url=url, deadline=deadline))

    return tenders


def scrape_innoenergy(site: dict) -> list[dict]:
    """
    EIT InnoEnergy — /about-us/join-us/request-for-proposal/
    Next.js app: tender data is embedded in <script id="__NEXT_DATA__"> as HTML
    inside page.content. Each accordion item has class
    'innoenergy-blocks__simple-accordion__item' with:
      - span.innoenergy-blocks__simple-accordion__item-text  → "DD.MM.YYYY | Title"
      - strong "Deadline for submission proposals:" paragraph → deadline
      - p.innoenergy-blocks__simple-accordion__item-link a   → download URL
    """
    tenders = []
    try:
        resp = requests.get(site["url"], headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [ERROR] Could not fetch {site['url']}: {e}", file=sys.stderr)
        return tenders

    # Pull the embedded Next.js JSON
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if not m:
        print("  [ERROR] InnoEnergy: __NEXT_DATA__ not found", file=sys.stderr)
        return tenders

    try:
        data = json.loads(m.group(1))
        content_html = (
            data.get("props", {})
                .get("pageProps", {})
                .get("__TEMPLATE_QUERY_DATA__", {})
                .get("page", {})
                .get("content", "")
        )
    except (json.JSONDecodeError, AttributeError):
        print("  [ERROR] InnoEnergy: failed to parse __NEXT_DATA__", file=sys.stderr)
        return tenders

    if not content_html:
        return tenders

    soup = BeautifulSoup(content_html, "lxml")
    seen = set()

    for item in soup.find_all("div", class_="innoenergy-blocks__simple-accordion__item"):
        # Title span: "04.05.2026 | Catering services for The Business Booster 2026"
        span = item.find("span", class_="innoenergy-blocks__simple-accordion__item-text")
        if not span:
            continue
        raw_title = span.get_text(strip=True)
        parts = raw_title.split("|", 1)
        title = parts[1].strip() if len(parts) > 1 else raw_title
        if not title or len(title) < 5 or title in seen:
            continue
        seen.add(title)

        # Deadline: look for "Deadline for submission proposals:" in the desc block
        deadline = ""
        desc = item.find("div", class_="innoenergy-blocks__simple-accordion__item-desc")
        if desc:
            for p in desc.find_all("p"):
                text = p.get_text(" ", strip=True)
                if "deadline for submission" in text.lower():
                    deadline = text.split(":", 1)[-1].strip()
                    break

        # Download URL: last <a> in the item-link paragraph
        url = site["url"]
        link_p = item.find("p", class_="innoenergy-blocks__simple-accordion__item-link")
        if link_p:
            a = link_p.find("a", href=True)
            if a:
                url = abs_url(site["base_url"], a["href"])

        tenders.append(make_tender(
            source=site["name"], title=title, url=url, deadline=deadline,
        ))

    return tenders


def scrape_eit_culture_creativity(site: dict) -> list[dict]:
    """
    EIT Culture & Creativity — /your-opportunities/request-proposals

    Each tender card is a <div class="content"> containing:
      • <div class="content-title"><h2><a href="/your-opportunities/request-proposals/<slug>">
      • <div class="date"><div>April 13, 2026  ›  May 13, 2026</div></div>

    The date after ›  is the submission deadline. Both dates are on the listing
    page itself, so no individual-page fetches needed.
    """
    tenders = []
    soup = fetch(site["url"])
    if not soup:
        return tenders

    seen: set[str] = set()

    for card in soup.find_all("div", class_="content"):
        # ── Title + URL ──────────────────────────────────────────────────────
        title_div = card.find("div", class_="content-title")
        if not title_div:
            continue
        a = title_div.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if "/your-opportunities/request-proposals/" not in href:
            continue
        slug = href.rstrip("/").split("/")[-1]
        if slug in ("request-proposals", "archive") or not slug:
            continue

        url = abs_url(site["base_url"], href)
        if url in seen:
            continue
        seen.add(url)

        title = a.get_text(strip=True)
        if not title or len(title) < 8:
            h = title_div.find(["h2", "h3", "h4"])
            if h:
                title = h.get_text(strip=True)
        if not title or len(title) < 8:
            title = slug.replace("-", " ").title()

        # ── Deadline: extract end-date from "StartDate › EndDate" ────────────
        deadline = ""
        date_div = card.find("div", class_="date")
        if date_div:
            date_text = date_div.get_text(" ", strip=True)
            if "›" in date_text:
                # Take the part after the arrow — that is the closing date
                deadline = date_text.split("›", 1)[1].strip()
            else:
                deadline = date_text.strip()

        tenders.append(make_tender(
            source=site["name"], title=title, url=url, deadline=deadline,
        ))

    return tenders


def scrape_eit_water(site: dict) -> list[dict]:
    """
    EIT Water — /opportunities/calls-funding
    Newest KIC (launched 2024); page structure uses generic card/link layout.
    Falls back to scrape_generic with added keyword matching.
    """
    tenders = []
    soup = fetch(site["url"])
    if not soup:
        return tenders

    seen = set()
    KEYWORDS = [
        "rfp", "tender", "call", "procurement", "proposal", "grant",
        "pilot", "funding", "opportunity", "open call",
    ]

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Skip links that point back to the listing page itself
        if href.rstrip("/") in (
            site["url"].rstrip("/"),
            "/opportunities/calls-funding",
        ):
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 10:
            # Try parent heading
            parent = a.find_parent(["div", "li", "article", "section"])
            if parent:
                h = parent.find(["h2", "h3", "h4"])
                if h:
                    title = h.get_text(strip=True)
        if not title or len(title) < 10:
            continue
        if any(kw in title.lower() for kw in KEYWORDS) and href not in seen:
            seen.add(href)
            url = abs_url(site["base_url"], href)
            parent = a.find_parent(["div", "li", "article", "section"])
            deadline = find_deadline(parent) if parent else ""
            tenders.append(make_tender(
                source=site["name"], title=title, url=url, deadline=deadline,
            ))

    return tenders


def scrape_generic(site: dict) -> list[dict]:
    """Generic fallback: find links that look like procurement opportunities."""
    tenders = []
    soup = fetch(site["url"])
    if not soup:
        return tenders

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 10:
            continue
        if any(kw in title.lower() for kw in [
            "rfp", "tender", "procurement", "call for", "request for proposal",
            "invitation to tender", "bid", "supplier",
        ]) and href not in seen:
            seen.add(href)
            url = abs_url(site["base_url"], href)
            tenders.append(make_tender(source=site["name"], title=title, url=url))

    return tenders


# ─────────────────────────────────────────────────────────────────────────────
# DISPATCHER
# ─────────────────────────────────────────────────────────────────────────────

SCRAPERS: dict = {
    "28digital": scrape_28digital,
    "eit_health": scrape_eit_health,
    "climate_kic": scrape_climate_kic,
    "eit_food": scrape_eit_food,
    "eit_urban_mobility": scrape_eit_urban_mobility,
    "eit_raw_materials": scrape_eit_raw_materials,
    "eit_innoenergy": scrape_innoenergy,
    "eit_culture_creativity": scrape_eit_culture_creativity,
    "eit_water": scrape_eit_water,
}


def run_all(site_filter: str | None = None) -> list[dict]:
    all_tenders = []
    for site in SITES:
        if site_filter and site["id"] != site_filter:
            continue
        print(f"Scraping {site['name']} ...")
        scraper = SCRAPERS.get(site["id"], scrape_generic)
        tenders = scraper(site)
        print(f"  → {len(tenders)} tender(s) found")
        all_tenders.extend(tenders)
    return all_tenders


# ─────────────────────────────────────────────────────────────────────────────
# STATE  (new-only detection)
# ─────────────────────────────────────────────────────────────────────────────

def load_seen() -> set:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(tender_ids: list) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    updated = load_seen() | set(tender_ids)
    STATE_FILE.write_text(json.dumps(sorted(updated), indent=2))


def filter_new(tenders: list[dict]) -> list[dict]:
    seen = load_seen()
    return [t for t in tenders if t["id"] not in seen]


# ─────────────────────────────────────────────────────────────────────────────
# DEADLINE FILTERING
# ─────────────────────────────────────────────────────────────────────────────

_MONTHS = (
    "january|february|march|april|may|june|"
    "july|august|september|october|november|december"
)
_DATE_PATTERNS = [
    # DD.MM.YYYY  →  InnoEnergy, Climate-KIC
    (re.compile(r"\b(\d{1,2})\.(\d{2})\.(\d{4})\b"), "%d.%m.%Y"),
    # YYYY-MM-DD  →  ISO dates; trailing \b replaced with (?!\d) so "2026-02-09_foo" also matches
    (re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"), "%Y-%m-%d"),
    # Month D(D), YYYY  →  "June 7, 2026" / "June 7 2026"
    (re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.IGNORECASE), "%B %d %Y"),
    # D(D) Month YYYY  →  "7 June 2026"
    (re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})\b", re.IGNORECASE), "%d %B %Y"),
    # DD/Month/YYYY  →  "01/May/2026"  (EIT RawMaterials DiliCHANCE style)
    # Candidate is rebuilt as "01 May 2026" (space-separated), so format uses spaces too
    (re.compile(rf"\b(\d{{1,2}})/({_MONTHS})/(\d{{4}})\b", re.IGNORECASE), "%d %B %Y"),
    # DD.MM.YY  →  InnoEnergy 2-digit year (e.g. "25.09.25" = Sept 25 2025)
    # Must come AFTER DD.MM.YYYY so the 4-digit pattern is tried first
    (re.compile(r"\b(\d{1,2})\.(\d{2})\.(\d{2})\b"), "%d.%m.%y"),
]


def parse_deadline(text: str) -> date | None:
    """
    Extract and parse the first recognisable date from a deadline string.
    Returns a datetime.date, or None if no date can be parsed.
    Handles: DD.MM.YYYY, YYYY-MM-DD, "May 15, 2026", "15 May 2026",
             ordinals like "June 7th, 2026" or "22nd March 2026", etc.
    """
    if not text:
        return None
    # Strip ordinal suffixes so "7th" → "7", "1st" → "1", "22nd" → "22", etc.
    text = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    # Inject current year into year-less dates in deadline context:
    # "until 15 of March" / "by 20 May" / "is 26 May" → adds current year
    _cur_year = datetime.now(UTC).year
    def _inject_year(m: "re.Match") -> str:
        day, month, year = m.group(1), m.group(2), m.group(3)
        return f"{day} {month} {year if year else _cur_year}"
    text = re.sub(
        rf"(?:until|by|is)\s+(\d{{1,2}})\s+(?:of\s+)?({_MONTHS})(?:\s+(\d{{4}}))?",
        _inject_year,
        text, flags=re.IGNORECASE,
    )
    for pattern, fmt in _DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            # Reconstruct a normalised string for strptime
            if ("%B" in fmt and fmt.startswith("%B")) or "%B" in fmt:          # Month DD YYYY
                candidate = f"{m.group(1)} {m.group(2)} {m.group(3)}"
            else:
                candidate = m.group(0)
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


_CLOSED_KEYWORDS = {
    "closed", "expired", "deadline passed", "no longer accepting",
    "awarded", "cancelled", "canceled", "completed", "past deadline",
    "submission closed", "call closed", "tender closed",
}


def filter_expired(
    tenders: list[dict],
    today: date | None = None,
) -> list[dict]:
    """
    Remove tenders that are clearly closed or expired. Two checks:

    1. Date check — deadline is parseable AND already in the past.
    2. Keyword check — deadline or title text contains words like
       "closed", "expired", "awarded", "cancelled", etc.

    Tenders with no deadline and no closing keywords are kept
    (we can't prove they're closed).
    """
    if today is None:
        today = datetime.now(UTC).date()

    kept, dropped = [], 0
    for t in tenders:
        deadline_text = (t.get("deadline") or "").lower()
        title_text    = (t.get("title") or "").lower()

        # Check 1: parseable date in the past
        dl = parse_deadline(deadline_text)
        if dl is not None and dl < today:
            dropped += 1
            continue

        # Check 2: explicit closed/expired keyword in deadline or title
        combined = deadline_text + " " + title_text
        if any(kw in combined for kw in _CLOSED_KEYWORDS):
            dropped += 1
            continue

        kept.append(t)

    if dropped:
        print(f"  ✂  {dropped} expired/closed tender(s) removed")
    return kept


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

def save_json(tenders: list[dict], path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(tenders, indent=2, ensure_ascii=False))
    print(f"Saved {len(tenders)} tender(s) → {path}")


def save_csv(tenders: list[dict], path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    fields = ["id", "source", "title", "url", "deadline", "description", "scraped_at"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(tenders)
    print(f"Saved {len(tenders)} tender(s) → {path}")


def print_tenders(tenders: list[dict]) -> None:
    if not tenders:
        print("\nNo tenders found.")
        return
    print(f"\n{'=' * 70}")
    print(f"  {len(tenders)} TENDER(S) FOUND")
    print(f"{'=' * 70}")
    for t in tenders:
        print(f"\n  [{t['source']}]")
        print(f"  Title   : {t['title']}")
        print(f"  URL     : {t['url']}")
        if t["deadline"]:
            print(f"  Deadline: {t['deadline']}")
        if t["description"]:
            print(f"  Notes   : {t['description'][:120]}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape procurement tenders from EIT KIC websites.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output", choices=["print", "json", "csv"], default="print",
        help="Output format (default: print)",
    )
    parser.add_argument(
        "--active-only", action="store_true",
        help="Remove tenders whose deadline has already passed",
    )
    parser.add_argument(
        "--new-only", action="store_true",
        help="Only show tenders not seen in previous runs",
    )
    parser.add_argument(
        "--mark-seen", action="store_true",
        help="Mark all found tenders as seen (for future --new-only runs)",
    )
    parser.add_argument(
        "--site",
        choices=[s["id"] for s in SITES] + ["all"],
        default="all",
        help="Scrape only a specific site (default: all)",
    )
    args = parser.parse_args()

    site_filter = None if args.site == "all" else args.site
    tenders = run_all(site_filter)

    if args.active_only:
        tenders = filter_expired(tenders)

    if args.new_only:
        before = len(tenders)
        tenders = filter_new(tenders)
        print(f"\n{len(tenders)} new (out of {before} total) since last run.")

    if args.mark_seen or args.new_only:
        save_seen([t["id"] for t in tenders])

    today = datetime.now(UTC).strftime("%Y-%m-%d")

    if args.output == "json":
        save_json(tenders, OUTPUT_DIR / f"tenders_{today}.json")
    elif args.output == "csv":
        save_csv(tenders, OUTPUT_DIR / f"tenders_{today}.csv")
    else:
        print_tenders(tenders)


if __name__ == "__main__":
    main()
