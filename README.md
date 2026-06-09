# TED-API — EU tender intelligence

Scrapes EU public tenders (TED — Tenders Electronic Daily — plus EIT Knowledge &
Innovation Community sites), filters them for relevance with the Anthropic Claude
API, and serves the results through a Streamlit app.

## Architecture

```
                 GitHub Actions (cron)                         Streamlit app
  ┌───────────────────────────────────────────┐   ┌──────────────────────────────┐
  │ ted_intelligence.py    (daily, keyword)    │   │ app.py            (overview)  │
  │ ted_intelligence_ai.py (daily, AI run)     │──▶│ pages/1_TED_Tenders.py        │
  │ weekly_run.py          (weekly, EIT)       │   │ pages/2_EIT_Tenders.py        │
  └───────────────────────────────────────────┘   │ pages/3_Tender_Search.py      │
        │ writes CSVs (committed back to repo)     └──────────────────────────────┘
        ▼                                                       ▲ reads CSVs
                            committed CSV data store
```

- **`ted_core.py`** — the single source of truth for the TED pipeline: API
  query/pagination, notice extraction, language/deadline/negative filters, the
  Claude relevance filters (official `anthropic` SDK), and CSV/XLSX/Slack output.
  The two daily entry scripts and the client portal all import it; they differ
  only in parameters (deadline handling, profile text, save layout).
- **`scraper.py`** — per-site scrapers for 8 EIT KIC procurement pages.
- **`evaluate.py`** — Claude fit-scoring for EIT tenders (used by `weekly_run.py`).

## Running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt              # runtime
pip install -r requirements-dev.txt          # + ruff / radon / pytest

# Secrets (env vars or Streamlit secrets)
export ANTHROPIC_API_KEY=...                  # required for the AI filters
export SLACK_WEBHOOK_URL=...                  # optional digests

streamlit run app.py                          # the UI
python ted_intelligence_ai.py                 # a daily AI fetch
python weekly_run.py                          # the weekly EIT run
python scraper.py --site climate_kic          # one scraper, ad hoc
```

## Quality gates

```bash
pytest -q                                     # 42 characterization + unit tests
ruff check .                                  # lint (config in pyproject.toml)
radon cc -s *.py pages/*.py                   # complexity (target: every block <= 15)
```

CI (`.github/workflows/quality.yml`) runs all three on every push/PR and fails
the build if any function exceeds cyclomatic complexity 15.

The test suite pins current behaviour with golden snapshots
(`tests/golden/`). Regenerate them **only** after a deliberate behaviour change:
`python tests/_generate_goldens.py`.

## Known data-pipeline caveats (pre-existing — flagged, not changed)

These were left intact to preserve current behaviour; they are worth a follow-up
decision:

1. **`daily_run.yml` commits `ted_results.csv`, but `ted_intelligence.py` never
   writes that file** — it writes `ted_results_ai.csv` + `ted_closed_relevant.csv`.
   `app.py`/`pages/1` *read* `ted_results.csv`, so that view is served from a
   file no current script updates.
2. **Both daily scripts write `ted_results_ai.csv`** with different layouts
   (`ted_intelligence_ai.py` concatenates live + awarded; `ted_intelligence.py`
   splits awarded into `ted_closed_relevant.csv`). Running both (07:00 and 07:30)
   has them overwrite each other's `ted_results_ai.csv`.
3. The growing committed CSVs act as the datastore. Consider migrating to the
   Supabase backend already used by `pages/1` for review state.

`eit_tenders.csv` is kept in the repo root — it is read by `pages/3_Tender_Search.py`
(the EIT comparison). Other stale root-level CSV/XLSX duplicates were removed.
