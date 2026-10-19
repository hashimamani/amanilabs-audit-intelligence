"""
Background jobs: anything that takes longer than an API gateway will wait
(a rule-engine run, a code-execution chart, a batched board report).

submit() records the job and hands it to the runner: inline runs it right
now in the same process (local dev, tests); sqs sends a message that the
worker Lambda picks up. The job record is the contract either way - the
client polls GET /jobs/{id} until status is succeeded or failed.
"""

import json
from functools import lru_cache

import boto3

from app.core.auth import Principal
from app.core.logging import logger
from app.core.settings import get_settings
from app.db import repository as repo

KINDS = ("analysis", "analytics", "report")
TERMINAL = ("succeeded", "failed")


class JobFailed(Exception):
    """A failure with a message safe to show the user."""


@lru_cache(maxsize=1)
def sqs_client():
    return boto3.client("sqs", region_name=get_settings().aws_region)


def reset_clients() -> None:
    sqs_client.cache_clear()


def submit(tenant_slug: str, user: Principal, *, kind: str, payload: dict) -> dict:
    job = repo.create_job(tenant_slug, kind=kind, payload=payload, created_by=user.email)
    dispatch(tenant_slug, job["job_id"])
    return repo.get_job(tenant_slug, job["job_id"])


def dispatch(tenant_slug: str, job_id: str) -> None:
    settings = get_settings()
    if settings.job_runner == "sqs":
        sqs_client().send_message(
            QueueUrl=settings.jobs_queue_url,
            MessageBody=json.dumps({"tenant_slug": tenant_slug, "job_id": job_id}),
        )
        return
    from app.jobs.execute import execute_job

    execute_job(tenant_slug, job_id)


def public_job(job: dict) -> dict:
    return {
        "id": job["job_id"], "kind": job["kind"], "status": job["status"], "result": job.get("result"),
        "error": job.get("error"), "created_at": job["created_at"], "updated_at": job["updated_at"],
    }


def log_job(job: dict, message: str) -> None:
    logger.info(message, job_id=job["job_id"], kind=job["kind"], status=job["status"])
