"""Golden + unit tests for the pure TED transformation helpers.

These import via the entry modules (ted_intelligence_ai / ted_intelligence) so they
keep passing after Phase 2 moves the shared logic into ted_core (the modules will
re-export the same names).
"""
import datetime as dt

import pytest
from _golden_util import norm_extract
from conftest import load_fixture, load_golden

MODULES = ["ted_intelligence_ai", "ted_intelligence"]


@pytest.mark.parametrize("mod_name", MODULES)
def test_extract_matches_golden(mod_name):
    mod = __import__(mod_name)
    notices = load_fixture("ted_notices.json")
    golden = load_golden(f"{mod_name}_extract.json")
    got = [norm_extract(mod.extract(n)) for n in notices]
    assert got == golden


@pytest.mark.parametrize("mod_name", MODULES)
def test_flat(mod_name):
    flat = __import__(mod_name).flat
    assert flat("  hi ") == "hi"
    assert flat(None) == ""
    assert flat([]) == ""
    assert flat(["a", "", "b"]) == "a | b"
    assert flat({"eng": "english", "fra": "french"}) == "english"
    assert flat({"fra": "french"}) == "french"
    assert flat({"zzz": "fallback"}) == "fallback"


@pytest.mark.parametrize("mod_name", MODULES)
def test_parse_deadline(mod_name):
    parse = __import__(mod_name).parse_deadline
    assert parse(None) is None
    assert parse("") is None
    assert parse("not a date") is None
    assert parse("2026-05-15") == dt.datetime(2026, 5, 15, tzinfo=dt.UTC)
    assert parse(["2026-05-15", "ignored"]).year == 2026
    iso = parse("2026-05-15T12:30:00+00:00")
    assert (iso.year, iso.month, iso.day, iso.hour) == (2026, 5, 15, 12)


@pytest.mark.parametrize("mod_name", MODULES)
def test_is_negative_and_bucket(mod_name):
    mod = __import__(mod_name)
    assert mod.is_negative("Waste management contract", "City") is True
    assert mod.is_negative("Market study", "EIC Agency") is False
    assert mod.get_bucket("can-standard") == "Market intelligence"
    assert mod.get_bucket("cn-standard") == "Live opportunity"


@pytest.mark.parametrize("mod_name", MODULES)
def test_make_query_shape(mod_name):
    q = __import__(mod_name).make_query(days_back=1)
    assert "classification-cpv" in q
    assert "publication-date >=" in q
    assert q.startswith("((")
