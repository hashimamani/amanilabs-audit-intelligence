"""
Zero-friction local start: the table, a demo tenant and a well-known dev
admin. Only ever runs in local mode - dev/prod tenants are provisioned
with app.scripts.create_tenant and users live in Cognito.
"""

from app.core import users
from app.core.auth import (
    DEFAULT_ADMIN_DEV_PASSWORD,
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_NAME,
    DEFAULT_TENANT_NAME,
    DEFAULT_TENANT_SLUG,
)
from app.core.settings import get_settings
from app.db import repository as repo
from app.db.table import ensure_table_exists


def bootstrap_local() -> None:
    settings = get_settings()
    if not settings.is_local:
        return
    ensure_table_exists()
    if repo.get_tenant(DEFAULT_TENANT_SLUG) is None:
        repo.create_tenant(DEFAULT_TENANT_SLUG, DEFAULT_TENANT_NAME)
    if settings.auth_mode == "local" and repo.get_user_by_email(DEFAULT_ADMIN_EMAIL) is None:
        users.create_user(
            DEFAULT_TENANT_SLUG, email=DEFAULT_ADMIN_EMAIL, name=DEFAULT_ADMIN_NAME, role="admin",
            password=DEFAULT_ADMIN_DEV_PASSWORD,
        )
