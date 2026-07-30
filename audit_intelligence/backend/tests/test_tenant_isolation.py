"""
Exercises cross-tenant case isolation end-to-end via FastAPI's
TestClient, against a throwaway SQLite file so it never touches a
developer's real audit_intelligence.db. DATABASE_URL must be pointed at
that throwaway file BEFORE anything imports app.core.db (transitively
imported by app.main and everything under app.api), since the engine
binds to DATABASE_URL at import time.

Auth is now individual login (see test_auth.py for the auth mechanics
themselves) rather than a shared per-tenant key, but the isolation
guarantee this file checks - one tenant can never see another's cases -
is unchanged.
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
from app.core.auth import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_DEV_PASSWORD
from app.scripts.create_tenant import create_tenant


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _login(client, email, password):
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def default_token(client):
    return _login(client, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_DEV_PASSWORD)


@pytest.fixture(scope="module")
def tenant_a_token(client):
    admin, password = create_tenant("tenant-a", "Tenant A SACCO", "admin-a@example.com", "Admin A")
    return _login(client, admin.email, password)


@pytest.fixture(scope="module")
def tenant_b_token(client):
    admin, password = create_tenant("tenant-b", "Tenant B SACCO", "admin-b@example.com", "Admin B")
    return _login(client, admin.email, password)


def test_no_token_is_rejected(client):
    resp = client.get("/cases")
    assert resp.status_code == 401


def test_unknown_token_is_rejected(client):
    resp = client.get("/cases", headers=_headers("not-a-real-token"))
    assert resp.status_code == 401


def test_default_tenant_works_end_to_end(client, default_token):
    resp = client.post("/analysis/run", json={}, headers=_headers(default_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["case_count"] > 0

    resp = client.get("/cases", headers=_headers(default_token))
    assert resp.status_code == 200
    assert len(resp.json()) > 0


def test_tenants_cannot_see_each_others_cases(client, tenant_a_token, tenant_b_token):
    run_a = client.post("/analysis/run", json={}, headers=_headers(tenant_a_token))
    assert run_a.status_code == 200

    cases_b = client.get("/cases", headers=_headers(tenant_b_token))
    assert cases_b.status_code == 200
    assert cases_b.json() == []

    cases_a = client.get("/cases", headers=_headers(tenant_a_token))
    assert cases_a.status_code == 200
    assert len(cases_a.json()) > 0


def test_fetching_another_tenants_case_by_id_is_a_404(client, tenant_a_token, tenant_b_token):
    cases_a = client.get("/cases", headers=_headers(tenant_a_token)).json()
    case_id = cases_a[0]["id"]

    resp = client.get(f"/cases/{case_id}", headers=_headers(tenant_b_token))
    assert resp.status_code == 404

    resp = client.get(f"/cases/{case_id}", headers=_headers(tenant_a_token))
    assert resp.status_code == 200
