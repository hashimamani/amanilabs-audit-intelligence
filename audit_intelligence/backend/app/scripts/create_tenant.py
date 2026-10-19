"""
Provisions a new tenant (SACCO) and its first admin user. Run from
backend/ with the target environment's variables set:

    python -m app.scripts.create_tenant --slug demo-sacco --name "Demo SACCO" \\
        --admin-email admin@demo-sacco.example --admin-name "Jane Doe"

Cognito mode: Cognito emails the admin a temporary password. Local mode:
the generated password is printed once. Every subsequent user for the
tenant is created by that admin through /users in the app.
"""

import argparse
import sys

from app.core import users
from app.core.settings import get_settings
from app.db import repository as repo


def create_tenant(slug: str, name: str, admin_email: str, admin_name: str) -> tuple[dict, str | None]:
    try:
        repo.create_tenant(slug, name)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    try:
        return users.create_user(slug, email=admin_email, name=admin_name, role="admin")
    except users.EmailInUse:
        print(f"Email '{admin_email}' is already in use.", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Provision a new Audit Intelligence tenant.")
    parser.add_argument("--slug", required=True, help="URL-safe unique tenant identifier")
    parser.add_argument("--name", required=True, help="Tenant display name")
    parser.add_argument("--admin-email", required=True, help="First admin user's email")
    parser.add_argument("--admin-name", required=True, help="First admin user's display name")
    args = parser.parse_args()

    admin, password = create_tenant(args.slug, args.name, args.admin_email, args.admin_name)
    print(f"Created tenant '{args.name}' (slug={args.slug}) with admin '{admin['email']}'.")
    if password:
        print(f"Password (store this now, it will not be shown again):\n{password}")
    elif get_settings().auth_mode == "cognito":
        print("Cognito has emailed the admin a temporary password.")


if __name__ == "__main__":
    main()
