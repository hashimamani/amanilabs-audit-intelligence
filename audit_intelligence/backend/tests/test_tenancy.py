"""
Exercises the multi-tenant API layer end-to-end via FastAPI's TestClient,
against a throwaway SQLite file so it never touches a developer's real
audit_intelligence.db. DATABASE_URL must be pointed at that throwaway file
BEFORE anything imports app.core.db (transitively imported by app.main and
everything under app.api), since the engine binds to DATABASE_URL at
import time.
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
def tenant_a_key():
    return create_tenant("tenant-a", "Tenant A SACCO").api_key


@pytest.fixture(scope="module")
def tenant_b_key():
    return create_tenant("tenant-b", "Tenant B SACCO").api_key


def _headers(key):
    return {"X-Tenant-Key": key}


def test_no_header_is_rejected(client):
    resp = client.get("/cases")
    assert resp.status_code == 401


def test_unknown_key_is_rejected(client):
    resp = client.get("/cases", headers=_headers("not-a-real-key"))
    assert resp.status_code == 401


def test_default_tenant_key_works_end_to_end(client):
    resp = client.post("/analysis/run", json={}, headers=_headers(DEFAULT_TENANT_DEV_KEY))
    assert resp.status_code == 200
    body = resp.json()
    assert body["case_count"] > 0

    resp = client.get("/cases", headers=_headers(DEFAULT_TENANT_DEV_KEY))
    assert resp.status_code == 200
    assert len(resp.json()) > 0


def test_tenants_cannot_see_each_others_cases(client, tenant_a_key, tenant_b_key):
    run_a = client.post("/analysis/run", json={}, headers=_headers(tenant_a_key))
    assert run_a.status_code == 200

    cases_b = client.get("/cases", headers=_headers(tenant_b_key))
    assert cases_b.status_code == 200
    assert cases_b.json() == []

    cases_a = client.get("/cases", headers=_headers(tenant_a_key))
    assert cases_a.status_code == 200
    assert len(cases_a.json()) > 0


def test_fetching_another_tenants_case_by_id_is_a_404(client, tenant_a_key, tenant_b_key):
    cases_a = client.get("/cases", headers=_headers(tenant_a_key)).json()
    case_id = cases_a[0]["id"]

    resp = client.get(f"/cases/{case_id}", headers=_headers(tenant_b_key))
    assert resp.status_code == 404

    resp = client.get(f"/cases/{case_id}", headers=_headers(tenant_a_key))
    assert resp.status_code == 200
