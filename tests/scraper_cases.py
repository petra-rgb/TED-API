"""Synthetic HTML fixtures + dispatch for the EIT scraper golden tests.

Each page mirrors the real DOM structure described in the scraper docstrings, but is
minimal and offline. Pages are keyed by the exact URL the scraper will request (listing
url, or abs_url(base_url, href) for detail pages), so a stubbed scraper.fetch can serve
them. innoenergy is special-cased because it uses requests.get + __NEXT_DATA__.
"""
import json
from contextlib import contextmanager
from unittest import mock

from bs4 import BeautifulSoup

# ── site dicts (only the keys the scrapers read) ────────────────────────────────
SITES = {
    "climate_kic": {"name": "EIT Climate-KIC", "url": "https://ck.example/proc",
                    "base_url": "https://ck.example"},
    "eit_food": {"name": "EIT Food", "url": "https://food.example/proc",
                 "base_url": "https://food.example"},
    "eit_urban_mobility": {"name": "EIT Urban Mobility", "url": "https://um.example/rfp",
                           "base_url": "https://um.example"},
    "eit_raw_materials": {"name": "EIT RawMaterials", "url": "https://rm.example/proc",
                          "base_url": "https://rm.example"},
    "eit_innoenergy": {"name": "EIT InnoEnergy", "url": "https://ie.example/rfp",
                       "base_url": "https://ie.example"},
    "eit_culture_creativity": {"name": "EIT Culture & Creativity", "url": "https://cc.example/rp",
                               "base_url": "https://cc.example"},
    "eit_water": {"name": "EIT Water", "url": "https://water.example/calls",
                  "base_url": "https://water.example"},
}

# ── HTML pages keyed by requested URL ───────────────────────────────────────────
PAGES = {
    "https://ck.example/proc": """
      <body>
        <div class="card"><h4>RFP: Climate adaptation study</h4>
          <p>The new deadline for submitting applications is 26 May 2026.</p>
          <a href="/docs/rfp1.pdf">Read more</a></div>
        <div class="card"><h4>RFP: Net zero advisory</h4>
          <p>Proposals welcome.</p>
          <a href="/docs/rfp2.pdf">Read more</a></div>
      </body>""",

    "https://food.example/proc": """
      <body>
        <article><h3>Open call: Food innovation specialist</h3>
          <a href="/calls/food1">Details</a><p>Deadline 2026-07-01</p></article>
        <article><h3>Subscribe</h3><a href="/sub">x</a><p>newsletter</p></article>
      </body>""",

    "https://um.example/rfp": """
      <body>
        <div class="card"><h3>RFP Mobility data platform</h3>
          <a href="/request-for-proposal/mobility-data/">Open request</a></div>
        <div class="card"><h3>RFP Old closed one</h3>
          <a href="/request-for-proposal/closed-one/">Closed request</a></div>
      </body>""",
    "https://um.example/request-for-proposal/mobility-data/":
        "<body><main><p>Deadline for submission: 20 May 2026 at 17:00 CET</p></main></body>",

    "https://rm.example/proc": """
      <body>
        <a href="/call-for-offers/raw-1">Call for offers: critical materials study</a>
      </body>""",
    "https://rm.example/call-for-offers/raw-1":
        "<body><main><p>Deadline for submitting proposals 30.04.2026</p></main></body>",

    "https://cc.example/rp": """
      <body>
        <div class="content">
          <div class="content-title"><h2><a href="/your-opportunities/request-proposals/culture-1">Culture grant</a></h2></div>
          <div class="date"><div>April 13, 2026 &#8250; May 13, 2026</div></div>
        </div>
      </body>""",

    "https://water.example/calls": """
      <body>
        <div><h3>Open call: water tech pilot</h3><a href="/opportunities/water-1">Apply</a>
          <p>Deadline 15 June 2026</p></div>
      </body>""",
}

# innoenergy: a page with __NEXT_DATA__ whose content holds accordion items
_INNO_CONTENT = """
  <div class="innoenergy-blocks__simple-accordion__item">
    <span class="innoenergy-blocks__simple-accordion__item-text">04.05.2026 | Catering services for TBB 2026</span>
    <div class="innoenergy-blocks__simple-accordion__item-desc">
      <p>Deadline for submission proposals: 04.05.2026</p></div>
    <p class="innoenergy-blocks__simple-accordion__item-link"><a href="/docs/inno1.pdf">download</a></p>
  </div>"""
_INNO_NEXT = {"props": {"pageProps": {"__TEMPLATE_QUERY_DATA__": {"page": {"content": _INNO_CONTENT}}}}}
INNO_HTML = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(_INNO_NEXT)}</script></body></html>'


def _fetch_stub(url):
    html = PAGES.get(url)
    return BeautifulSoup(html, "lxml") if html is not None else None


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


@contextmanager
def patched(scraper):
    """Patch scraper.fetch (and requests.get for innoenergy) to serve fixtures."""
    with mock.patch.object(scraper, "fetch", side_effect=_fetch_stub), \
         mock.patch.object(scraper.requests, "get",
                           side_effect=lambda url, **kw: _Resp(INNO_HTML)):
        yield


def normalize(tenders):
    """Drop the volatile scraped_at timestamp; keep deterministic fields, sorted."""
    out = [{k: v for k, v in t.items() if k != "scraped_at"} for t in tenders]
    return sorted(out, key=lambda t: (t.get("source", ""), t.get("title", "")))
