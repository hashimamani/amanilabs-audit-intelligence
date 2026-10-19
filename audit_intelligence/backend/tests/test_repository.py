"""Key layout and value round-trips the routes rely on."""

from app.db import repository as repo


def test_floats_and_nested_blobs_round_trip():
    repo.create_tenant("repo-test", "Repo Test")
    run = repo.create_run("repo-test", "default")
    stored = repo.put_cases("repo-test", run["run_id"], [
        {"subject_type": "member", "subject_id": "M1", "subject_name": "A", "risk_score": 87.5, "severity": "High",
         "status": "Open", "triggered_rules": ["R001"], "flags": [{"rule_id": "R001", "evidence": [{"label": "x", "value": "1"}]}],
         "evidence": [], "timeline": [{"timestamp": None, "rule_id": "R001"}], "related_entities": {"members": ["M1"]},
         "recommended_actions": [], "assigned_auditor": None, "notes": [], "outcome": None, "ai_summary": None},
        {"subject_type": "member", "subject_id": "M2", "subject_name": "B", "risk_score": 100.0, "severity": "Critical",
         "status": "Open", "triggered_rules": ["R009"], "flags": [], "evidence": [], "timeline": [],
         "related_entities": {}, "recommended_actions": [], "assigned_auditor": None, "notes": [], "outcome": None, "ai_summary": None},
    ])
    assert [s["case_ref"] for s in stored] == ["CASE-0001-0001", "CASE-0001-0002"]

    case = repo.get_case("repo-test", "CASE-0001-0001")
    assert case["risk_score"] == 87.5 and isinstance(case["risk_score"], float)
    assert case["run_id"] == 1 and isinstance(case["run_id"], int)
    assert case["timeline"][0]["timestamp"] is None
    assert case["flags"][0]["evidence"][0]["value"] == "1"

    summaries = repo.list_case_summaries("repo-test", 1)
    assert [s["case_ref"] for s in summaries] == ["CASE-0001-0002", "CASE-0001-0001"]
    assert "flags" not in summaries[0]
    assert summaries[0]["flag_count"] == 0


def test_latest_run_skips_runs_that_did_not_succeed():
    repo.create_tenant("repo-latest", "Repo Latest")
    first = repo.create_run("repo-latest", "default")
    repo.update_run("repo-latest", first["run_id"], status="succeeded")
    repo.create_run("repo-latest", "default")  # queued, never finished
    assert repo.latest_run("repo-latest")["run_id"] == first["run_id"]
    assert repo.latest_run("repo-latest", succeeded_only=False)["run_id"] == first["run_id"] + 1
    assert [r["run_id"] for r in repo.list_runs("repo-latest")] == [2, 1]


def test_create_tenant_refuses_duplicates():
    repo.create_tenant("repo-dup", "Dup")
    try:
        repo.create_tenant("repo-dup", "Dup again")
    except ValueError as e:
        assert "already exists" in str(e)
    else:
        raise AssertionError("duplicate tenant slug was accepted")


def test_update_case_on_missing_case_returns_none():
    assert repo.update_case("repo-test", "CASE-9999-0001", status="Closed") is None
    assert repo.bulk_update_status("repo-test", ["CASE-9999-0001"], "Closed") == 0
