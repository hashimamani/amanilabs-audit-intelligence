"""
Analytics "ask for a chart" endpoint, exercised through the real API layer.
The Anthropic client is mocked to return a forced generate_chart tool_use
block - these tests verify the backend's own aggregation/enum-validation
logic (the part that actually guarantees no invented numbers), not the
model's chart-picking judgment. No real key, no network call.
"""

import os
import sys
import tempfile
from collections import Counter
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
def seeded_cases(client, default_token):
    client.post("/analysis/run", json={}, headers=_headers(default_token))
    # limit=200 (the max page size) so this actually captures every case,
    # not just the default page of 50 - matches the max the rest of the app
    # already relies on at this project's case volumes (dozens, not
    # thousands; see DashboardPage.tsx's client-side aggregation precedent).
    resp = client.get("/cases?limit=200", headers=_headers(default_token))
    return resp.json()


def _fake_tool_use_client(group_by, metric):
    block = MagicMock(type="tool_use", input={"group_by": group_by, "metric": metric})
    # `name=` in the MagicMock() constructor is reserved for the mock's own
    # debug repr, not a settable attribute - assign after construction.
    block.name = "generate_chart"
    fake = MagicMock()
    fake.messages.create.return_value = MagicMock(content=[block])
    return fake


@pytest.fixture
def mocked_ai_tool(request):
    group_by, metric = request.param
    fake = _fake_tool_use_client(group_by, metric)
    app.dependency_overrides[get_anthropic_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_anthropic_client, None)


@pytest.mark.parametrize("mocked_ai_tool", [("severity", "case_count")], indirect=True)
def test_analytics_severity_groupby_matches_real_counts(client, default_token, seeded_cases, mocked_ai_tool):
    resp = client.post("/analytics/query", json={"question": "cases by severity"}, headers=_headers(default_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["group_by"] == "severity"

    expected = Counter(c["severity"] for c in seeded_cases)
    actual = {d["label"]: d["value"] for d in body["data"]}
    assert actual == dict(expected)


@pytest.mark.parametrize("mocked_ai_tool", [("rule_id", "case_count")], indirect=True)
def test_analytics_rule_id_groupby_counts_once_per_rule(client, default_token, seeded_cases, mocked_ai_tool):
    resp = client.post(
        "/analytics/query", json={"question": "which rules fire most"}, headers=_headers(default_token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    expected: Counter = Counter()
    for c in seeded_cases:
        for rule_id in c["triggered_rules"]:
            expected[rule_id] += 1
    actual = {d["label"]: d["value"] for d in body["data"]}
    assert actual == dict(expected)
    # A case triggering 2+ rules proves this is genuinely per-rule, not
    # accidentally degenerating into per-case counting.
    assert any(len(c["triggered_rules"]) > 1 for c in seeded_cases), "fixture doesn't exercise a multi-rule case"


@pytest.mark.parametrize("mocked_ai_tool", [("loan_amount", "case_count")], indirect=True)
def test_analytics_rejects_out_of_enum_group_by(client, default_token, mocked_ai_tool):
    resp = client.post("/analytics/query", json={"question": "..."}, headers=_headers(default_token))
    assert resp.status_code == 400


def test_analytics_503_when_key_unset(client, default_token, monkeypatch):
    app.dependency_overrides.pop(get_anthropic_client, None)
    monkeypatch.setattr("app.core.ai.ANTHROPIC_API_KEY", None)
    resp = client.post("/analytics/query", json={"question": "..."}, headers=_headers(default_token))
    assert resp.status_code == 503
