"""
Erasing a tenant removes everything it owned - table items, uploaded files,
Cognito accounts - and nothing anyone else owns. Only the worker's admin
task runs it, and only with the slug typed twice.
"""

from unittest.mock import MagicMock

import boto3
import pytest
from boto3.dynamodb.conditions import Key

from app import worker_handler
from app.core import datasets, tenants, users
from app.core.settings import get_settings
from app.db import repository as repo


def _context():
    return MagicMock(aws_request_id="r", function_name="worker", memory_limit_in_mb=512, invoked_function_arn="arn")


def _partition_size(slug: str) -> int:
    return get_table_count(slug)


def get_table_count(slug: str) -> int:
    response = repo.get_table().query(KeyConditionExpression=Key("PK").eq(repo.tenant_pk(slug)), Select="COUNT")
    return response["Count"]


def test_erasure_removes_every_item_file_and_login_of_one_tenant_only(client, headers, provision_tenant, run_demo_analysis, default_case_ids):
    token = provision_tenant("erase-me", "Erase Me SACCO")
    run_demo_analysis(token)
    dataset, _ = datasets.create_dataset("erase-me")
    datasets.store_local_file("erase-me", dataset["dataset_id"], "members.csv", b"member_id,name\n")
    local_dir = get_settings().uploads_dir / "erase-me"
    assert local_dir.is_dir()
    assert _partition_size("erase-me") > 90  # tenant, admin, run, job, 91 cases, dataset
    default_before = _partition_size("default")

    result = tenants.erase_tenant("erase-me")

    assert result["users_deleted"] == 1
    assert result["datasets_deleted"] == 1
    assert result["items_deleted"] > 90
    assert repo.get_tenant("erase-me") is None
    assert _partition_size("erase-me") == 0
    assert repo.get_user_by_email("admin@erase-me.example") is None
    assert not local_dir.exists()
    # The erased admin's token no longer opens anything.
    assert client.get("/cases", headers=headers(token)).status_code in (401, 403, 404)
    # The neighbour is untouched.
    assert _partition_size("default") == default_before
    assert len(default_case_ids) > 0


def test_erasing_an_unknown_tenant_is_an_error_not_a_no_op():
    with pytest.raises(tenants.TenantNotFound):
        tenants.erase_tenant("never-existed")


@pytest.fixture
def s3_mode(monkeypatch):
    boto3.client("s3", region_name="eu-west-1").create_bucket(
        Bucket="audit-intelligence-erase-datasets", CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )
    monkeypatch.setenv("DATASET_STORE", "s3")
    monkeypatch.setenv("DATASETS_BUCKET", "audit-intelligence-erase-datasets")
    get_settings.cache_clear()
    datasets.reset_clients()
    yield boto3.client("s3", region_name="eu-west-1")
    get_settings.cache_clear()
    datasets.reset_clients()


def test_erasure_deletes_the_tenants_objects_without_listing_the_bucket(s3_mode, provision_tenant):
    s3 = s3_mode
    provision_tenant("erase-s3", "Erase S3 SACCO")
    provision_tenant("keep-s3", "Keep S3 SACCO")
    mine, _ = datasets.create_dataset("erase-s3")
    theirs, _ = datasets.create_dataset("keep-s3")
    for name in datasets.REQUIRED_FILES:
        s3.put_object(Bucket="audit-intelligence-erase-datasets", Key=f"tenants/erase-s3/datasets/{mine['dataset_id']}/{name}", Body=b"x")
        s3.put_object(Bucket="audit-intelligence-erase-datasets", Key=f"tenants/keep-s3/datasets/{theirs['dataset_id']}/{name}", Body=b"x")

    result = tenants.erase_tenant("erase-s3")

    assert result["datasets_deleted"] == 1
    remaining = [o["Key"] for o in s3.list_objects_v2(Bucket="audit-intelligence-erase-datasets").get("Contents", [])]
    assert remaining and all(key.startswith("tenants/keep-s3/") for key in remaining)
    assert len(remaining) == len(datasets.REQUIRED_FILES)


@pytest.fixture
def cognito_mode(monkeypatch):
    client = boto3.client("cognito-idp", region_name="eu-west-1")
    pool_id = client.create_user_pool(
        PoolName="audit-intelligence-erase",
        Schema=[{"Name": "tenant", "AttributeDataType": "String", "Mutable": True}],
    )["UserPool"]["Id"]
    for group in ("admin", "auditor"):
        client.create_group(UserPoolId=pool_id, GroupName=group)
    monkeypatch.setenv("AUTH_MODE", "cognito")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", pool_id)
    monkeypatch.setenv("COGNITO_CLIENT_ID", "client")
    get_settings.cache_clear()
    users.reset_clients()
    yield client, pool_id
    get_settings.cache_clear()
    users.reset_clients()


def test_erasure_deletes_the_cognito_accounts_including_disabled_ones(cognito_mode):
    client, pool_id = cognito_mode
    repo.create_tenant("erase-cognito", "Erase Cognito SACCO")
    repo.create_tenant("keep-cognito", "Keep Cognito SACCO")
    active, _ = users.create_user("erase-cognito", email="active@erase.example", name="Active", role="admin")
    disabled, _ = users.create_user("erase-cognito", email="disabled@erase.example", name="Disabled", role="auditor")
    users.update_user("erase-cognito", disabled["user_id"], is_active=False)
    users.create_user("keep-cognito", email="neighbour@keep.example", name="Neighbour", role="admin")

    result = tenants.erase_tenant("erase-cognito")

    assert result["users_deleted"] == 2
    for email in ("active@erase.example", "disabled@erase.example"):
        with pytest.raises(client.exceptions.UserNotFoundException):
            client.admin_get_user(UserPoolId=pool_id, Username=email)
    assert client.admin_get_user(UserPoolId=pool_id, Username="neighbour@keep.example")["Enabled"] is True
    assert repo.get_tenant("keep-cognito") is not None


def test_worker_admin_task_needs_the_slug_typed_twice(provision_tenant):
    provision_tenant("erase-worker", "Erase Worker SACCO")

    refused = worker_handler.handler({"admin_task": "delete_tenant", "slug": "erase-worker", "confirm": "erase-worke"}, _context())
    assert refused["ok"] is False
    assert "confirm" in refused["error"]
    assert repo.get_tenant("erase-worker") is not None

    missing = worker_handler.handler({"admin_task": "delete_tenant", "slug": "erase-worker"}, _context())
    assert missing["ok"] is False

    done = worker_handler.handler({"admin_task": "delete_tenant", "slug": "erase-worker", "confirm": "erase-worker"}, _context())
    assert done["ok"] is True
    assert done["slug"] == "erase-worker"
    assert done["users_deleted"] == 1
    assert repo.get_tenant("erase-worker") is None

    unknown = worker_handler.handler({"admin_task": "delete_tenant", "slug": "erase-worker", "confirm": "erase-worker"}, _context())
    assert unknown["ok"] is False
    assert "No tenant" in unknown["error"]
