"""
Multi-tenant identification: every request carries an X-Tenant-Key header
resolved to a tenants row. No login/session/RBAC - that's still deferred
(see PROJECT_CONTEXT.md section 7) - this is just enough to keep each
SACCO's runs and cases scoped to them.

DEFAULT_TENANT_DEV_KEY is a stable, non-secret constant (mirrors
DEFAULT_DATASET_ID in core/datasets.py) so local dev and the bundled demo
stay zero-friction - it only ever protects the shared synthetic demo data,
never a real tenant's data. Real tenants are provisioned with a random key
via app/scripts/create_tenant.py and that key is never defaulted to.
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.db.models import TenantORM

DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "Default / Demo"
DEFAULT_TENANT_DEV_KEY = "local-dev-default-key"


def ensure_default_tenant(db: Session) -> TenantORM:
    tenant = db.query(TenantORM).filter(TenantORM.slug == DEFAULT_TENANT_SLUG).first()
    if tenant is not None:
        return tenant
    tenant = TenantORM(
        slug=DEFAULT_TENANT_SLUG,
        name=DEFAULT_TENANT_NAME,
        api_key=DEFAULT_TENANT_DEV_KEY,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def get_current_tenant(
    x_tenant_key: str | None = Header(None, alias="X-Tenant-Key"),
    db: Session = Depends(get_db),
) -> TenantORM:
    # x_tenant_key is Optional here (rather than required) on purpose: a
    # required Header() makes FastAPI reject an absent header with 422
    # before this function ever runs, which reads as "malformed request"
    # rather than "not authenticated." Treating missing and unrecognized
    # keys the same way (401) is more honest about what's actually wrong.
    tenant = None
    if x_tenant_key:
        tenant = db.query(TenantORM).filter(TenantORM.api_key == x_tenant_key).first()
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Tenant-Key header")
    return tenant
