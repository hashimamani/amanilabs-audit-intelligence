from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.db import get_db
from app.core.security import hash_password
from app.db.models import UserORM
from app.api.routes.auth import user_to_out
from app.api.schemas import UserOut, UserCreateIn, UserUpdateIn

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), admin: UserORM = Depends(require_admin)):
    rows = db.query(UserORM).filter(UserORM.tenant_id == admin.tenant_id).order_by(UserORM.created_at).all()
    return [user_to_out(u) for u in rows]


@router.post("", response_model=UserOut)
def create_user(
    payload: UserCreateIn,
    db: Session = Depends(get_db),
    admin: UserORM = Depends(require_admin),
):
    existing = db.query(UserORM).filter(UserORM.email == payload.email.lower()).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail=f"Email '{payload.email}' is already in use")

    user = UserORM(
        tenant_id=admin.tenant_id,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        name=payload.name,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_to_out(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdateIn,
    db: Session = Depends(get_db),
    admin: UserORM = Depends(require_admin),
):
    user = db.query(UserORM).filter(UserORM.id == user_id, UserORM.tenant_id == admin.tenant_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    return user_to_out(user)
