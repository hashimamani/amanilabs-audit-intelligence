"""
Lambda entrypoint for the worker. Two kinds of invocation:

- an SQS batch from the jobs queue: one record = one job;
- a direct invocation carrying `admin_task`, from the provision-tenant and
  delete-tenant workflows, whose role may invoke this function and nothing
  else.
"""

import json

from app.core import tenants, users
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


def delete_tenant_task(event: dict) -> dict:
    """Erases a tenant. The slug must be repeated in `confirm`: the workflow
    checks that too, but this function is the last line and does not trust
    its caller to have done so."""
    slug = event.get("slug")
    if not slug or event.get("confirm") != slug:
        return {"ok": False, "error": "Refusing: `confirm` must repeat the tenant slug exactly"}
    try:
        result = tenants.erase_tenant(slug)
    except tenants.TenantNotFound:
        return {"ok": False, "error": f"No tenant with slug '{slug}'"}
    return {"ok": True, **result}


ADMIN_TASKS = {"create_tenant": create_tenant_task, "delete_tenant": delete_tenant_task}


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
