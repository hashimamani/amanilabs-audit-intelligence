"""
The user directory in Cognito mode, against moto's cognito-idp: creating a
user creates it in the pool, puts it in the role group, and mirrors it in
the table; role and active changes reach both.
"""

import boto3
import pytest

from app.core import users
from app.core.settings import get_settings
from app.db import repository as repo


@pytest.fixture
def pool(monkeypatch, client):
    client = boto3.client("cognito-idp", region_name="eu-west-1")
    pool_id = client.create_user_pool(
        PoolName="audit-intelligence-test",
        Schema=[{"Name": "tenant", "AttributeDataType": "String", "Mutable": True}],
    )["UserPool"]["Id"]
    for group in ("admin", "auditor"):
        client.create_group(UserPoolId=pool_id, GroupName=group)
    monkeypatch.setenv("AUTH_MODE", "cognito")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", pool_id)
    monkeypatch.setenv("COGNITO_CLIENT_ID", "client")
    get_settings.cache_clear()
    users.reset_clients()
    if repo.get_tenant("cognito-sacco") is None:
        repo.create_tenant("cognito-sacco", "Cognito SACCO")
    yield client, pool_id
    get_settings.cache_clear()
    users.reset_clients()


def _groups(client, pool_id, email):
    return [g["GroupName"] for g in client.admin_list_groups_for_user(UserPoolId=pool_id, Username=email)["Groups"]]


def test_create_user_lands_in_cognito_group_and_table(pool):
    client, pool_id = pool
    user, password = users.create_user("cognito-sacco", email="Jane@Example.com", name="Jane", role="auditor")

    assert password is None
    cognito_user = client.admin_get_user(UserPoolId=pool_id, Username="jane@example.com")
    attrs = {a["Name"]: a["Value"] for a in cognito_user["UserAttributes"]}
    assert attrs["custom:tenant"] == "cognito-sacco"
    assert attrs["sub"] == user["user_id"]
    assert _groups(client, pool_id, "jane@example.com") == ["auditor"]

    mirror = repo.get_user("cognito-sacco", user["user_id"])
    assert mirror["email"] == "jane@example.com"
    assert "password_hash" not in mirror


def test_role_change_moves_cognito_group(pool):
    client, pool_id = pool
    user, _ = users.create_user("cognito-sacco", email="bob@example.com", name="Bob", role="auditor")
    users.update_user("cognito-sacco", user["user_id"], role="admin")
    assert _groups(client, pool_id, "bob@example.com") == ["admin"]
    assert repo.get_user("cognito-sacco", user["user_id"])["role"] == "admin"


def test_deactivation_disables_the_cognito_user(pool):
    client, pool_id = pool
    user, _ = users.create_user("cognito-sacco", email="eve@example.com", name="Eve", role="auditor")
    users.update_user("cognito-sacco", user["user_id"], is_active=False)
    assert client.admin_get_user(UserPoolId=pool_id, Username="eve@example.com")["Enabled"] is False
    assert repo.get_user("cognito-sacco", user["user_id"])["is_active"] is False

    users.update_user("cognito-sacco", user["user_id"], is_active=True)
    assert client.admin_get_user(UserPoolId=pool_id, Username="eve@example.com")["Enabled"] is True


def test_duplicate_email_is_refused_before_touching_cognito(pool):
    users.create_user("cognito-sacco", email="cognito-dup@example.com", name="Dup", role="auditor")
    with pytest.raises(users.EmailInUse):
        users.create_user("cognito-sacco", email="COGNITO-DUP@example.com", name="Dup 2", role="admin")
