"""
Resolves a dataset_id to a directory of the 8 SACCO CSVs SaccoDataset
expects. "default" (or no dataset_id at all) points at the bundled
synthetic_sacco_data used throughout development so far, so /analysis/run
works out of the box with no upload required.
"""

from pathlib import Path

REQUIRED_FILES = [
    "members.csv", "branches.csv", "employees.csv", "accounts.csv",
    "transactions.csv", "loans.csv", "guarantors.csv", "loan_payments.csv",
]

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parents[1]
DEFAULT_DATASET_DIR = PROJECT_ROOT / "synthetic_sacco_data"
UPLOADS_DIR = BACKEND_DIR / "data" / "uploads"

DEFAULT_DATASET_ID = "default"


class DatasetNotFoundError(Exception):
    pass


def resolve_dataset_dir(dataset_id: str | None) -> Path:
    if dataset_id is None or dataset_id == DEFAULT_DATASET_ID:
        return DEFAULT_DATASET_DIR
    dataset_dir = UPLOADS_DIR / dataset_id
    if not dataset_dir.is_dir():
        raise DatasetNotFoundError(f"No uploaded dataset found for id '{dataset_id}'")
    return dataset_dir
