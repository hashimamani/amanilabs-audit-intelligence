"""
Lambda entrypoint for the worker. Two kinds of invocation:

- an SQS batch from the jobs queue: one record = one job;
- a direct invocation carrying `admin_task`, from the provision-tenant
  workflow, whose role may invoke this function and nothing else.
"""

import json

from app.core import users
from app.core.logging import logger
from app.db import repository as repo
from app.jobs.execute import execute_job


def create_tenant_task(event: dict) -> dict:
    slug, name = event["slug"], event["name"]
    try:
        repo.create_tenant(slug, name)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        admin, password = users.create_user(slug, email=event["admin_email"], name=event["admin_name"], role="admin")
    except users.EmailInUse:
        return {"ok": False, "error": f"Email '{event['admin_email']}' is already in use"}
    logger.info("tenant provisioned", tenant_slug=slug, admin_email=admin["email"])
    result = {"ok": True, "slug": slug, "name": name, "admin_email": admin["email"]}
    if password:
        result["password"] = password
    return result


ADMIN_TASKS = {"create_tenant": create_tenant_task}


@logger.inject_lambda_context
def handler(event, context):
    task = event.get("admin_task") if isinstance(event, dict) else None
    if task is not None:
        if task not in ADMIN_TASKS:
            return {"ok": False, "error": f"Unknown admin task '{task}'"}
        return ADMIN_TASKS[task](event)

    failures = []
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        try:
            execute_job(body["tenant_slug"], body["job_id"])
        except Exception:
            logger.exception("record failed", message_id=record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
