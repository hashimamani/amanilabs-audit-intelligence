"""Board report generator, as a job: grounding, selection rules, tenant scoping."""

from conftest import fake_ai_client


def _generate(client, token, headers, payload):
    resp = client.post("/reports/generate", json=payload, headers=headers(token))
    assert resp.status_code == 202, resp.text
    return resp.json()


def test_report_default_selection_is_critical_high_capped_at_20(client, default_token, headers, default_case_ids, mock_ai):
    fake = mock_ai(fake_ai_client("placeholder report"))
    job = _generate(client, default_token, headers, {})
    assert job["status"] == "succeeded", job
    assert job["result"]["case_count"] == 20
    assert job["result"]["report_text"] == "placeholder report"

    system_prompt = fake.messages.create.call_args.kwargs["system"]
    assert "Severity: Critical" in system_prompt or "Severity: High" in system_prompt
    assert "Severity: Medium" not in system_prompt
    assert "Severity: Low" not in system_prompt


def test_report_explicit_selection_grounds_on_real_evidence(client, default_token, headers, default_case_ids, mock_ai):
    fake = mock_ai(fake_ai_client("placeholder report"))
    target_ids = default_case_ids[:2]
    job = _generate(client, default_token, headers, {"case_ids": target_ids})
    assert job["result"]["case_count"] == 2

    system_prompt = fake.messages.create.call_args.kwargs["system"]
    for case_id in target_ids:
        case = client.get(f"/cases/{case_id}", headers=headers(default_token)).json()
        assert case["case_ref"] in system_prompt
        for e in case["evidence"]:
            assert e["value"] in system_prompt


def test_report_explicit_selection_excludes_foreign_tenant_case(client, headers, default_case_ids, provision_tenant, mock_ai):
    fake = mock_ai(fake_ai_client("placeholder report"))
    other_token = provision_tenant("reports-ai-other", "Other Tenant")
    job = _generate(client, other_token, headers, {"case_ids": [default_case_ids[0]]})
    assert job["status"] == "succeeded"
    assert job["result"]["case_count"] == 0
    fake.messages.create.assert_not_called()


def test_report_rejects_too_many_case_ids(client, default_token, headers, mock_ai):
    fake = mock_ai(fake_ai_client("placeholder report"))
    resp = client.post("/reports/generate", json={"case_ids": [f"CASE-{i:04d}" for i in range(51)]}, headers=headers(default_token))
    assert resp.status_code == 400
    fake.messages.create.assert_not_called()


def test_report_503_when_key_unset(client, default_token, headers, monkeypatch):
    monkeypatch.setattr("app.core.ai.ANTHROPIC_API_KEY", None)
    assert client.post("/reports/generate", json={}, headers=headers(default_token)).status_code == 503
