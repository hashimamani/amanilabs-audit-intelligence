"""
Provisions a new tenant (SACCO). Run from backend/ as:

    python -m app.scripts.create_tenant --slug demo-sacco --name "Demo SACCO"

Prints the generated API key once - it is not stored anywhere else and
cannot be recovered, only rotated by deleting and recreating the tenant.
This is deliberately a CLI, not an admin UI: fine for provisioning a
handful of pilot tenants by hand, revisit once self-service onboarding is
actually needed.
"""

import argparse
import secrets
import sys

from app.core.db import SessionLocal
from app.db.models import TenantORM


def create_tenant(slug: str, name: str) -> TenantORM:
    db = SessionLocal()
    try:
        existing = db.query(TenantORM).filter(TenantORM.slug == slug).first()
        if existing is not None:
            print(f"Tenant slug '{slug}' already exists (id={existing.id}).", file=sys.stderr)
            sys.exit(1)

        tenant = TenantORM(slug=slug, name=name, api_key=secrets.token_urlsafe(32))
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return tenant
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Provision a new Audit Intelligence tenant.")
    parser.add_argument("--slug", required=True, help="URL-safe unique tenant identifier")
    parser.add_argument("--name", required=True, help="Display name")
    args = parser.parse_args()

    tenant = create_tenant(args.slug, args.name)
    print(f"Created tenant '{tenant.name}' (slug={tenant.slug}, id={tenant.id}).")
    print(f"API key (store this now, it will not be shown again):\n{tenant.api_key}")


if __name__ == "__main__":
    main()
