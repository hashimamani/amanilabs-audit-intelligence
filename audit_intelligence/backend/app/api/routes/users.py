from fastapi import APIRouter, Depends, HTTPException

from app.api.routes.auth import user_to_out
from app.api.schemas import UserCreateIn, UserOut, UserUpdateIn
from app.core import users
from app.core.auth import Principal, get_current_tenant, require_admin
from app.db.repository import Tenant

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(admin: Principal = Depends(require_admin), tenant: Tenant = Depends(get_current_tenant)):
    return [user_to_out(u, tenant) for u in users.list_users(tenant.slug)]


@router.post("", response_model=UserOut)
def create_user(
    payload: UserCreateIn,
    admin: Principal = Depends(require_admin),
    tenant: Tenant = Depends(get_current_tenant),
):
    try:
        user, _ = users.create_user(tenant.slug, email=payload.email, name=payload.name, role=payload.role, password=payload.password)
    except users.EmailInUse:
        raise HTTPException(status_code=400, detail=f"Email '{payload.email}' is already in use")
    return user_to_out(user, tenant)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdateIn,
    admin: Principal = Depends(require_admin),
    tenant: Tenant = Depends(get_current_tenant),
):
    user = users.update_user(tenant.slug, user_id, role=payload.role, is_active=payload.is_active)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user_to_out(user, tenant)
