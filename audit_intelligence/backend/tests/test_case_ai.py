"""
Case Q&A. The important assertion is that the grounding context handed to
the (fake) client really contains the case's evidence - the code-level
enforcement of "never invent evidence".
"""

from conftest import fake_ai_client


def test_ask_404_for_missing_or_foreign_case(client, default_token, headers, default_case_ids, provision_tenant, mock_ai):
    fake = mock_ai(fake_ai_client("placeholder answer"))
    assert client.post("/cases/CASE-9999-9999/ask", json={"question": "?"}, headers=headers(default_token)).status_code == 404
    other_token = provision_tenant("case-ai-other", "Other Tenant")
    assert client.post(f"/cases/{default_case_ids[0]}/ask", json={"question": "?"}, headers=headers(other_token)).status_code == 404
    fake.messages.create.assert_not_called()


def test_ask_grounds_on_real_case_evidence(client, default_token, headers, default_case_ids, mock_ai):
    fake = mock_ai(fake_ai_client("placeholder answer"))
    case_id = default_case_ids[0]
    real_case = client.get(f"/cases/{case_id}", headers=headers(default_token)).json()

    resp = client.post(f"/cases/{case_id}/ask", json={"question": "what evidence supports this flag?"}, headers=headers(default_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["answer"] == "placeholder answer"

    system_prompt = fake.messages.create.call_args.kwargs["system"]
    for evidence_item in real_case["evidence"]:
        assert evidence_item["value"] in system_prompt
    for flag in real_case["flags"]:
        for evidence_item in flag["evidence"]:
            assert evidence_item["value"] in system_prompt


def test_ask_truncation_note_appended_on_max_tokens(client, default_token, headers, default_case_ids, mock_ai):
    mock_ai(fake_ai_client("partial answer", stop_reason="max_tokens"))
    resp = client.post(f"/cases/{default_case_ids[0]}/ask", json={"question": "..."}, headers=headers(default_token))
    assert resp.status_code == 200
    assert "truncated" in resp.json()["answer"].lower()


def test_ask_503_when_key_unset(client, default_token, headers, default_case_ids, monkeypatch):
    monkeypatch.setattr("app.core.ai.ANTHROPIC_API_KEY", None)
    resp = client.post(f"/cases/{default_case_ids[0]}/ask", json={"question": "..."}, headers=headers(default_token))
    assert resp.status_code == 503
