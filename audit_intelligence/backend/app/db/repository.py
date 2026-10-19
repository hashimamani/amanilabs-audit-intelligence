"""
Every read and write against the table. Routes and jobs call these
functions and never build a key themselves, so the tenant partition is
always part of the key and a cross-tenant read cannot be written by
accident. See db/table.py for the item shapes.
"""

import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from app.db.table import GSI1_NAME, get_table

CASE_SUMMARY_FIELDS = (
    "case_ref", "run_id", "subject_type", "subject_id", "subject_name", "risk_score",
    "severity", "status", "triggered_rules", "flag_count", "created_at", "updated_at",
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    """Time-prefixed so items created later sort later; random suffix so two
    in the same millisecond cannot collide."""
    return f"{int(time.time() * 1000):013d}{secrets.token_hex(4)}"


def _to_dynamo(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


def _strip_keys(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in ("PK", "SK", "GSI1PK", "GSI1SK")}


def _query_all(**kwargs) -> list[dict]:
    table = get_table()
    items: list[dict] = []
    response = table.query(**kwargs)
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.query(ExclusiveStartKey=response["LastEvaluatedKey"], **kwargs)
        items.extend(response.get("Items", []))
    return [_from_dynamo(_strip_keys(i)) for i in items]


def tenant_pk(slug: str) -> str:
    return f"TENANT#{slug}"


# --- tenants ---------------------------------------------------------------

@dataclass(frozen=True)
class Tenant:
    slug: str
    name: str


def get_tenant(slug: str) -> Tenant | None:
    item = get_table().get_item(Key={"PK": tenant_pk(slug), "SK": "META"}).get("Item")
    return Tenant(slug=item["slug"], name=item["name"]) if item else None


def create_tenant(slug: str, name: str) -> Tenant:
    try:
        get_table().put_item(
            Item={"PK": tenant_pk(slug), "SK": "META", "slug": slug, "name": name,
                  "created_at": utcnow_iso(), "run_counter": 0},
            ConditionExpression="attribute_not_exists(PK)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ValueError(f"Tenant slug '{slug}' already exists") from e
        raise
    return Tenant(slug=slug, name=name)


def next_run_number(slug: str) -> int:
    response = get_table().update_item(
        Key={"PK": tenant_pk(slug), "SK": "META"},
        UpdateExpression="ADD run_counter :one",
        ExpressionAttributeValues={":one": 1},
        ConditionExpression="attribute_exists(PK)",
        ReturnValues="UPDATED_NEW",
    )
    return int(response["Attributes"]["run_counter"])


# --- users -----------------------------------------------------------------

def _user_sk(user_id: str) -> str:
    return f"USER#{user_id}"


def put_user(slug: str, user: dict) -> dict:
    item = {
        "PK": tenant_pk(slug), "SK": _user_sk(user["user_id"]),
        "GSI1PK": f"USER_EMAIL#{user['email'].lower()}", "GSI1SK": "USER",
        "tenant_slug": slug, "created_at": user.get("created_at") or utcnow_iso(),
        **user,
    }
    get_table().put_item(Item=_to_dynamo(item))
    return _from_dynamo(_strip_keys(item))


def get_user(slug: str, user_id: str) -> dict | None:
    item = get_table().get_item(Key={"PK": tenant_pk(slug), "SK": _user_sk(user_id)}).get("Item")
    return _from_dynamo(_strip_keys(item)) if item else None


def get_user_by_email(email: str) -> dict | None:
    items = _query_all(
        IndexName=GSI1_NAME,
        KeyConditionExpression=Key("GSI1PK").eq(f"USER_EMAIL#{email.lower()}") & Key("GSI1SK").eq("USER"),
    )
    if not items:
        return None
    # The index projects the summary; the full item carries the same fields
    # for users, so this is only a defensive re-read.
    return get_user(items[0]["tenant_slug"], items[0]["user_id"])


def list_users(slug: str) -> list[dict]:
    items = _query_all(KeyConditionExpression=Key("PK").eq(tenant_pk(slug)) & Key("SK").begins_with("USER#"))
    return sorted(items, key=lambda u: u.get("created_at", ""))


def update_user(slug: str, user_id: str, **fields) -> dict | None:
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        return get_user(slug, user_id)
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": _to_dynamo(v) for k, v in fields.items()}
    try:
        response = get_table().update_item(
            Key={"PK": tenant_pk(slug), "SK": _user_sk(user_id)},
            UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(PK)",
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise
    return _from_dynamo(_strip_keys(response["Attributes"]))


# --- analysis runs ---------------------------------------------------------

def _run_sk(run_id: int) -> str:
    return f"RUN#{run_id:06d}"


def create_run(slug: str, dataset_id: str, job_id: str | None = None) -> dict:
    run_id = next_run_number(slug)
    item = {
        "PK": tenant_pk(slug), "SK": _run_sk(run_id),
        "run_id": run_id, "dataset_id": dataset_id, "status": "queued", "job_id": job_id,
        "created_at": utcnow_iso(), "flag_count": 0, "case_count": 0,
        "severity_counts": {}, "rule_counts": {}, "error": None, "completed_at": None,
    }
    get_table().put_item(Item=item)
    return _strip_keys(item)


def get_run(slug: str, run_id: int) -> dict | None:
    item = get_table().get_item(Key={"PK": tenant_pk(slug), "SK": _run_sk(run_id)}).get("Item")
    return _from_dynamo(_strip_keys(item)) if item else None


def list_runs(slug: str) -> list[dict]:
    return _query_all(
        KeyConditionExpression=Key("PK").eq(tenant_pk(slug)) & Key("SK").begins_with("RUN#"),
        ScanIndexForward=False,
    )


def latest_run(slug: str, succeeded_only: bool = True) -> dict | None:
    kwargs = dict(
        KeyConditionExpression=Key("PK").eq(tenant_pk(slug)) & Key("SK").begins_with("RUN#"),
        ScanIndexForward=False,
    )
    if succeeded_only:
        kwargs["FilterExpression"] = Attr("status").eq("succeeded")
    runs = _query_all(**kwargs)
    return runs[0] if runs else None


def update_run(slug: str, run_id: int, **fields) -> dict:
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": _to_dynamo(v) for k, v in fields.items()}
    response = get_table().update_item(
        Key={"PK": tenant_pk(slug), "SK": _run_sk(run_id)},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return _from_dynamo(_strip_keys(response["Attributes"]))


# --- cases -----------------------------------------------------------------

def _case_sk(case_ref: str) -> str:
    return f"CASE#{case_ref}"


def _run_gsi_pk(slug: str, run_id: int) -> str:
    return f"{tenant_pk(slug)}#{_run_sk(run_id)}"


def _risk_sk(score: float, seq: int) -> str:
    # Queried descending; the inverted sequence keeps the builder's order
    # (lowest sequence first) among cases with the same score.
    return f"RISK#{int(round(score * 10)):05d}#{9999 - seq:04d}"


def put_cases(slug: str, run_id: int, cases: list[dict]) -> list[dict]:
    """cases are the builder's Case.to_dict() output in builder order
    (highest risk first). case_ref is assigned here: it has to be unique
    across a tenant's runs, which the builder (one run at a time) cannot know."""
    now = utcnow_iso()
    stored = []
    with get_table().batch_writer() as batch:
        for seq, case in enumerate(cases, start=1):
            case_ref = f"CASE-{run_id:04d}-{seq:04d}"
            item = {
                **{k: v for k, v in case.items() if k != "case_id"},
                "PK": tenant_pk(slug), "SK": _case_sk(case_ref),
                "GSI1PK": _run_gsi_pk(slug, run_id), "GSI1SK": _risk_sk(case["risk_score"], seq),
                "case_ref": case_ref, "run_id": run_id, "flag_count": len(case["flags"]),
                "created_at": now, "updated_at": now,
            }
            batch.put_item(Item=_to_dynamo(item))
            stored.append(_strip_keys(item))
    return stored


def get_case(slug: str, case_ref: str) -> dict | None:
    item = get_table().get_item(Key={"PK": tenant_pk(slug), "SK": _case_sk(case_ref)}).get("Item")
    return _from_dynamo(_strip_keys(item)) if item else None


def get_cases(slug: str, case_refs: list[str]) -> list[dict]:
    found = [c for c in (get_case(slug, ref) for ref in case_refs) if c is not None]
    return sorted(found, key=lambda c: -c["risk_score"])


def list_case_summaries(
    slug: str, run_id: int, *, status: str | None = None, severity: str | None = None,
    min_risk: float | None = None, severities: list[str] | None = None,
) -> list[dict]:
    """Highest risk first, from the summary-only index."""
    filters = []
    if status:
        filters.append(Attr("status").eq(status))
    if severity:
        filters.append(Attr("severity").eq(severity))
    if severities:
        filters.append(Attr("severity").is_in(severities))
    if min_risk is not None:
        filters.append(Attr("risk_score").gte(Decimal(str(min_risk))))
    kwargs = dict(
        IndexName=GSI1_NAME,
        KeyConditionExpression=Key("GSI1PK").eq(_run_gsi_pk(slug, run_id)),
        ScanIndexForward=False,
    )
    if filters:
        combined = filters[0]
        for f in filters[1:]:
            combined = combined & f
        kwargs["FilterExpression"] = combined
    return _query_all(**kwargs)


def list_case_analytics_rows(slug: str) -> list[dict]:
    """Every case the tenant has, across all runs, reduced to the columns the
    analytics sandbox is allowed to see - no case_ref, subject id or name."""
    return _query_all(
        KeyConditionExpression=Key("PK").eq(tenant_pk(slug)) & Key("SK").begins_with("CASE#"),
        ProjectionExpression="run_id, severity, #s, subject_type, triggered_rules, risk_score, created_at",
        ExpressionAttributeNames={"#s": "status"},
    )


def update_case(slug: str, case_ref: str, *, status=None, assigned_auditor=None, outcome=None, add_note=None) -> dict | None:
    sets, names, values = ["#updated_at = :updated_at"], {"#updated_at": "updated_at"}, {":updated_at": utcnow_iso()}
    for field, value in (("status", status), ("assigned_auditor", assigned_auditor), ("outcome", outcome)):
        if value is not None:
            sets.append(f"#{field} = :{field}")
            names[f"#{field}"] = field
            values[f":{field}"] = value
    if add_note is not None:
        sets.append("#notes = list_append(if_not_exists(#notes, :empty), :note)")
        names["#notes"] = "notes"
        values[":empty"] = []
        values[":note"] = [add_note]
    try:
        response = get_table().update_item(
            Key={"PK": tenant_pk(slug), "SK": _case_sk(case_ref)},
            UpdateExpression="SET " + ", ".join(sets),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(PK)",
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise
    return _from_dynamo(_strip_keys(response["Attributes"]))


def bulk_update_status(slug: str, case_refs: list[str], status: str) -> int:
    updated = 0
    for ref in case_refs:
        if update_case(slug, ref, status=status) is not None:
            updated += 1
    return updated


# --- case activity ---------------------------------------------------------

def add_activity(slug: str, case_ref: str, *, actor_email: str, actor_name: str, action: str, detail: dict | None = None) -> dict:
    at = utcnow_iso()
    item = {
        "PK": tenant_pk(slug), "SK": f"ACTIVITY#{case_ref}#{at}#{secrets.token_hex(3)}",
        "case_ref": case_ref, "at": at, "actor_email": actor_email, "actor_name": actor_name,
        "action": action, "detail": detail or {},
    }
    get_table().put_item(Item=_to_dynamo(item))
    return _strip_keys(item)


def list_activity(slug: str, case_ref: str) -> list[dict]:
    return _query_all(
        KeyConditionExpression=Key("PK").eq(tenant_pk(slug)) & Key("SK").begins_with(f"ACTIVITY#{case_ref}#"),
        ScanIndexForward=False,
    )


# --- jobs ------------------------------------------------------------------

def create_job(slug: str, *, kind: str, payload: dict, created_by: str) -> dict:
    now = utcnow_iso()
    item = {
        "PK": tenant_pk(slug), "SK": f"JOB#{new_id()}",
        "kind": kind, "status": "queued", "payload": payload, "result": None, "error": None,
        "created_by": created_by, "created_at": now, "updated_at": now,
    }
    item["job_id"] = item["SK"].removeprefix("JOB#")
    get_table().put_item(Item=_to_dynamo(item))
    return _from_dynamo(_strip_keys(item))


def get_job(slug: str, job_id: str) -> dict | None:
    item = get_table().get_item(Key={"PK": tenant_pk(slug), "SK": f"JOB#{job_id}"}).get("Item")
    return _from_dynamo(_strip_keys(item)) if item else None


def update_job(slug: str, job_id: str, **fields) -> dict:
    fields["updated_at"] = utcnow_iso()
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": _to_dynamo(v) for k, v in fields.items()}
    response = get_table().update_item(
        Key={"PK": tenant_pk(slug), "SK": f"JOB#{job_id}"},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return _from_dynamo(_strip_keys(response["Attributes"]))


# --- datasets --------------------------------------------------------------

def put_dataset(slug: str, dataset: dict) -> dict:
    item = {"PK": tenant_pk(slug), "SK": f"DATASET#{dataset['dataset_id']}", **dataset}
    get_table().put_item(Item=_to_dynamo(item))
    return _from_dynamo(_strip_keys(item))


def get_dataset(slug: str, dataset_id: str) -> dict | None:
    item = get_table().get_item(Key={"PK": tenant_pk(slug), "SK": f"DATASET#{dataset_id}"}).get("Item")
    return _from_dynamo(_strip_keys(item)) if item else None


def list_datasets(slug: str) -> list[dict]:
    return _query_all(
        KeyConditionExpression=Key("PK").eq(tenant_pk(slug)) & Key("SK").begins_with("DATASET#"),
        ScanIndexForward=False,
    )
