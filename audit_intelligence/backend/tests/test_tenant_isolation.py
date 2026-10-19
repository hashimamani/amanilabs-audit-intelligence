"""One tenant can never see another's runs or cases."""


def test_no_token_or_unknown_token_is_rejected(client, headers):
    assert client.get("/cases").status_code == 401
    assert client.get("/cases", headers=headers("not-a-real-token")).status_code == 401


def test_default_tenant_works_end_to_end(client, default_token, headers, run_demo_analysis):
    body = run_demo_analysis()
    assert body["case_count"] > 0
    assert body["flag_count"] > body["case_count"] // 2
    assert sum(body["severity_counts"].values()) == body["case_count"]
    assert body["rule_counts"]["R001"] >= 10

    resp = client.get("/cases", headers=headers(default_token))
    assert resp.status_code == 200
    assert len(resp.json()) > 0


def test_tenants_cannot_see_each_others_cases(client, headers, provision_tenant, run_demo_analysis):
    token_a = provision_tenant("tenant-a", "Tenant A SACCO")
    token_b = provision_tenant("tenant-b", "Tenant B SACCO")
    run_demo_analysis(token_a)

    assert client.get("/cases", headers=headers(token_b)).json() == []
    assert client.get("/analysis/runs", headers=headers(token_b)).json() == []
    cases_a = client.get("/cases", headers=headers(token_a)).json()
    assert len(cases_a) > 0

    case_id = cases_a[0]["id"]
    assert client.get(f"/cases/{case_id}", headers=headers(token_b)).status_code == 404
    assert client.get(f"/cases/{case_id}", headers=headers(token_a)).status_code == 200
    assert client.get(f"/cases/{case_id}/activity", headers=headers(token_b)).status_code == 404

    run_id = cases_a[0]["run_id"]
    assert client.get(f"/analysis/runs/{run_id}", headers=headers(token_b)).status_code == 404
    assert client.get(f"/cases?run_id={run_id}", headers=headers(token_b)).json() == []


def test_run_numbers_are_per_tenant(client, headers, provision_tenant, run_demo_analysis):
    token = provision_tenant("tenant-c", "Tenant C SACCO")
    first = run_demo_analysis(token)
    second = run_demo_analysis(token)
    assert (first["id"], second["id"]) == (1, 2)
    cases = client.get("/cases", headers=headers(token)).json()
    assert cases[0]["id"].startswith("CASE-0002-")
