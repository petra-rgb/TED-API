"""Golden tests for the per-site EIT scrapers, driven by offline HTML fixtures.

These lock the extraction behaviour of the highest-complexity scrapers so the Phase 3
decomposition can be proven behaviour-preserving. Network (scraper.fetch / requests.get)
is stubbed to serve the synthetic pages in scraper_cases.py.
"""
import pytest

import scraper
import scraper_cases as sc
from conftest import load_golden

SCRAPER_KEYS = list(sc.SITES.keys())


@pytest.mark.parametrize("key", SCRAPER_KEYS)
def test_scraper_matches_golden(key):
    golden = load_golden("scrapers.json")[key]
    with sc.patched(scraper):
        tenders = scraper.SCRAPERS[key](sc.SITES[key])
    assert sc.normalize(tenders) == golden


def test_ids_are_stable_md5_of_source_title_url():
    """make_tender id is a deterministic hash, so goldens stay valid across runs."""
    import hashlib
    t = scraper.make_tender(source="S", title="T", url="U")
    assert t["id"] == hashlib.md5(b"S|T|U").hexdigest()[:12]
