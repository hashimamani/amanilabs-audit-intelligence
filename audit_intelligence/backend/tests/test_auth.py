"""
Login/RBAC, exercised through the real API layer via FastAPI's
TestClient, against its own throwaway SQLite file (DATABASE_URL must be
set before anything imports app.core.db - see test_tenant_isolation.py's
docstring for why).
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


def _login(client, email, password):
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_with_correct_credentials_succeeds(client):
    resp = client.post(
        "/auth/login", json={"email": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_DEV_PASSWORD}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == DEFAULT_ADMIN_EMAIL
    assert body["user"]["role"] == "admin"


def test_login_with_wrong_password_is_401(client):
    resp = client.post("/auth/login", json={"email": DEFAULT_ADMIN_EMAIL, "password": "wrong"})
    assert resp.status_code == 401


def test_login_with_unknown_email_is_401(client):
    resp = client.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever"})
    assert resp.status_code == 401


def test_me_requires_a_valid_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401

    token = _login(client, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_DEV_PASSWORD)
    resp = client.get("/auth/me", headers=_headers(token))
    assert resp.status_code == 200
    assert resp.json()["email"] == DEFAULT_ADMIN_EMAIL


def test_deactivated_user_is_rejected_even_with_a_valid_token(client):
    admin_token = _login(client, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_DEV_PASSWORD)
    created = client.post(
        "/users",
        json={
            "email": "to-deactivate@example.com",
            "name": "Soon Deactivated",
            "password": "irrelevant-pw",
            "role": "auditor",
        },
        headers=_headers(admin_token),
    ).json()

    user_token = _login(client, "to-deactivate@example.com", "irrelevant-pw")
    assert client.get("/auth/me", headers=_headers(user_token)).status_code == 200

    client.patch(f"/users/{created['id']}", json={"is_active": False}, headers=_headers(admin_token))
    assert client.get("/auth/me", headers=_headers(user_token)).status_code == 401


def test_admin_only_routes_reject_an_auditor(client):
    admin_token = _login(client, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_DEV_PASSWORD)
    client.post(
        "/users",
        json={
            "email": "plain-auditor@example.com",
            "name": "Plain Auditor",
            "password": "auditor-pw",
            "role": "auditor",
        },
        headers=_headers(admin_token),
    )
    auditor_token = _login(client, "plain-auditor@example.com", "auditor-pw")

    resp = client.get("/users", headers=_headers(auditor_token))
    assert resp.status_code == 403


def test_user_crud_is_scoped_to_the_admins_own_tenant(client):
    other_admin, other_password = create_tenant(
        "auth-test-other", "Other Tenant", "other-admin@example.com", "Other Admin"
    )
    other_token = _login(client, other_admin.email, other_password)

    default_admin_token = _login(client, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_DEV_PASSWORD)
    default_users = client.get("/users", headers=_headers(default_admin_token)).json()
    foreign_user_id = next(u["id"] for u in default_users if u["email"] == DEFAULT_ADMIN_EMAIL)

    resp = client.patch(
        f"/users/{foreign_user_id}", json={"is_active": False}, headers=_headers(other_token)
    )
    assert resp.status_code == 404
