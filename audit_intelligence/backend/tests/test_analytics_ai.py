"""
Analytics "ask for a chart" endpoint, exercised through the real API layer.
Since the actual aggregation now happens in Claude-authored code running in
a sandbox (not in this codebase), these tests can't meaningfully assert a
specific computed answer - verifying that is exactly what the enum-based
predecessor did, and exactly what limited it (see PROJECT_CONTEXT.md for
the full reasoning behind the redesign). What's still under this codebase's
control, and what these tests verify instead: the case data actually
handed to the model (real, privacy-minimized, spans all runs), and the
response parsing/validation logic (never trust the model's printed JSON
shape blindly, even though the numbers inside it are already trustworthy
because they came from code that actually ran). No real key, no network
call anywhere in this file.
"""

import csv
import io
import json
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
    admin, password = create_tenant(
        "analytics-ai-other", "Other Tenant", "analytics-ai-admin@example.com", "Analytics AI Admin"
    )
    return _login(client, admin.email, password)


@pytest.fixture(scope="module", autouse=True)
def ensure_seeded(client, default_token):
    # Guarantees the default tenant has at least one run/case before any
    # test needs real data, regardless of test execution order.
    client.post("/analysis/run", json={}, headers=_headers(default_token))


def _bash_result_block(stdout: str, return_code: int = 0):
    result_content = MagicMock(type="bash_code_execution_result", stdout=stdout, stderr="", return_code=return_code)
    return MagicMock(type="bash_code_execution_tool_result", content=result_content)


def _fake_client_returning_chart(chart: dict):
    fake = MagicMock()
    fake.messages.create.return_value = MagicMock(
        content=[_bash_result_block(json.dumps(chart))], stop_reason="end_turn"
    )
    return fake


def _query_with_mock(client, token, fake, question="..."):
    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        return client.post("/analytics/query", json={"question": question}, headers=_headers(token))
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


def _extract_csv_from_prompt(system_prompt: str) -> str:
    marker = "CASE DATA (CSV):\n"
    start = system_prompt.index(marker) + len(marker)
    end = system_prompt.index("\n\nRules —")
    return system_prompt[start:end]


@pytest.fixture
def mocked_ai():
    fake = _fake_client_returning_chart(
        {"title": "Cases by severity", "chart_type": "bar", "data": [{"label": "Critical", "value": 5}]}
    )
    app.dependency_overrides[get_anthropic_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_anthropic_client, None)


def test_analytics_csv_excludes_pii_and_spans_all_runs(client, default_token, mocked_ai):
    run_a = client.post("/analysis/run", json={}, headers=_headers(default_token)).json()
    run_b = client.post("/analysis/run", json={}, headers=_headers(default_token)).json()
    cases_b = client.get(f"/cases?run_id={run_b['id']}&limit=200", headers=_headers(default_token)).json()

    resp = client.post(
        "/analytics/query", json={"question": "cases by severity"}, headers=_headers(default_token)
    )
    assert resp.status_code == 200, resp.text

    system_prompt = mocked_ai.messages.create.call_args.kwargs["system"]
    csv_text = _extract_csv_from_prompt(system_prompt)
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    run_ids_in_csv = {row["run_id"] for row in rows}
    assert str(run_a["id"]) in run_ids_in_csv
    assert str(run_b["id"]) in run_ids_in_csv

    for c in cases_b:
        assert c["case_ref"] not in system_prompt
        assert c["subject_id"] not in system_prompt
        assert c["subject_name"] not in system_prompt


def test_analytics_uses_sonnet_not_the_app_wide_opus_default(client, default_token, mocked_ai):
    resp = client.post("/analytics/query", json={"question": "cases by severity"}, headers=_headers(default_token))
    assert resp.status_code == 200, resp.text
    call_kwargs = mocked_ai.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-5"
    # Sonnet 5 defaults to adaptive thinking when `thinking` is omitted
    # (unlike Opus 4.8) - must be explicitly disabled here or switching
    # models silently reintroduces the latency this was meant to cut.
    assert call_kwargs["thinking"] == {"type": "disabled"}


def test_analytics_returns_valid_chart_from_code_execution(client, default_token):
    chart = {
        "title": "Average risk score for R001 cases",
        "chart_type": "bar",
        "data": [{"label": "R001", "value": 63.4}],
    }
    fake = _fake_client_returning_chart(chart)
    resp = _query_with_mock(client, default_token, fake, "average risk score for R001 cases")
    assert resp.status_code == 200, resp.text
    assert resp.json() == chart


def test_analytics_extracts_chart_after_exploratory_prints(client, default_token):
    # The system prompt explicitly allows Claude's code to print other
    # things before its FINAL print, as long as that final print is pure
    # JSON - e.g. a df.head() sanity check during exploration.
    chart = {"title": "Cases by severity", "chart_type": "bar", "data": [{"label": "Critical", "value": 5}]}
    stdout = "  severity\n0  Critical\n1  High\n" + json.dumps(chart)
    fake = MagicMock()
    fake.messages.create.return_value = MagicMock(content=[_bash_result_block(stdout)], stop_reason="end_turn")
    resp = _query_with_mock(client, default_token, fake)
    assert resp.status_code == 200, resp.text
    assert resp.json() == chart


def test_analytics_extracts_pretty_printed_multiline_json(client, default_token):
    chart = {"title": "Cases by severity", "chart_type": "bar", "data": [{"label": "Critical", "value": 5}]}
    stdout = json.dumps(chart, indent=2)
    fake = MagicMock()
    fake.messages.create.return_value = MagicMock(content=[_bash_result_block(stdout)], stop_reason="end_turn")
    resp = _query_with_mock(client, default_token, fake)
    assert resp.status_code == 200, resp.text
    assert resp.json() == chart


def test_analytics_502_when_no_code_execution_block(client, default_token):
    fake = MagicMock()
    fake.messages.create.return_value = MagicMock(
        content=[MagicMock(type="text", text="I can't help with that")], stop_reason="end_turn"
    )
    resp = _query_with_mock(client, default_token, fake)
    assert resp.status_code == 502


def test_analytics_502_when_stdout_is_malformed_json(client, default_token):
    fake = MagicMock()
    fake.messages.create.return_value = MagicMock(content=[_bash_result_block("not valid json")], stop_reason="end_turn")
    resp = _query_with_mock(client, default_token, fake)
    assert resp.status_code == 502


def test_analytics_502_when_chart_json_missing_required_keys(client, default_token):
    fake = _fake_client_returning_chart({"title": "x"})
    resp = _query_with_mock(client, default_token, fake)
    assert resp.status_code == 502


def test_analytics_502_when_chart_type_invalid(client, default_token):
    fake = _fake_client_returning_chart({"title": "x", "chart_type": "pie", "data": []})
    resp = _query_with_mock(client, default_token, fake)
    assert resp.status_code == 502


def test_analytics_no_cases_returns_empty_chart_without_calling_ai(client, other_tenant_token):
    fake = MagicMock()
    resp = _query_with_mock(client, other_tenant_token, fake, "cases by severity")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []
    fake.messages.create.assert_not_called()


def test_analytics_resubmits_on_pause_turn(client, default_token):
    chart = {"title": "Cases by status", "chart_type": "bar", "data": [{"label": "Open", "value": 3}]}
    first = MagicMock(content=[MagicMock(type="text", text="working")], stop_reason="pause_turn")
    second = MagicMock(content=[_bash_result_block(json.dumps(chart))], stop_reason="end_turn")
    fake = MagicMock()
    fake.messages.create.side_effect = [first, second]

    resp = _query_with_mock(client, default_token, fake, "cases by status")
    assert resp.status_code == 200, resp.text
    assert resp.json() == chart
    assert fake.messages.create.call_count == 2


def test_analytics_retries_fresh_with_concise_nudge_on_max_tokens(client, default_token):
    chart = {"title": "Cases by status", "chart_type": "bar", "data": [{"label": "Open", "value": 3}]}
    truncated = MagicMock(
        content=[MagicMock(type="text", text="I'll analyze..."), MagicMock(type="server_tool_use", input={})],
        stop_reason="max_tokens",
    )
    retried = MagicMock(content=[_bash_result_block(json.dumps(chart))], stop_reason="end_turn")
    fake = MagicMock()
    fake.messages.create.side_effect = [truncated, retried]

    resp = _query_with_mock(client, default_token, fake, "trend of Critical cases this month")
    assert resp.status_code == 200, resp.text
    assert resp.json() == chart
    assert fake.messages.create.call_count == 2
    retry_call = fake.messages.create.call_args_list[1]
    assert "ran out of output budget" in retry_call.kwargs["system"]
    assert len(retry_call.kwargs["messages"]) == 1  # fresh call, not a resumed partial turn


def test_analytics_502_with_clear_message_when_max_tokens_persists(client, default_token):
    truncated = MagicMock(content=[MagicMock(type="text", text="...")], stop_reason="max_tokens")
    fake = MagicMock()
    fake.messages.create.side_effect = [truncated, truncated]

    resp = _query_with_mock(client, default_token, fake, "trend of Critical cases this month")
    assert resp.status_code == 502
    assert "more specific" in resp.json()["detail"]


def test_analytics_503_when_key_unset(client, default_token, monkeypatch):
    app.dependency_overrides.pop(get_anthropic_client, None)
    monkeypatch.setattr("app.core.ai.ANTHROPIC_API_KEY", None)
    resp = client.post("/analytics/query", json={"question": "..."}, headers=_headers(default_token))
    assert resp.status_code == 503
