"""Unit tests for the pure helpers in scraper.py (no network)."""
import datetime as dt

import scraper


def test_abs_url():
    assert scraper.abs_url("https://x.com", "https://y.com/a") == "https://y.com/a"
    assert scraper.abs_url("https://x.com", "//cdn/a") == "https://cdn/a"
    assert scraper.abs_url("https://x.com/", "/a") == "https://x.com/a"
    assert scraper.abs_url("https://x.com", "a") == "https://x.com/a"


def test_make_tender_strips_and_hashes():
    t = scraper.make_tender(source="S", title="  Title ", url="U", deadline=" 1 May ")
    assert t["title"] == "Title"
    assert t["deadline"] == "1 May"
    assert len(t["id"]) == 12


def test_parse_deadline_variants():
    p = scraper.parse_deadline
    assert p("30.04.2026") == dt.date(2026, 4, 30)
    assert p("2026-04-30") == dt.date(2026, 4, 30)
    assert p("May 15, 2026") == dt.date(2026, 5, 15)
    assert p("15 May 2026") == dt.date(2026, 5, 15)
    assert p("June 7th, 2026") == dt.date(2026, 6, 7)        # ordinal stripped
    assert p("01/May/2026") == dt.date(2026, 5, 1)
    assert p("") is None
    assert p("no date here") is None


def test_extract_submission_deadline():
    f = scraper._extract_submission_deadline
    assert f("Deadline for submitting proposals - June 7, 2026") == "June 7, 2026"
    assert f("Deadline for submitting proposals  30.04.2026") == "30.04.2026"
    assert f("the deadline for submitting applications is 26 May 2026") == "26 May 2026"
    assert f("nothing relevant") == ""


def test_filter_expired_keeps_future_and_unknown_drops_past_and_closed():
    today = dt.date(2026, 1, 1)
    tenders = [
        {"title": "Future", "deadline": "30.04.2026"},
        {"title": "Past", "deadline": "01.01.2020"},
        {"title": "Awarded already", "deadline": ""},
        {"title": "No deadline", "deadline": ""},
    ]
    kept = scraper.filter_expired(tenders, today=today)
    titles = {t["title"] for t in kept}
    assert "Future" in titles
    assert "No deadline" in titles
    assert "Past" not in titles            # parseable past date
    assert "Awarded already" not in titles  # closed keyword in title


def test_filter_new(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "STATE_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(scraper, "OUTPUT_DIR", tmp_path)
    a = scraper.make_tender(source="S", title="A", url="ua")
    b = scraper.make_tender(source="S", title="B", url="ub")
    scraper.save_seen([a["id"]])
    new = scraper.filter_new([a, b])
    assert [t["title"] for t in new] == ["B"]
