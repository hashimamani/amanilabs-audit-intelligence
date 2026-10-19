"""
Password hashing for local auth mode, and the local token format.

In local mode this app plays the part Cognito plays in dev/prod: it checks
a password and mints a token whose claims have the same names Cognito's ID
token uses (sub, email, name, cognito:groups, custom:tenant), so everything
downstream of get_current_user is identical in both modes.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.settings import get_settings

LOCAL_TOKEN_HOURS = 24


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_local_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user["user_id"],
        "email": user["email"],
        "name": user["name"],
        "cognito:groups": [user["role"]],
        "custom:tenant": user["tenant_slug"],
        "token_use": "id",
        "iss": "local",
        "iat": now,
        "exp": now + timedelta(hours=LOCAL_TOKEN_HOURS),
    }
    return jwt.encode(claims, get_settings().local_jwt_secret, algorithm="HS256")
