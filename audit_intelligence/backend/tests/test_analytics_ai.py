"""
"Ask for a chart" runs as a job. What this codebase controls, and what is
asserted: the CSV handed to the model (all runs, no identifying columns),
the model/thinking settings, the retry paths, and that the printed JSON's
structure is validated before it becomes a result.
"""

import csv
import io
import json
from unittest.mock import MagicMock


def _bash_result_block(stdout: str, return_code: int = 0):
    result_content = MagicMock(type="bash_code_execution_result", stdout=stdout, stderr="", return_code=return_code)
    return MagicMock(type="bash_code_execution_tool_result", content=result_content)


def _fake_client_returning_chart(chart: dict):
    fake = MagicMock()
    fake.messages.create.return_value = MagicMock(content=[_bash_result_block(json.dumps(chart))], stop_reason="end_turn")
    return fake


def _query(client, token, headers, question="..."):
    resp = client.post("/analytics/query", json={"question": question}, headers=headers(token))
    assert resp.status_code == 202, resp.text
    return resp.json()


def _extract_csv_from_prompt(system_prompt: str) -> str:
    marker = "CASE DATA (CSV):\n"
    start = system_prompt.index(marker) + len(marker)
    end = system_prompt.index("\n\nRules —")
    return system_prompt[start:end]


CHART = {"title": "Cases by severity", "chart_type": "bar", "data": [{"label": "Critical", "value": 5.0}]}


def test_analytics_csv_excludes_pii_and_spans_all_runs(client, default_token, headers, run_demo_analysis, mock_ai):
    fake = mock_ai(_fake_client_returning_chart(CHART))
    run_a = run_demo_analysis()
    run_b = run_demo_analysis()
    cases_b = client.get(f"/cases?run_id={run_b['id']}&limit=200", headers=headers(default_token)).json()

    job = _query(client, default_token, headers, "cases by severity")
    assert job["status"] == "succeeded", job
    assert job["result"] == CHART

    system_prompt = fake.messages.create.call_args.kwargs["system"]
    rows = list(csv.DictReader(io.StringIO(_extract_csv_from_prompt(system_prompt))))
    run_ids_in_csv = {row["run_id"] for row in rows}
    assert {str(run_a["id"]), str(run_b["id"])} <= run_ids_in_csv
    assert set(rows[0]) == {"run_id", "severity", "status", "subject_type", "triggered_rules", "risk_score", "created_at"}
    for c in cases_b:
        assert c["case_ref"] not in system_prompt
        assert c["subject_id"] not in system_prompt
        assert c["subject_name"] not in system_prompt


def test_analytics_uses_sonnet_with_thinking_disabled(client, default_token, headers, default_case_ids, mock_ai):
    fake = mock_ai(_fake_client_returning_chart(CHART))
    _query(client, default_token, headers)
    call_kwargs = fake.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-5"
    assert call_kwargs["thinking"] == {"type": "disabled"}
    assert call_kwargs["tools"][0]["type"] == "code_execution_20260120"


def test_analytics_extracts_chart_after_exploratory_prints_and_pretty_json(client, default_token, headers, default_case_ids, mock_ai):
    for stdout in ("  severity\n0  Critical\n1  High\n" + json.dumps(CHART), json.dumps(CHART, indent=2)):
        fake = MagicMock()
        fake.messages.create.return_value = MagicMock(content=[_bash_result_block(stdout)], stop_reason="end_turn")
        mock_ai(fake)
        job = _query(client, default_token, headers)
        assert job["status"] == "succeeded", job
        assert job["result"] == CHART


def test_analytics_fails_cleanly_on_invalid_model_output(client, default_token, headers, default_case_ids, mock_ai):
    bad_responses = [
        MagicMock(content=[MagicMock(type="text", text="I can't help with that")], stop_reason="end_turn"),
        MagicMock(content=[_bash_result_block("not valid json")], stop_reason="end_turn"),
        MagicMock(content=[_bash_result_block(json.dumps({"title": "x"}))], stop_reason="end_turn"),
        MagicMock(content=[_bash_result_block(json.dumps({"title": "x", "chart_type": "pie", "data": []}))], stop_reason="end_turn"),
    ]
    for response in bad_responses:
        fake = MagicMock()
        fake.messages.create.return_value = response
        mock_ai(fake)
        job = _query(client, default_token, headers)
        assert job["status"] == "failed"
        assert job["error"] == "AI did not return a valid chart"
        assert job["result"] is None


def test_analytics_no_cases_returns_empty_chart_without_calling_ai(client, headers, provision_tenant, mock_ai):
    fake = mock_ai(MagicMock())
    token = provision_tenant("analytics-empty", "Empty Tenant")
    job = _query(client, token, headers, "cases by severity")
    assert job["status"] == "succeeded"
    assert job["result"]["data"] == []
    fake.messages.create.assert_not_called()


def test_analytics_resubmits_on_pause_turn(client, default_token, headers, default_case_ids, mock_ai):
    first = MagicMock(content=[MagicMock(type="text", text="working")], stop_reason="pause_turn")
    second = MagicMock(content=[_bash_result_block(json.dumps(CHART))], stop_reason="end_turn")
    fake = MagicMock()
    fake.messages.create.side_effect = [first, second]
    mock_ai(fake)
    job = _query(client, default_token, headers, "cases by status")
    assert job["status"] == "succeeded"
    assert fake.messages.create.call_count == 2


def test_analytics_retries_fresh_with_concise_nudge_on_max_tokens(client, default_token, headers, default_case_ids, mock_ai):
    truncated = MagicMock(
        content=[MagicMock(type="text", text="I'll analyze..."), MagicMock(type="server_tool_use", input={})],
        stop_reason="max_tokens",
    )
    retried = MagicMock(content=[_bash_result_block(json.dumps(CHART))], stop_reason="end_turn")
    fake = MagicMock()
    fake.messages.create.side_effect = [truncated, retried]
    mock_ai(fake)

    job = _query(client, default_token, headers, "trend of Critical cases this month")
    assert job["status"] == "succeeded"
    assert fake.messages.create.call_count == 2
    retry_call = fake.messages.create.call_args_list[1]
    assert "ran out of output budget" in retry_call.kwargs["system"]
    assert len(retry_call.kwargs["messages"]) == 1


def test_analytics_clear_message_when_max_tokens_persists(client, default_token, headers, default_case_ids, mock_ai):
    truncated = MagicMock(content=[MagicMock(type="text", text="...")], stop_reason="max_tokens")
    fake = MagicMock()
    fake.messages.create.side_effect = [truncated, truncated]
    mock_ai(fake)
    job = _query(client, default_token, headers, "trend of Critical cases this month")
    assert job["status"] == "failed"
    assert "more specific" in job["error"]


def test_analytics_503_when_key_unset(client, default_token, headers, monkeypatch):
    monkeypatch.setattr("app.core.ai.ANTHROPIC_API_KEY", None)
    assert client.post("/analytics/query", json={"question": "..."}, headers=headers(default_token)).status_code == 503
