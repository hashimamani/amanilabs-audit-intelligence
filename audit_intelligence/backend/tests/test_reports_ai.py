"""
Board report generator, exercised through the real API layer. The
Anthropic client is mocked - no real key, no network call. The important
assertions are: the grounding text handed to the (mocked) client really
does contain the selected cases' real evidence (same discipline as case
Q&A, just batched), tenant isolation holds for explicit case_ids, and the
default selection is Critical+High only, capped, never crashes on an
empty result.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.ai import get_anthropic_client
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
def other_tenant_token(client):
    admin, password = create_tenant("reports-ai-other", "Other Tenant", "reports-ai-admin@example.com", "Reports AI Admin")
    return _login(client, admin.email, password)


@pytest.fixture(scope="module")
def default_case_ids(client, default_token):
    client.post("/analysis/run", json={}, headers=_headers(default_token))
    cases = client.get("/cases?limit=200", headers=_headers(default_token)).json()
    return [c["id"] for c in cases]


def _fake_client_returning(text, stop_reason="end_turn"):
    block = MagicMock(type="text", text=text)
    fake = MagicMock()
    fake.messages.create.return_value = MagicMock(content=[block], stop_reason=stop_reason)
    return fake


@pytest.fixture
def mocked_ai():
    fake = _fake_client_returning("placeholder report")
    app.dependency_overrides[get_anthropic_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_anthropic_client, None)


def test_report_default_selection_is_critical_high_capped_at_20(client, default_token, default_case_ids, mocked_ai):
    resp = client.post("/reports/generate", json={}, headers=_headers(default_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["case_count"] == 20

    system_prompt = mocked_ai.messages.create.call_args.kwargs["system"]
    assert "Severity: Critical" in system_prompt or "Severity: High" in system_prompt
    assert "Severity: Medium" not in system_prompt
    assert "Severity: Low" not in system_prompt


def test_report_explicit_selection_grounds_on_real_evidence(client, default_token, default_case_ids, mocked_ai):
    target_ids = default_case_ids[:2]
    resp = client.post("/reports/generate", json={"case_ids": target_ids}, headers=_headers(default_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["case_count"] == 2

    system_prompt = mocked_ai.messages.create.call_args.kwargs["system"]
    for case_id in target_ids:
        case = client.get(f"/cases/{case_id}", headers=_headers(default_token)).json()
        assert case["case_ref"] in system_prompt
        for e in case["evidence"]:
            assert e["value"] in system_prompt


def test_report_explicit_selection_excludes_foreign_tenant_case(
    client, default_case_ids, other_tenant_token, mocked_ai
):
    foreign_case_id = default_case_ids[0]
    resp = client.post(
        "/reports/generate",
        json={"case_ids": [foreign_case_id]},
        headers=_headers(other_tenant_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["case_count"] == 0
    mocked_ai.messages.create.assert_not_called()


def test_report_rejects_too_many_case_ids(client, default_token, mocked_ai):
    too_many_ids = list(range(1, 52))  # MAX_REPORT_CASES = 50
    resp = client.post("/reports/generate", json={"case_ids": too_many_ids}, headers=_headers(default_token))
    assert resp.status_code == 400
    mocked_ai.messages.create.assert_not_called()


def test_report_503_when_key_unset(client, default_token, monkeypatch):
    app.dependency_overrides.pop(get_anthropic_client, None)
    monkeypatch.setattr("app.core.ai.ANTHROPIC_API_KEY", None)
    resp = client.post("/reports/generate", json={}, headers=_headers(default_token))
    assert resp.status_code == 503
