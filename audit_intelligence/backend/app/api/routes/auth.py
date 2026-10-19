from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import LoginIn, LoginOut, UserOut
from app.core import users
from app.core.auth import Principal, get_current_tenant, get_current_user
from app.core.security import create_local_token
from app.core.settings import get_settings
from app.db import repository as repo
from app.db.repository import Tenant

router = APIRouter(prefix="/auth", tags=["auth"])


def user_to_out(user: dict, tenant: Tenant) -> UserOut:
    return UserOut(
        id=user["user_id"], email=user["email"], name=user["name"], role=user["role"],
        is_active=bool(user.get("is_active", True)), tenant_slug=tenant.slug, tenant_name=tenant.name,
    )


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn):
    """Local mode only. In dev/prod the browser signs in with Cognito
    directly and this route does not exist."""
    if get_settings().auth_mode != "local":
        raise HTTPException(status_code=404, detail="Login is handled by Cognito in this environment")
    user = users.authenticate_local(payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    tenant = repo.get_tenant(user["tenant_slug"])
    return LoginOut(access_token=create_local_token(user), user=user_to_out(user, tenant))


@router.get("/me", response_model=UserOut)
def me(user: Principal = Depends(get_current_user), tenant: Tenant = Depends(get_current_tenant)):
    mirror = repo.get_user(tenant.slug, user.user_id) or {
        "user_id": user.user_id, "email": user.email, "name": user.name, "role": user.role, "is_active": True,
    }
    return user_to_out(mirror, tenant)
