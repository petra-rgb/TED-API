#!/usr/bin/env python3
"""
Regenerate golden snapshots from the CURRENT code.

Golden-output (characterization) tests lock the exact behaviour of the pure
transformation functions so the Phase 2 de-duplication and Phase 3 complexity
refactors can be proven byte-for-byte behaviour-preserving.

Run from the project root (TED-API/):
    python tests/_generate_goldens.py

Only run this deliberately, when you have confirmed a behaviour change is
intended — never to paper over a failing test.
"""
import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
FIX = HERE / "fixtures"
GOLD = HERE / "golden"
GOLD.mkdir(exist_ok=True)

from _golden_util import df_records, norm_extract  # noqa: E402


def main() -> None:
    notices = json.loads((FIX / "ted_notices.json").read_text())
    import ted_core

    for mod_name in ("ted_intelligence_ai", "ted_intelligence"):
        mod = __import__(mod_name)

        extract_golden = [norm_extract(mod.extract(n)) for n in notices]
        (GOLD / f"{mod_name}_extract.json").write_text(
            json.dumps(extract_golden, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        )

        with mock.patch.object(ted_core, "paginate", return_value=(notices, None)):
            live, intel = mod.fetch(days_back=1)
        fetch_golden = {"live": df_records(live), "intel": df_records(intel)}
        (GOLD / f"{mod_name}_fetch.json").write_text(
            json.dumps(fetch_golden, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        )
        print(f"{mod_name}: extract={len(extract_golden)} "
              f"live={len(fetch_golden['live'])} intel={len(fetch_golden['intel'])}")

    _generate_scraper_goldens()


def _generate_scraper_goldens() -> None:
    import scraper

    import scraper_cases as sc

    out = {}
    for key, site in sc.SITES.items():
        with sc.patched(scraper):
            tenders = scraper.SCRAPERS[key](site)
        out[key] = sc.normalize(tenders)
    (GOLD / "scrapers.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )
    print("scrapers: " + ", ".join(f"{k}={len(v)}" for k, v in out.items()))


if __name__ == "__main__":
    main()
