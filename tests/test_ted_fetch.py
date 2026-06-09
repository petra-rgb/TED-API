"""Golden test for the fetch() filter/split loop (language / deadline / negative / bucket).

Network is mocked at _fetch_page so the loop runs offline against the committed fixture.
The two modules deliberately diverge: ted_intelligence skips the deadline filter for
awarded (intel) notices, so a past-deadline 'can-*' notice survives there but is dropped
by ted_intelligence_ai. The goldens lock that exact divergence.
"""
from unittest import mock

import pytest

from _golden_util import df_records
from conftest import load_fixture, load_golden

MODULES = ["ted_intelligence_ai", "ted_intelligence"]


@pytest.mark.parametrize("mod_name", MODULES)
def test_fetch_filter_split_matches_golden(mod_name):
    mod = __import__(mod_name)
    notices = load_fixture("ted_notices.json")
    golden = load_golden(f"{mod_name}_fetch.json")

    with mock.patch.object(mod, "_fetch_page",
                           return_value=(notices, None, None, len(notices))):
        live, intel = mod.fetch(days_back=1)

    assert df_records(live) == golden["live"]
    assert df_records(intel) == golden["intel"]


def test_variants_diverge_on_intel_deadline():
    """Documents the one real behavioural difference between the two entry scripts."""
    ai = load_golden("ted_intelligence_ai_fetch.json")
    kw = load_golden("ted_intelligence_fetch.json")
    assert _ids(ai["live"]) == _ids(kw["live"])           # live identical
    ai_intel, kw_intel = _ids(ai["intel"]), _ids(kw["intel"])
    # the past-deadline awarded notice (0002) survives only in the non-AI variant
    assert "0002-2026" in kw_intel and "0002-2026" not in ai_intel


def _ids(records):
    return {r["pub_num"] for r in records}
