"""Normalisation helpers shared by the golden generator and the golden tests.

Kept identical on both sides so a NaN/None or datetime mismatch can't make a passing
refactor look like a regression (NaN != NaN in plain dict equality).
"""
import datetime as dt
import math


def _clean_scalar(v):
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, dt.datetime):
        return v.isoformat()
    return v


def df_records(df):
    """DataFrame -> list of JSON-comparable dicts, sorted by pub_num, NaN->None."""
    if df is None or getattr(df, "empty", True):
        return []
    recs = df.to_dict("records")
    cleaned = [{k: _clean_scalar(v) for k, v in r.items()} for r in recs]
    return sorted(cleaned, key=lambda r: r.get("pub_num", ""))


def norm_extract(d):
    return {k: _clean_scalar(v) for k, v in d.items()}
