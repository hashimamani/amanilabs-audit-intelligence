"""
The user directory behind /users and tenant provisioning.

Cognito mode: Cognito is the authority for identity and passwords. Each
user also gets a mirror item in the table (same user_id as the Cognito
`sub`) so that listing a tenant's users is one query - Cognito cannot
filter ListUsers by a custom attribute - and so that deactivation is
visible to get_current_user immediately.

Local mode: the table item is the whole user, password hash included.
"""

import secrets
from functools import lru_cache

import boto3

from app.core.security import hash_password
from app.core.settings import get_settings
from app.db import repository as repo


class EmailInUse(Exception):
    pass


@lru_cache(maxsize=1)
def cognito_client():
    return boto3.client("cognito-idp", region_name=get_settings().aws_region)


def reset_clients() -> None:
    cognito_client.cache_clear()


def _public(user: dict) -> dict:
    return {k: v for k, v in user.items() if k != "password_hash"}


def list_users(tenant_slug: str) -> list[dict]:
    return [_public(u) for u in repo.list_users(tenant_slug)]


def create_user(tenant_slug: str, *, email: str, name: str, role: str, password: str | None = None) -> tuple[dict, str | None]:
    """Returns the user and, in local mode, the password that was set (the
    caller's, or a generated one). In Cognito mode the password is never
    seen by this code: Cognito emails a temporary one."""
    email = email.lower()
    if repo.get_user_by_email(email) is not None:
        raise EmailInUse(email)

    settings = get_settings()
    if settings.auth_mode == "cognito":
        client = cognito_client()
        response = client.admin_create_user(
            UserPoolId=settings.cognito_user_pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name", "Value": name},
                {"Name": "custom:tenant", "Value": tenant_slug},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )
        user_id = next(a["Value"] for a in response["User"]["Attributes"] if a["Name"] == "sub")
        client.admin_add_user_to_group(UserPoolId=settings.cognito_user_pool_id, Username=email, GroupName=role)
        user = repo.put_user(tenant_slug, {"user_id": user_id, "email": email, "name": name, "role": role, "is_active": True})
        return _public(user), None

    generated = password or secrets.token_urlsafe(16)
    user = repo.put_user(tenant_slug, {
        "user_id": secrets.token_hex(16), "email": email, "name": name, "role": role,
        "is_active": True, "password_hash": hash_password(generated),
    })
    return _public(user), generated


def update_user(tenant_slug: str, user_id: str, *, role: str | None = None, is_active: bool | None = None) -> dict | None:
    current = repo.get_user(tenant_slug, user_id)
    if current is None:
        return None

    settings = get_settings()
    if settings.auth_mode == "cognito":
        client = cognito_client()
        pool = settings.cognito_user_pool_id
        if role is not None and role != current["role"]:
            client.admin_remove_user_from_group(UserPoolId=pool, Username=current["email"], GroupName=current["role"])
            client.admin_add_user_to_group(UserPoolId=pool, Username=current["email"], GroupName=role)
        if is_active is not None and is_active != current.get("is_active", True):
            if is_active:
                client.admin_enable_user(UserPoolId=pool, Username=current["email"])
            else:
                client.admin_disable_user(UserPoolId=pool, Username=current["email"])
                client.admin_user_global_sign_out(UserPoolId=pool, Username=current["email"])

    updated = repo.update_user(tenant_slug, user_id, role=role, is_active=is_active)
    return _public(updated) if updated else None


def authenticate_local(email: str, password: str) -> dict | None:
    from app.core.security import verify_password

    user = repo.get_user_by_email(email)
    if user is None or not user.get("is_active", True) or not user.get("password_hash"):
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user
