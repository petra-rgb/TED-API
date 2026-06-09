"""Smoke tests: run each cron entry point end-to-end with the network mocked.

These prove the wiring (fetch -> filter -> AI -> save -> export -> slack) holds
together and writes the expected output files, without hitting TED or Claude.
"""
from conftest import load_fixture

import scraper
import ted_core


class _Block:
    text = "RELEVANT: YES\nREASON: ok"


class _Resp:
    content = [_Block()]  # noqa: RUF012  (test stub)


class _FakeClient:
    class messages:
        @staticmethod
        def create(**kw):
            return _Resp()


def _patch_ted(monkeypatch):
    monkeypatch.setattr(ted_core, "paginate",
                        lambda *a, **k: (load_fixture("ted_notices.json"), None))
    monkeypatch.setattr(ted_core, "claude_client", lambda key: _FakeClient())


def test_ted_ai_main_writes_combined_csv(tmp_path, monkeypatch):
    import ted_intelligence_ai as mod
    monkeypatch.chdir(tmp_path)
    _patch_ted(monkeypatch)
    mod.main()
    assert (tmp_path / "ted_results_ai.csv").exists()


def test_ted_keyword_main_writes_split_csvs(tmp_path, monkeypatch):
    import ted_intelligence as mod
    monkeypatch.chdir(tmp_path)
    _patch_ted(monkeypatch)
    mod.main()
    assert (tmp_path / "ted_results_ai.csv").exists()
    assert (tmp_path / "ted_closed_relevant.csv").exists()


def test_weekly_run_writes_output_csvs(tmp_path, monkeypatch):
    import evaluate
    import weekly_run
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()

    raw = [scraper.make_tender(source="EIT Food", title="Deep tech GTM study",
                               url="http://x/1", deadline="31.12.2099")]

    def _fake_eval(tenders, **kw):
        return [{**t, "fit": "YES", "score": 9, "fit_reason": "r",
                 "fit_match": "GTM", "call_summary": "s", "call_deadline": ""}
                for t in tenders]

    monkeypatch.setattr(scraper, "run_all", lambda *a, **k: raw)
    monkeypatch.setattr(evaluate, "evaluate_all", _fake_eval)

    result = weekly_run.run(api_key="sk-test", verbose=False)
    assert len(result) == 1
    assert (tmp_path / "output" / "active_tenders.csv").exists()
    assert (tmp_path / "output" / "new_this_week.csv").exists()
    assert (tmp_path / "output" / "all_tenders_master.csv").exists()
