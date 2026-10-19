"""
Cognito mode: a token signed by the pool's key is accepted, anything else
is not. The pool's JWKS is replaced by a key generated here; the claim
shapes are Cognito's (ID token, cognito:groups, custom:tenant).
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import auth
from app.core.settings import get_settings
from app.db import repository as repo

POOL = "eu-west-1_TESTPOOL"
CLIENT_ID = "test-client-id"
ISSUER = f"https://cognito-idp.eu-west-1.amazonaws.com/{POOL}"


@pytest.fixture
def cognito_mode(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cognito")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", POOL)
    monkeypatch.setenv("COGNITO_CLIENT_ID", CLIENT_ID)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def keypair(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    class FakeSigningKey:
        key = public_pem

    class FakeJwks:
        def get_signing_key_from_jwt(self, token):
            return FakeSigningKey()

    monkeypatch.setattr(auth, "_jwks_client", lambda: FakeJwks())
    return private


def _token(private, **overrides):
    now = int(time.time())
    claims = {
        "sub": "cognito-sub-1", "email": "auditor@cognito.example", "name": "Cognito Auditor",
        "cognito:groups": ["auditor"], "custom:tenant": "default", "token_use": "id",
        "iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + 600,
        **overrides,
    }
    return jwt.encode(claims, private, algorithm="RS256")


def test_valid_id_token_is_accepted(client, cognito_mode, keypair):
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {_token(keypair)}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "auditor@cognito.example"
    assert body["role"] == "auditor"
    assert body["tenant_slug"] == "default"


def test_access_token_wrong_audience_wrong_issuer_or_expired_are_rejected(client, cognito_mode, keypair):
    for bad in (
        _token(keypair, token_use="access"),
        _token(keypair, aud="another-client"),
        _token(keypair, iss="https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_OTHER"),
        _token(keypair, exp=int(time.time()) - 10),
    ):
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_token_signed_by_another_key_is_rejected(client, cognito_mode, keypair):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {_token(other)}"}).status_code == 401


def test_local_token_is_rejected_in_cognito_mode(client, cognito_mode, keypair, default_token):
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {default_token}"}).status_code == 401


def test_login_route_is_absent_in_cognito_mode(client, cognito_mode):
    assert client.post("/auth/login", json={"email": "a@b.c", "password": "x"}).status_code == 404


def test_unknown_tenant_or_missing_group_is_rejected(client, cognito_mode, keypair):
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {_token(keypair, **{'custom:tenant': 'nope'})}"}).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {_token(keypair, **{'cognito:groups': ['other']})}"}).status_code == 401


def test_deactivated_mirror_user_is_rejected(client, cognito_mode, keypair):
    repo.put_user("default", {"user_id": "cognito-sub-off", "email": "off@cognito.example", "name": "Off", "role": "auditor", "is_active": False})
    token = _token(keypair, sub="cognito-sub-off", email="off@cognito.example")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
