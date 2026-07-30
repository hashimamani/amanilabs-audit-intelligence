"""
Password hashing (bcrypt) and stateless access tokens (JWT) for the
Login/RBAC layer. JWT_SECRET must be overridden via env var before any
real deployment - the default here is a labeled, insecure dev value, same
pattern as DATABASE_URL in core/db.py and the CORS comment in main.py.

Tokens carry only {sub: user_id, exp} - no role/tenant baked in - so
get_current_user (core/auth.py) always does a fresh DB lookup. That's
what makes deactivating a user take effect immediately rather than
waiting for their existing token to expire.
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-insecure-secret-change-before-any-real-deploy")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except jwt.PyJWTError:
        return None
