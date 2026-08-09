"""
Case Q&A ("ask about this case"), exercised through the real API layer.
The Anthropic client is mocked via app.dependency_overrides - no real key,
no network call. What actually matters here isn't that the mock returns
text (that's trivial); it's that the grounding context passed to the
(mocked) client really does contain the case's real evidence, which is
the code-level enforcement of the product's "never invent evidence" rule.
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
    admin, password = create_tenant("case-ai-other", "Other Tenant", "case-ai-admin@example.com", "Case AI Admin")
    return _login(client, admin.email, password)


@pytest.fixture(scope="module")
def default_case_ids(client, default_token):
    client.post("/analysis/run", json={}, headers=_headers(default_token))
    cases = client.get("/cases", headers=_headers(default_token)).json()
    return [c["id"] for c in cases]


def _fake_client_returning(text, stop_reason="end_turn"):
    block = MagicMock(type="text", text=text)
    fake = MagicMock()
    fake.messages.create.return_value = MagicMock(content=[block], stop_reason=stop_reason)
    return fake


@pytest.fixture
def mocked_ai():
    """Overrides get_anthropic_client with a mock for one test, then restores
    it - so the 503-when-unset test (which deliberately clears any override)
    isn't affected by leftover state from other tests, regardless of order."""
    fake = _fake_client_returning("placeholder answer")
    app.dependency_overrides[get_anthropic_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_anthropic_client, None)


def test_ask_404_for_missing_case(client, default_token, mocked_ai):
    resp = client.post(
        "/cases/999999/ask",
        json={"question": "why was this flagged?"},
        headers=_headers(default_token),
    )
    assert resp.status_code == 404
    mocked_ai.messages.create.assert_not_called()


def test_ask_404_for_foreign_tenant_case(client, default_token, default_case_ids, other_tenant_token, mocked_ai):
    foreign_case_id = default_case_ids[0]
    resp = client.post(
        f"/cases/{foreign_case_id}/ask",
        json={"question": "why was this flagged?"},
        headers=_headers(other_tenant_token),
    )
    assert resp.status_code == 404
    mocked_ai.messages.create.assert_not_called()


def test_ask_grounds_on_real_case_evidence(client, default_token, default_case_ids, mocked_ai):
    case_id = default_case_ids[0]
    real_case = client.get(f"/cases/{case_id}", headers=_headers(default_token)).json()

    resp = client.post(
        f"/cases/{case_id}/ask",
        json={"question": "what evidence supports this flag?"},
        headers=_headers(default_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["answer"] == "placeholder answer"

    system_prompt = mocked_ai.messages.create.call_args.kwargs["system"]
    for evidence_item in real_case["evidence"]:
        assert evidence_item["value"] in system_prompt
    for flag in real_case["flags"]:
        for evidence_item in flag["evidence"]:
            assert evidence_item["value"] in system_prompt


def test_ask_truncation_note_appended_on_max_tokens(client, default_token, default_case_ids):
    case_id = default_case_ids[0]
    fake = _fake_client_returning("partial answer", stop_reason="max_tokens")
    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        resp = client.post(
            f"/cases/{case_id}/ask",
            json={"question": "..."},
            headers=_headers(default_token),
        )
        assert resp.status_code == 200
        assert "truncated" in resp.json()["answer"].lower()
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


def test_ask_503_when_key_unset(client, default_token, default_case_ids, monkeypatch):
    case_id = default_case_ids[0]
    app.dependency_overrides.pop(get_anthropic_client, None)
    monkeypatch.setattr("app.core.ai.ANTHROPIC_API_KEY", None)

    resp = client.post(
        f"/cases/{case_id}/ask",
        json={"question": "..."},
        headers=_headers(default_token),
    )
    assert resp.status_code == 503
