"""Case listing, updates, bulk status, and the activity trail."""


def test_cases_list_highest_risk_first_and_filters(client, default_token, headers, default_case_ids):
    cases = client.get("/cases?limit=200", headers=headers(default_token)).json()
    scores = [c["risk_score"] for c in cases]
    assert scores == sorted(scores, reverse=True)
    assert all(c["id"] == c["case_ref"] for c in cases)

    critical = client.get("/cases?severity=Critical&limit=200", headers=headers(default_token)).json()
    assert critical and all(c["severity"] == "Critical" for c in critical)
    high_risk = client.get("/cases?min_risk=90&limit=200", headers=headers(default_token)).json()
    assert high_risk and all(c["risk_score"] >= 90 for c in high_risk)
    page = client.get("/cases?limit=5&offset=5", headers=headers(default_token)).json()
    assert [c["id"] for c in page] == [c["id"] for c in cases[5:10]]


def test_case_detail_has_flags_evidence_and_timeline(client, default_token, headers, default_case_ids):
    row = client.get(f"/cases/{default_case_ids[0]}", headers=headers(default_token)).json()
    assert row["flags"] and row["evidence"] and row["timeline"]
    assert row["flags"][0]["evidence"][0]["label"]
    assert row["notes"] == []


def test_update_case_records_activity(client, default_token, headers, default_case_ids):
    case_id = default_case_ids[1]
    resp = client.patch(f"/cases/{case_id}", json={"status": "In Progress"}, headers=headers(default_token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "In Progress"

    client.patch(f"/cases/{case_id}", json={"assigned_auditor": "Jane", "outcome": "Confirmed"}, headers=headers(default_token))
    client.patch(f"/cases/{case_id}", json={"add_note": "called the member"}, headers=headers(default_token))
    client.patch(f"/cases/{case_id}", json={"add_note": "second note"}, headers=headers(default_token))

    row = client.get(f"/cases/{case_id}", headers=headers(default_token)).json()
    assert row["notes"] == ["called the member", "second note"]
    assert row["assigned_auditor"] == "Jane"

    activity = client.get(f"/cases/{case_id}/activity", headers=headers(default_token)).json()
    actions = [a["action"] for a in activity]
    assert actions == ["note_added", "note_added", "outcome_set", "assigned", "status_changed"]
    assert activity[-1]["detail"] == {"from": "Open", "to": "In Progress"}
    assert activity[0]["actor_email"] == "admin@default.local"


def test_unchanged_status_adds_no_activity(client, default_token, headers, default_case_ids):
    case_id = default_case_ids[2]
    client.patch(f"/cases/{case_id}", json={"status": "Open"}, headers=headers(default_token))
    assert client.get(f"/cases/{case_id}/activity", headers=headers(default_token)).json() == []


def test_bulk_update_changes_only_the_given_cases(client, default_token, headers, default_case_ids):
    target_ids = default_case_ids[3:6]
    untouched_id = default_case_ids[6]

    resp = client.patch("/cases/bulk-status", json={"case_ids": target_ids, "status": "Closed"}, headers=headers(default_token))
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 3
    for case_id in target_ids:
        assert client.get(f"/cases/{case_id}", headers=headers(default_token)).json()["status"] == "Closed"
        activity = client.get(f"/cases/{case_id}/activity", headers=headers(default_token)).json()
        assert activity[0]["detail"]["bulk"] is True
    assert client.get(f"/cases/{untouched_id}", headers=headers(default_token)).json()["status"] != "Closed"


def test_bulk_update_ignores_another_tenants_case_ids(client, default_token, headers, default_case_ids, provision_tenant):
    other_token = provision_tenant("bulk-test-other", "Other Tenant")
    foreign_case_id = default_case_ids[7]
    resp = client.patch("/cases/bulk-status", json={"case_ids": [foreign_case_id], "status": "In Progress"}, headers=headers(other_token))
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 0
    assert client.get(f"/cases/{foreign_case_id}", headers=headers(default_token)).json()["status"] != "In Progress"


def test_bulk_update_with_empty_ids_is_a_no_op(client, default_token, headers):
    resp = client.patch("/cases/bulk-status", json={"case_ids": [], "status": "Closed"}, headers=headers(default_token))
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 0
