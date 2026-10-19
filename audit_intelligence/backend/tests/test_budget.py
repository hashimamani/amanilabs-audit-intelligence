"""The daily AI allowance: counted per tenant, enforced before any job is queued."""

import pytest
from conftest import fake_ai_client
from app.core import budget
from app.core.settings import get_settings
from app.db import repository as repo


@pytest.fixture
def daily_limit(monkeypatch):
    def _set(limit: int):
        monkeypatch.setenv("AI_DAILY_LIMIT", str(limit))
        get_settings.cache_clear()
    yield _set
    get_settings.cache_clear()


def test_ai_calls_count_against_the_tenant_and_stop_at_the_limit(client, headers, provision_tenant, mock_ai, daily_limit):
    daily_limit(3)
    fake = mock_ai(fake_ai_client("report"))
    token = provision_tenant("budget-sacco", "Budget SACCO")
    assert budget.ai_calls_today("budget-sacco") == 0

    for _ in range(3):
        assert client.post("/reports/generate", json={}, headers=headers(token)).status_code == 202
    assert budget.ai_calls_today("budget-sacco") == 3

    resp = client.post("/analytics/query", json={"question": "cases by severity"}, headers=headers(token))
    assert resp.status_code == 429
    assert "daily AI allowance" in resp.json()["detail"]
    assert budget.ai_calls_today("budget-sacco") == 3  # the refused call is not counted
    assert fake.messages.create.call_count == 0  # empty tenant: no cases, no model call either way


def test_budget_is_per_tenant(client, headers, provision_tenant, mock_ai, daily_limit):
    daily_limit(1)
    mock_ai(fake_ai_client("report"))
    a = provision_tenant("budget-a", "A")
    b = provision_tenant("budget-b", "B")
    assert client.post("/reports/generate", json={}, headers=headers(a)).status_code == 202
    assert client.post("/reports/generate", json={}, headers=headers(a)).status_code == 429
    assert client.post("/reports/generate", json={}, headers=headers(b)).status_code == 202


def test_unconfigured_ai_does_not_consume_the_allowance(client, headers, provision_tenant, daily_limit):
    """Without a key the route answers 503 (see core/ai.py); that must not
    eat into the day's allowance."""
    daily_limit(5)
    token = provision_tenant("budget-nokey", "No Key SACCO")
    resp = client.post("/reports/generate", json={}, headers=headers(token))
    assert resp.status_code == 503
    assert budget.ai_calls_today("budget-nokey") == 0


def test_counter_is_one_conditional_write(provision_tenant):
    """The check and the increment are the same DynamoDB call, so the limit
    cannot be overshot by concurrent requests; the counter item carries the
    TTL attribute so the table forgets old days by itself."""
    provision_tenant("budget-atomic", "Atomic SACCO")
    assert repo.increment_usage("budget-atomic", "ai#2026-01-01", expires_at=4102444800, limit=2) == 1
    assert repo.increment_usage("budget-atomic", "ai#2026-01-01", expires_at=4102444800, limit=2) == 2
    with pytest.raises(repo.UsageLimitReached):
        repo.increment_usage("budget-atomic", "ai#2026-01-01", expires_at=4102444800, limit=2)
    assert repo.get_usage("budget-atomic", "ai#2026-01-01") == 2

    item = repo.get_table().get_item(Key={"PK": "TENANT#budget-atomic", "SK": "USAGE#ai#2026-01-01"})["Item"]
    assert int(item["ttl"]) == 4102444800
    ttl = repo.get_table().meta.client.describe_time_to_live(TableName=repo.get_table().name)["TimeToLiveDescription"]
    assert ttl["AttributeName"] == "ttl"
    assert ttl["TimeToLiveStatus"] == "ENABLED"
