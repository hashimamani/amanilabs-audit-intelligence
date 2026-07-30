"""
Provisions a new tenant (SACCO) and its first admin user. Run from
backend/ as:

    python -m app.scripts.create_tenant --slug demo-sacco --name "Demo SACCO" \\
        --admin-email admin@demo-sacco.example --admin-name "Jane Doe"

Prints the generated admin password once - it is not stored anywhere else
and cannot be recovered, only reset by an admin through the /users UI (or
by deleting and recreating this account). This is deliberately a CLI, not
an admin UI: fine for provisioning a handful of pilot tenants by hand.
Every subsequent user for that tenant is created by this admin through
the app itself, not this script.
"""

import argparse
import secrets
import sys

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.db.models import TenantORM, UserORM


def create_tenant(slug: str, name: str, admin_email: str, admin_name: str) -> tuple[UserORM, str]:
    db = SessionLocal()
    try:
        existing_tenant = db.query(TenantORM).filter(TenantORM.slug == slug).first()
        if existing_tenant is not None:
            print(f"Tenant slug '{slug}' already exists (id={existing_tenant.id}).", file=sys.stderr)
            sys.exit(1)

        existing_user = db.query(UserORM).filter(UserORM.email == admin_email.lower()).first()
        if existing_user is not None:
            print(f"Email '{admin_email}' is already in use.", file=sys.stderr)
            sys.exit(1)

        tenant = TenantORM(slug=slug, name=name)
        db.add(tenant)
        db.flush()

        password = secrets.token_urlsafe(16)
        admin = UserORM(
            tenant_id=tenant.id,
            email=admin_email.lower(),
            password_hash=hash_password(password),
            name=admin_name,
            role="admin",
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin, password
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Provision a new Audit Intelligence tenant.")
    parser.add_argument("--slug", required=True, help="URL-safe unique tenant identifier")
    parser.add_argument("--name", required=True, help="Tenant display name")
    parser.add_argument("--admin-email", required=True, help="First admin user's email")
    parser.add_argument("--admin-name", required=True, help="First admin user's display name")
    args = parser.parse_args()

    admin, password = create_tenant(args.slug, args.name, args.admin_email, args.admin_name)
    print(f"Created tenant '{args.name}' (slug={args.slug}) with admin '{admin.email}'.")
    print(f"Password (store this now, it will not be shown again):\n{password}")


if __name__ == "__main__":
    main()
