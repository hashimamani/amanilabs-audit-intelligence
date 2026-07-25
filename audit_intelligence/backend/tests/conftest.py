import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.rules.dataset import SaccoDataset
from app.rules.engine import RuleEngine
from app.cases.builder import build_cases

PROJECT_ROOT = BACKEND_DIR.parents[1]
DATA_DIR = PROJECT_ROOT / "synthetic_sacco_data"

# Session-scoped: loading the full dataset and running all 8 rules takes a
# couple of seconds, and every test in this suite reads the same fixed
# synthetic dataset - no need to redo that work per test.


@pytest.fixture(scope="session")
def dataset():
    return SaccoDataset(str(DATA_DIR))


@pytest.fixture(scope="session")
def flags(dataset):
    return RuleEngine().run(dataset)


@pytest.fixture(scope="session")
def cases(flags, dataset):
    return build_cases(flags, dataset=dataset)


@pytest.fixture(scope="session")
def ground_truth():
    with open(DATA_DIR / "ground_truth.json") as f:
        return json.load(f)
