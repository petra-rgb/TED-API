"""Shared pytest setup: put the project root on sys.path and expose fixture/golden helpers."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = Path(__file__).resolve().parent / "golden"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def load_golden(name: str):
    return json.loads((GOLDEN / name).read_text())
