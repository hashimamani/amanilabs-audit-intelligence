"""Local-mode login, token validation, role gating and tenant scoping of /users."""

from app.core.auth import DEFAULT_ADMIN_DEV_PASSWORD, DEFAULT_ADMIN_EMAIL


def test_login_with_correct_credentials_succeeds(client):
    resp = client.post("/auth/login", json={"email": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_DEV_PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == DEFAULT_ADMIN_EMAIL
    assert body["user"]["role"] == "admin"
    assert body["user"]["tenant_slug"] == "default"


def test_login_with_wrong_password_or_unknown_email_is_401(client):
    assert client.post("/auth/login", json={"email": DEFAULT_ADMIN_EMAIL, "password": "wrong"}).status_code == 401
    assert client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"}).status_code == 401


def test_me_requires_a_valid_token(client, default_token, headers):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers=headers("garbage")).status_code == 401
    resp = client.get("/auth/me", headers=headers(default_token))
    assert resp.status_code == 200
    assert resp.json()["email"] == DEFAULT_ADMIN_EMAIL


def test_deactivated_user_is_rejected_even_with_a_valid_token(client, default_token, headers, login):
    created = client.post(
        "/users",
        json={"email": "to-deactivate@example.com", "name": "Soon Deactivated", "password": "irrelevant-pw", "role": "auditor"},
        headers=headers(default_token),
    ).json()
    user_token = login(client, "to-deactivate@example.com", "irrelevant-pw")
    assert client.get("/auth/me", headers=headers(user_token)).status_code == 200

    client.patch(f"/users/{created['id']}", json={"is_active": False}, headers=headers(default_token))
    assert client.get("/auth/me", headers=headers(user_token)).status_code == 401
    assert client.post("/auth/login", json={"email": "to-deactivate@example.com", "password": "irrelevant-pw"}).status_code == 401


def test_role_change_takes_effect_without_a_new_token(client, default_token, headers, login):
    created = client.post(
        "/users",
        json={"email": "promoted@example.com", "name": "Promoted", "password": "pw-promoted", "role": "auditor"},
        headers=headers(default_token),
    ).json()
    token = login(client, "promoted@example.com", "pw-promoted")
    assert client.get("/users", headers=headers(token)).status_code == 403

    client.patch(f"/users/{created['id']}", json={"role": "admin"}, headers=headers(default_token))
    assert client.get("/users", headers=headers(token)).status_code == 200


def test_admin_only_routes_reject_an_auditor(client, default_token, headers, login):
    client.post(
        "/users",
        json={"email": "plain-auditor@example.com", "name": "Plain Auditor", "password": "auditor-pw", "role": "auditor"},
        headers=headers(default_token),
    )
    auditor_token = login(client, "plain-auditor@example.com", "auditor-pw")
    assert client.get("/users", headers=headers(auditor_token)).status_code == 403


def test_duplicate_email_is_rejected(client, default_token, headers):
    payload = {"email": "dup@example.com", "name": "Dup", "password": "pw", "role": "auditor"}
    assert client.post("/users", json=payload, headers=headers(default_token)).status_code == 200
    assert client.post("/users", json=payload, headers=headers(default_token)).status_code == 400


def test_user_crud_is_scoped_to_the_admins_own_tenant(client, default_token, headers, provision_tenant):
    other_token = provision_tenant("auth-test-other", "Other Tenant")
    default_users = client.get("/users", headers=headers(default_token)).json()
    foreign_user_id = next(u["id"] for u in default_users if u["email"] == DEFAULT_ADMIN_EMAIL)

    resp = client.patch(f"/users/{foreign_user_id}", json={"is_active": False}, headers=headers(other_token))
    assert resp.status_code == 404
    assert client.get("/users", headers=headers(other_token)).json()[0]["tenant_slug"] == "auth-test-other"
