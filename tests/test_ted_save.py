"""Behaviour tests for save_to_csv in both TED entry modules.

They use different file layouts which must be preserved:
  ted_intelligence_ai : live + intel concatenated into ONE file (ted_results_ai.csv)
  ted_intelligence    : live -> csv_file, intel -> separate closed_ai_file
Both dedupe on pub_num (keep last) and add a fetched_date column.
"""
import pandas as pd


def _df(pub_nums, value=1):
    return pd.DataFrame([{"pub_num": p, "title": f"t-{p}", "val": value} for p in pub_nums])


def test_ai_save_concatenates_live_and_intel_and_dedupes(tmp_path):
    import ted_intelligence_ai as mod
    csv = tmp_path / "ted_results_ai.csv"
    # pre-existing row with a pub_num that the new live data also contains
    _df(["OLD", "0001"], value=1).assign(fetched_date="2020-01-01").to_csv(csv, index=False)

    mod.save_to_csv(_df(["0001", "NEW"], value=2), _df(["INTEL1"]), csv_file=str(csv))

    out = pd.read_csv(csv)
    assert set(out["pub_num"]) == {"OLD", "0001", "NEW", "INTEL1"}
    assert "fetched_date" in out.columns
    # keep="last" → the new 0001 (val=2) wins over the pre-existing one (val=1)
    assert int(out.loc[out["pub_num"] == "0001", "val"].iloc[0]) == 2


def test_keyword_save_writes_two_separate_files(tmp_path):
    import ted_intelligence as mod
    csv = tmp_path / "ted_results_ai.csv"
    closed = tmp_path / "ted_closed_relevant.csv"

    mod.save_to_csv(_df(["L1", "L2"]), _df(["I1"]),
                    csv_file=str(csv), closed_ai_file=str(closed))

    live_out = pd.read_csv(csv)
    closed_out = pd.read_csv(closed)
    assert set(live_out["pub_num"]) == {"L1", "L2"}      # intel not mixed in
    assert set(closed_out["pub_num"]) == {"I1"}
    assert "fetched_date" in live_out.columns and "fetched_date" in closed_out.columns
