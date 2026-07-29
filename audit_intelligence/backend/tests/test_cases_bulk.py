"""
Bulk case-status update, exercised through the real API layer (not just
the ORM) so tenant scoping on the endpoint is actually verified. Same
throwaway-SQLite-via-DATABASE_URL pattern as test_tenancy.py, in its own
temp file so the two test modules never share database state.
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.tenancy import DEFAULT_TENANT_DEV_KEY
from app.scripts.create_tenant import create_tenant


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def other_tenant_key():
    return create_tenant("bulk-test-other", "Other Tenant").api_key


def _headers(key):
    return {"X-Tenant-Key": key}


@pytest.fixture(scope="module")
def default_case_ids(client):
    client.post("/analysis/run", json={}, headers=_headers(DEFAULT_TENANT_DEV_KEY))
    cases = client.get("/cases", headers=_headers(DEFAULT_TENANT_DEV_KEY)).json()
    return [c["id"] for c in cases]


def test_bulk_update_changes_only_the_given_cases(client, default_case_ids):
    target_ids = default_case_ids[:3]
    untouched_id = default_case_ids[3]

    resp = client.patch(
        "/cases/bulk-status",
        json={"case_ids": target_ids, "status": "Closed"},
        headers=_headers(DEFAULT_TENANT_DEV_KEY),
    )
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 3

    for case_id in target_ids:
        row = client.get(f"/cases/{case_id}", headers=_headers(DEFAULT_TENANT_DEV_KEY)).json()
        assert row["status"] == "Closed"

    untouched = client.get(f"/cases/{untouched_id}", headers=_headers(DEFAULT_TENANT_DEV_KEY)).json()
    assert untouched["status"] != "Closed"


def test_bulk_update_ignores_another_tenants_case_ids(client, default_case_ids, other_tenant_key):
    foreign_case_id = default_case_ids[4]

    resp = client.patch(
        "/cases/bulk-status",
        json={"case_ids": [foreign_case_id], "status": "In Progress"},
        headers=_headers(other_tenant_key),
    )
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 0

    row = client.get(f"/cases/{foreign_case_id}", headers=_headers(DEFAULT_TENANT_DEV_KEY)).json()
    assert row["status"] != "In Progress"


def test_bulk_update_with_empty_ids_is_a_no_op(client):
    resp = client.patch(
        "/cases/bulk-status",
        json={"case_ids": [], "status": "Closed"},
        headers=_headers(DEFAULT_TENANT_DEV_KEY),
    )
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 0
