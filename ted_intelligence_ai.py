"""
Daily TED fetch + Claude relevance filter (AI run) — DevelopMinded.

Thin entry point over ted_core (the shared pipeline). This run applies the
deadline filter uniformly to every notice and writes live + awarded rows into a
single combined CSV. Scheduled by .github/workflows/daily_run_ai.yml.
"""
import ted_core
from ted_core import (  # noqa: F401  (re-exported for back-compat / tests)
    extract,
    flat,
    get_bucket,
    is_negative,
    make_query,
    parse_deadline,
)

DAYS_BACK = ted_core.DAYS_BACK

DM_PROFILE = """
DevelopMinded is a technology commercialisation consultancy that supports deep tech spinouts,
EIC/Horizon Europe grantees, and research-based ventures. Our core services are:
- Technology commercialisation and exploitation of research results
- Go-to-market strategy and market intelligence (market sizing, segmentation, competitive analysis)
- Investment readiness and fundraising support (pitch decks, financial modelling, investor targeting)
- EU tender bid preparation (e.g. HADEA, EIC, Horizon Europe procurements)
- Partnership strategy and stakeholder outreach
- Regulatory pathway analysis for market entry
- Talent strategy and HR roadmap for scaling ventures
- Evaluation and assessment of investor readiness, innovation programmes, and startup competitions

Ideal clients: EIC Accelerator / EIC Transition / EIC Pathfinder grantees, university spinouts,
deep tech companies (biotech, medtech, cleantech, agtech, defence tech) at TRL 4-7 needing
commercial and strategic support to reach the market.

NOT relevant: running clinical trials, lab/research execution, software development,
infrastructure/construction management, academic surveys, open source
maintenance, ecological studies, or procurements for physical goods/equipment.
"""


def fetch(days_back: int = DAYS_BACK):
    """Fetch + filter TED notices; deadline filter applies to awarded contracts too."""
    return ted_core.fetch_ted(days_back, skip_intel_deadline=False, progress=print)


def save_to_csv(live, intel, csv_file: str = "ted_results_ai.csv"):
    """Combined layout: live + awarded rows in one file."""
    ted_core.save_results(live, intel, csv_file=csv_file)


def main() -> None:
    live, intel = fetch()
    live = ted_core.ai_filter(live, profile=DM_PROFILE)
    intel = ted_core.ai_filter_intel(intel)
    save_to_csv(live, intel)
    ted_core.export_xlsx(live, intel)
    ted_core.send_slack_digest(live, intel)


if __name__ == "__main__":
    main()
