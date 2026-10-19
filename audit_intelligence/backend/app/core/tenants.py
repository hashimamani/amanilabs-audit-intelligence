"""
Erasing a tenant: the right-to-erasure path, and what a SACCO that stops
being a customer is owed.

Everything the platform holds for one tenant lives in three places, and
this removes all of them, in the order that leaves nothing orphaned if a
step fails part-way:

1. its users' Cognito accounts (so nobody can sign in while the rest goes);
2. its uploaded CSVs in the datasets bucket (the raw member data);
3. every item in its table partition, the tenant record last.

Only the worker runs this, from the delete-tenant workflow, which asks for
the slug to be typed twice; the API function cannot - its role is granted
neither AdminDeleteUser nor s3:DeleteObject on purpose.
"""

import shutil

from app.core import users
from app.core.datasets import REQUIRED_FILES, s3_client
from app.core.logging import logger
from app.core.settings import get_settings
from app.db import repository as repo


class TenantNotFound(Exception):
    pass


def _delete_cognito_users(tenant_slug: str) -> int:
    settings = get_settings()
    rows = repo.list_users(tenant_slug)
    if settings.auth_mode != "cognito":
        return len(rows)
    client = users.cognito_client()
    deleted = 0
    for row in rows:
        try:
            client.admin_user_global_sign_out(UserPoolId=settings.cognito_user_pool_id, Username=row["email"])
        except client.exceptions.UserNotFoundException:
            continue
        except client.exceptions.NotAuthorizedException:
            pass  # a disabled user cannot be signed out, and is about to be deleted anyway
        try:
            client.admin_delete_user(UserPoolId=settings.cognito_user_pool_id, Username=row["email"])
            deleted += 1
        except client.exceptions.UserNotFoundException:
            continue
    return deleted


def _delete_datasets(tenant_slug: str) -> int:
    """The keys are known without listing: every dataset item names its id and
    the files are the fixed export contract, so the worker needs
    s3:DeleteObject under the tenant prefix and no s3:ListBucket."""
    settings = get_settings()
    datasets = repo.list_datasets(tenant_slug)
    if settings.dataset_store == "s3":
        keys = [
            {"Key": f"tenants/{tenant_slug}/datasets/{d['dataset_id']}/{name}"}
            for d in datasets
            for name in REQUIRED_FILES
        ]
        for start in range(0, len(keys), 1000):
            s3_client().delete_objects(Bucket=settings.datasets_bucket, Delete={"Objects": keys[start:start + 1000], "Quiet": True})
    else:
        shutil.rmtree(settings.uploads_dir / tenant_slug, ignore_errors=True)
    return len(datasets)


def erase_tenant(tenant_slug: str) -> dict:
    """Removes the tenant and everything it owns. Returns what was removed."""
    tenant = repo.get_tenant(tenant_slug)
    if tenant is None:
        raise TenantNotFound(tenant_slug)
    users_deleted = _delete_cognito_users(tenant_slug)
    datasets_deleted = _delete_datasets(tenant_slug)
    items_deleted = repo.delete_tenant_items(tenant_slug)
    logger.info(
        "tenant erased", tenant_slug=tenant_slug, users=users_deleted, datasets=datasets_deleted, items=items_deleted,
    )
    return {
        "slug": tenant_slug, "name": tenant.name,
        "users_deleted": users_deleted, "datasets_deleted": datasets_deleted, "items_deleted": items_deleted,
    }
