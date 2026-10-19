"""The job record and the two runners: inline and SQS-to-worker."""

import json
from unittest.mock import MagicMock

import boto3
import pytest

from app import worker_handler
from app.core.auth import Principal
from app.core.settings import get_settings
from app.db import repository as repo
from app.jobs import execute, service
from conftest import fake_ai_client

USER = Principal(user_id="u1", email="jobs@default.local", name="Jobs", tenant_slug="default", role="admin")


def test_crashing_handler_marks_job_failed_with_generic_error(monkeypatch, default_case_ids):
    def boom(tenant_slug, job):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("app.jobs.report.run_report_job", boom)
    job = service.submit("default", USER, kind="report", payload={"case_ids": None})
    assert job["status"] == "failed"
    assert "secret internal detail" not in job["error"]
    assert "unexpectedly" in job["error"]


def test_finished_jobs_are_not_re_executed(mock_ai, default_case_ids):
    fake = mock_ai(fake_ai_client("report"))
    job = service.submit("default", USER, kind="report", payload={"case_ids": None})
    assert job["status"] == "succeeded"
    execute.execute_job("default", job["job_id"])
    assert fake.messages.create.call_count == 1


def test_job_is_visible_only_to_its_tenant(client, default_token, headers, provision_tenant, mock_ai):
    mock_ai(fake_ai_client("report"))
    job = service.submit("default", USER, kind="report", payload={"case_ids": None})
    assert client.get(f"/jobs/{job['job_id']}", headers=headers(default_token)).status_code == 200
    other = provision_tenant("jobs-other", "Other")
    assert client.get(f"/jobs/{job['job_id']}", headers=headers(other)).status_code == 404


@pytest.fixture
def sqs_mode(monkeypatch):
    queue_url = boto3.client("sqs", region_name="eu-west-1").create_queue(QueueName="audit-intelligence-test-jobs")["QueueUrl"]
    monkeypatch.setenv("JOB_RUNNER", "sqs")
    monkeypatch.setenv("JOBS_QUEUE_URL", queue_url)
    get_settings.cache_clear()
    service.reset_clients()
    yield queue_url
    get_settings.cache_clear()
    service.reset_clients()


def test_sqs_runner_enqueues_and_worker_executes(sqs_mode, mock_ai, default_case_ids):
    mock_ai(fake_ai_client("report via worker"))
    job = service.submit("default", USER, kind="report", payload={"case_ids": None})
    assert job["status"] == "queued"

    sqs = boto3.client("sqs", region_name="eu-west-1")
    messages = sqs.receive_message(QueueUrl=sqs_mode, MaxNumberOfMessages=10)["Messages"]
    assert [json.loads(m["Body"]) for m in messages] == [{"tenant_slug": "default", "job_id": job["job_id"]}]

    event = {"Records": [{"messageId": "m1", "body": messages[0]["Body"]}]}
    result = worker_handler.handler(event, MagicMock(aws_request_id="r1", function_name="worker", memory_limit_in_mb=512, invoked_function_arn="arn"))
    assert result == {"batchItemFailures": []}
    assert repo.get_job("default", job["job_id"])["status"] == "succeeded"
    assert repo.get_job("default", job["job_id"])["result"]["report_text"] == "report via worker"


def test_worker_reports_partial_batch_failures(sqs_mode, monkeypatch):
    monkeypatch.setattr(execute, "execute_job", lambda slug, job_id: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(worker_handler, "execute_job", execute.execute_job)
    event = {"Records": [{"messageId": "bad", "body": json.dumps({"tenant_slug": "default", "job_id": "x"})}]}
    result = worker_handler.handler(event, MagicMock(aws_request_id="r2", function_name="worker", memory_limit_in_mb=512, invoked_function_arn="arn"))
    assert result == {"batchItemFailures": [{"itemIdentifier": "bad"}]}


def test_analysis_run_failure_is_recorded_on_the_run(client, default_token, headers, monkeypatch):
    monkeypatch.setattr("app.jobs.analysis.RuleEngine.run", lambda self, dataset: (_ for _ in ()).throw(ValueError("bad csv")))
    resp = client.post("/analysis/run", json={}, headers=headers(default_token))
    assert resp.status_code == 202
    run = resp.json()
    assert run["status"] == "failed"
    assert "ValueError: bad csv" in run["error"]
    job = client.get(f"/jobs/{run['job_id']}", headers=headers(default_token)).json()
    assert job["status"] == "failed"
    # A failed run never becomes "the latest run" for listings.
    cases = client.get("/cases", headers=headers(default_token)).json()
    assert all(c["run_id"] != run["id"] for c in cases)
