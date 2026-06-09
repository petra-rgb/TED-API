"""Unit tests for the Claude-filter helpers moved into ted_core (network mocked)."""
import pandas as pd

import ted_core


def test_raw_score_intel_weights_tiers():
    # "eic accelerator" is TIER1 (7), "horizon europe" is TIER2 (3)
    row = {"title": "EIC Accelerator support", "buyer": "Horizon Europe agency", "description": ""}
    assert ted_core._raw_score_intel(row) == 7 + 3
    assert ted_core._raw_score_intel({"title": "road works", "buyer": "city"}) == 0


def test_parse_response_strips_fences():
    assert ted_core._parse_response('```json\n{"relevant": true}\n```') == {"relevant": True}
    assert ted_core._parse_response('{"relevant": false}') == {"relevant": False}


def test_ask_claude_no_key_keeps():
    rel, reason = ted_core._ask_claude("profile", "t", "b", "x", api_key="")
    assert rel is True and "No API key" in reason


def test_ask_claude_parses_yes(monkeypatch):
    class _R:
        status_code = 200
        def json(self):
            return {"content": [{"text": "RELEVANT: YES\nREASON: strong commercialisation fit"}]}

    monkeypatch.setattr(ted_core.requests, "post", lambda *a, **k: _R())
    rel, reason = ted_core._ask_claude("profile", "t", "b", "x", api_key="sk-test")
    assert rel is True
    assert reason == "strong commercialisation fit"


def test_ai_filter_keeps_only_relevant(monkeypatch):
    # Deterministic stub: relevant iff title contains "keep"
    monkeypatch.setattr(ted_core, "_ask_claude",
                        lambda profile, title, buyer, text, **kw: ("keep" in title, "why"))
    live = pd.DataFrame([
        {"title": "keep this", "buyer": "b", "description": "d"},
        {"title": "drop that", "buyer": "b", "description": "d"},
    ])
    kept = ted_core.ai_filter(live, profile="p", api_key="sk", log=lambda *_: None)
    assert list(kept["title"]) == ["keep this"]
    assert bool(kept["ai_relevant"].all())
