"""Lambda entrypoint for the jobs queue: one SQS record = one job."""

import json

from app.core.logging import logger
from app.jobs.execute import execute_job


@logger.inject_lambda_context
def handler(event, context):
    failures = []
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        try:
            execute_job(body["tenant_slug"], body["job_id"])
        except Exception:
            logger.exception("record failed", message_id=record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
