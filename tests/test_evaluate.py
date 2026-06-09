"""Unit tests for evaluate.evaluate_tender JSON handling (Claude call mocked)."""
import evaluate


class _Block:
    def __init__(self, text):
        self.text = text


class _Msg:
    def __init__(self, text):
        self.content = [_Block(text)]


class _FakeClient:
    """Minimal stand-in for anthropic.Anthropic — returns a canned message."""
    def __init__(self, text):
        outer = self

        class _Messages:
            def create(self, **kw):
                return _Msg(outer._text)
        self._text = text
        self.messages = _Messages()


def _tender(**over):
    base = {"title": "Deep tech GTM", "source": "EIT Food", "url": "http://x",
            "deadline": "", "description": "desc"}
    base.update(over)
    return base


def test_strips_markdown_fence_and_uppercases_fit(monkeypatch):
    monkeypatch.setattr(evaluate, "fetch_page_text", lambda url: ("page text", ""))
    client = _FakeClient('```json\n{"fit":"yes","score":8,"reason":"good fit",'
                         '"match":"GTM","summary":"s","deadline":"2026-05-01"}\n```')
    out = evaluate.evaluate_tender(client, _tender())
    assert out["fit"] == "YES"
    assert out["score"] == 8
    assert out["fit_reason"] == "good fit"
    assert out["call_deadline"] == "2026-05-01"   # used because scraper found none


def test_keeps_scraper_deadline_over_claude(monkeypatch):
    monkeypatch.setattr(evaluate, "fetch_page_text", lambda url: ("page text", ""))
    client = _FakeClient('{"fit":"NO","score":2,"reason":"r","match":"none",'
                         '"summary":"s","deadline":"2099-01-01"}')
    out = evaluate.evaluate_tender(client, _tender(deadline="2026-03-03"))
    assert out["call_deadline"] == "2026-03-03"


def test_non_json_marks_error(monkeypatch):
    monkeypatch.setattr(evaluate, "fetch_page_text", lambda url: ("page text", ""))
    client = _FakeClient("sorry, I cannot produce JSON")
    out = evaluate.evaluate_tender(client, _tender())
    assert out["fit"] == "ERROR"
    assert out["fit_reason"].startswith("Claude returned non-JSON")
