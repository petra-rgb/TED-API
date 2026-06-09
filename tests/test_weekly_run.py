"""Unit tests for the pure deadline logic in weekly_run.py."""
import datetime as dt

import weekly_run


def test_smart_parse_end_of_month():
    assert weekly_run._smart_parse("End of June 2026") == dt.date(2026, 6, 30)


def test_smart_parse_range_takes_later_date():
    assert weekly_run._smart_parse("15/22 May 2026") == dt.date(2026, 5, 22)


def test_smart_parse_delegates_to_scraper():
    assert weekly_run._smart_parse("30.04.2026") == dt.date(2026, 4, 30)


def test_smart_parse_blank():
    assert weekly_run._smart_parse("") is None
    assert weekly_run._smart_parse("nan") is None
    assert weekly_run._smart_parse(None) is None


def test_is_expired():
    assert weekly_run._is_expired({"deadline": "01.01.2020"}) is True
    assert weekly_run._is_expired({"deadline": "31.12.2099"}) is False
    assert weekly_run._is_expired({"deadline": "", "call_deadline": "31.12.2099"}) is False
    assert weekly_run._is_expired({"deadline": "", "call_deadline": ""}) is False
    # call_deadline in the past also counts as expired
    assert weekly_run._is_expired({"deadline": "", "call_deadline": "01.01.2020"}) is True
