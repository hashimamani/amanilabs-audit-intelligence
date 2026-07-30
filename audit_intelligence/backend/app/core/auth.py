"""
Individual login (email + password, JWT bearer token) replaces the old
shared X-Tenant-Key model entirely - a user belongs to exactly one
tenant, so logging in determines both identity and tenant. No RBAC
role/tenant is baked into the token itself; get_current_user always
re-reads the user row (see core/security.py's docstring for why).

DEFAULT_TENANT_DEV_KEY (docker-compose.yml, .env.example) no longer
exists - DEFAULT_ADMIN_DEV_PASSWORD is its replacement, same reasoning:
a stable, non-secret credential that only ever protects the bundled
synthetic demo data, so local dev / `docker compose up` stay
zero-friction without needing any manual account setup.
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token, hash_password
from app.db.models import TenantORM, UserORM

DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "Default / Demo"
DEFAULT_ADMIN_EMAIL = "admin@default.local"
DEFAULT_ADMIN_NAME = "Default Admin"
DEFAULT_ADMIN_DEV_PASSWORD = "local-dev-admin"


def ensure_default_tenant_and_admin(db: Session) -> None:
    tenant = db.query(TenantORM).filter(TenantORM.slug == DEFAULT_TENANT_SLUG).first()
    if tenant is None:
        tenant = TenantORM(slug=DEFAULT_TENANT_SLUG, name=DEFAULT_TENANT_NAME)
        db.add(tenant)
        db.flush()

    admin = db.query(UserORM).filter(UserORM.email == DEFAULT_ADMIN_EMAIL).first()
    if admin is None:
        admin = UserORM(
            tenant_id=tenant.id,
            email=DEFAULT_ADMIN_EMAIL,
            password_hash=hash_password(DEFAULT_ADMIN_DEV_PASSWORD),
            name=DEFAULT_ADMIN_NAME,
            role="admin",
        )
        db.add(admin)

    db.commit()


def get_current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> UserORM:
    user = None
    if authorization and authorization.startswith("Bearer "):
        user_id = decode_access_token(authorization.removeprefix("Bearer "))
        if user_id is not None:
            user = db.get(UserORM, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")
    return user


def get_current_tenant(user: UserORM = Depends(get_current_user)) -> TenantORM:
    return user.tenant


def require_admin(user: UserORM = Depends(get_current_user)) -> UserORM:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
