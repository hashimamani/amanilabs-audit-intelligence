"""
The single DynamoDB table every record lives in, and its key schema.

Item shapes (all under one tenant partition so a route can never read
across tenants without constructing a different PK on purpose):

  PK=TENANT#<slug>  SK=META                      tenant
  PK=TENANT#<slug>  SK=USER#<user_id>            user (directory mirror; password hash in local auth mode only)
  PK=TENANT#<slug>  SK=RUN#<run_no:06d>          analysis run
  PK=TENANT#<slug>  SK=CASE#<case_ref>           case (full record)
  PK=TENANT#<slug>  SK=ACTIVITY#<case_ref>#<ts>  one auditor action on a case
  PK=TENANT#<slug>  SK=JOB#<job_id>              background job
  PK=TENANT#<slug>  SK=DATASET#<dataset_id>      uploaded dataset
  PK=TENANT#<slug>  SK=USAGE#ai#<yyyy-mm-dd>     paid AI calls that day (expired by TTL)

GSI1 serves the two lookups that are not by tenant partition order:
  cases of one run, highest risk first   GSI1PK=TENANT#<slug>#RUN#<run_no>  GSI1SK=RISK#<score>#<seq>
  user by email (local login)            GSI1PK=USER_EMAIL#<email>           GSI1SK=USER
It projects only the summary attributes a case list needs, so listing a run
never reads the flag/evidence blobs.

The CDK Data stack defines the same keys; infra/test asserts the names match.
"""

from functools import lru_cache

import boto3
from botocore.config import Config

from app.core.settings import get_settings

TABLE_KEYS = {"PK": "S", "SK": "S", "GSI1PK": "S", "GSI1SK": "S"}
GSI1_NAME = "GSI1"
# Epoch seconds; items carrying it are removed by DynamoDB once it passes.
# The CDK Data stack enables TTL on the same attribute; infra/test asserts it.
TTL_ATTRIBUTE = "ttl"
GSI1_PROJECTED = [
    "case_ref", "run_id", "subject_type", "subject_id", "subject_name", "risk_score",
    "severity", "status", "triggered_rules", "flag_count", "created_at", "updated_at",
    "user_id", "email", "name", "role", "is_active", "password_hash", "tenant_slug",
]


@lru_cache(maxsize=1)
def dynamodb_resource():
    settings = get_settings()
    kwargs = {"region_name": settings.aws_region, "config": Config(retries={"max_attempts": 5, "mode": "standard"})}
    if settings.dynamodb_endpoint:
        kwargs["endpoint_url"] = settings.dynamodb_endpoint
    return boto3.resource("dynamodb", **kwargs)


@lru_cache(maxsize=1)
def get_table():
    return dynamodb_resource().Table(get_settings().table_name)


def reset_clients() -> None:
    dynamodb_resource.cache_clear()
    get_table.cache_clear()


def create_table(resource, name: str):
    """Creates the table with the production key schema. Used by tests (moto)
    and by local startup against DynamoDB Local; real environments get the
    table from CDK."""
    table = resource.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": t} for k, t in TABLE_KEYS.items()],
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": GSI1_NAME,
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "INCLUDE", "NonKeyAttributes": GSI1_PROJECTED},
            }
        ],
    )
    table.wait_until_exists()
    resource.meta.client.update_time_to_live(
        TableName=name, TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTRIBUTE},
    )
    return table


def ensure_table_exists() -> None:
    resource = dynamodb_resource()
    name = get_settings().table_name
    existing = [t.name for t in resource.tables.all()]
    if name not in existing:
        create_table(resource, name)
