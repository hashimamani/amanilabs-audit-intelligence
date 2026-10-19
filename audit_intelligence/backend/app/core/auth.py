"""
Who is asking, and for which tenant.

Dev/prod: the bearer is a Cognito ID token (the frontend sends the ID
token, as Tender Tracker does, because only the ID token carries the
custom tenant attribute). API Gateway's JWT authorizer has already
rejected anything unsigned by the pool, and this verifies again against
the pool's JWKS so the app behaves identically when run outside the
gateway. Role comes from `cognito:groups`; tenant from `custom:tenant`.

Local: the same claim names, signed HS256 by this app (core/security.py).

Either way the user's mirror item in the table is consulted so that an
admin deactivating a user takes effect on the next request, not when the
token expires.
"""

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, Header, HTTPException

from app.core.settings import get_settings
from app.db import repository as repo
from app.db.repository import Tenant

ROLES = ("admin", "auditor")

DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "Default / Demo"
DEFAULT_ADMIN_EMAIL = "admin@default.local"
DEFAULT_ADMIN_NAME = "Default Admin"
DEFAULT_ADMIN_DEV_PASSWORD = "local-dev-admin"


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    name: str
    tenant_slug: str
    role: str


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    settings = get_settings()
    url = f"https://cognito-idp.{settings.aws_region}.amazonaws.com/{settings.cognito_user_pool_id}/.well-known/jwks.json"
    return jwt.PyJWKClient(url, cache_keys=True)


def decode_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        if settings.auth_mode == "cognito":
            signing_key = _jwks_client().get_signing_key_from_jwt(token)
            issuer = f"https://cognito-idp.{settings.aws_region}.amazonaws.com/{settings.cognito_user_pool_id}"
            claims = jwt.decode(
                token, signing_key.key, algorithms=["RS256"], audience=settings.cognito_client_id, issuer=issuer,
            )
        else:
            claims = jwt.decode(token, settings.local_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if claims.get("token_use") != "id":
        return None
    return claims


def principal_from_claims(claims: dict) -> Principal | None:
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [g for g in groups.strip("[]").split(" ") if g]
    role = next((g for g in groups if g in ROLES), None)
    tenant_slug = claims.get("custom:tenant")
    if role is None or not tenant_slug or not claims.get("sub"):
        return None
    return Principal(
        user_id=claims["sub"],
        email=claims.get("email", ""),
        name=claims.get("name") or claims.get("email", ""),
        tenant_slug=tenant_slug,
        role=role,
    )


def get_current_user(authorization: str | None = Header(None)) -> Principal:
    principal = None
    if authorization and authorization.startswith("Bearer "):
        claims = decode_token(authorization.removeprefix("Bearer ").strip())
        if claims is not None:
            principal = principal_from_claims(claims)
    if principal is None:
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")
    mirror = repo.get_user(principal.tenant_slug, principal.user_id)
    if mirror is not None and not mirror.get("is_active", True):
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")
    if mirror is not None and mirror.get("role") in ROLES and mirror["role"] != principal.role:
        # An admin changed the role since the token was issued; the table wins.
        principal = Principal(**{**principal.__dict__, "role": mirror["role"]})
    return principal


def get_current_tenant(user: Principal = Depends(get_current_user)) -> Tenant:
    tenant = repo.get_tenant(user.tenant_slug)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")
    return tenant


def require_admin(user: Principal = Depends(get_current_user)) -> Principal:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
