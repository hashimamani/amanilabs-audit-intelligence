from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.security import create_access_token, verify_password
from app.db.models import UserORM
from app.api.schemas import LoginIn, LoginOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def user_to_out(user: UserORM) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        is_active=user.is_active,
        tenant_slug=user.tenant.slug,
        tenant_name=user.tenant.name,
    )


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(UserORM).filter(UserORM.email == payload.email.lower()).first()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user.id)
    return LoginOut(access_token=token, user=user_to_out(user))


@router.get("/me", response_model=UserOut)
def me(user: UserORM = Depends(get_current_user)):
    return user_to_out(user)
