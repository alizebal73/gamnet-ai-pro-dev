import uuid

from gamenet.server.db import get_connection
from gamenet.server.repositories.auth_session_repository import AuthSessionRepository
from gamenet.server.security.tokens import generate_token, hash_token
from gamenet.server.services.user_service import UserService
from gamenet.shared.enums import RoleName


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_login_and_me(client, make_user_with_token):
    headers = make_user_with_token(RoleName.OPERATOR.value)
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["roles"] == ["operator"]
    assert "customer.view" in body["permissions"]
    assert "settings.edit" not in body["permissions"]


def test_login_via_api(client):
    username = _unique("api")
    with get_connection() as conn:
        UserService(conn).create_user(
            username=username, password="secret-123", roles=["manager"]
        )
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "secret-123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == username
    assert body["user"]["roles"] == ["manager"]
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200


def test_wrong_password_401_and_audit(client):
    username = _unique("fail")
    with get_connection() as conn:
        user = UserService(conn).create_user(
            username=username, password="right-pass-1", roles=["viewer"]
        )
        user_id = user["id"]
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "wrong-pass"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM audit_logs WHERE action = 'LOGIN_FAILED' AND user_id = ?",
            (user_id,),
        ).fetchone()
    assert row is not None


def test_unknown_user_same_message(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "no-such-user-xyz", "password": "x"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


def test_lockout_after_max_attempts(client):
    username = _unique("lock")
    with get_connection() as conn:
        UserService(conn).create_user(
            username=username, password="right-pass-1", roles=["viewer"]
        )
    for _ in range(5):
        r = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "wrong"},
        )
        assert r.status_code == 401
    locked = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "right-pass-1"},
    )
    assert locked.status_code == 423
    assert "locked_until" in locked.json()["detail"]


def test_logout_revokes_token(client, make_user_with_token):
    headers = make_user_with_token(RoleName.OPERATOR.value)
    out = client.post("/api/v1/auth/logout", headers=headers)
    assert out.status_code == 204
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 401


def test_expired_token_rejected(client):
    username = _unique("exp")
    with get_connection() as conn:
        user = UserService(conn).create_user(
            username=username, password="secret-123", roles=["viewer"]
        )
        token = generate_token()
        AuthSessionRepository(conn).create(
            token_hash=hash_token(token),
            user_id=user["id"],
            expires_at="2000-01-01T00:00:00Z",
        )
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 401


def test_protected_routes_require_auth(client):
    assert (
        client.post(
            "/api/v1/customers", json={"name": "X", "pin": "1234"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/customers/search", params={"q": "x"}
        ).status_code
        == 401
    )


def test_viewer_forbidden_on_customers(client, make_user_with_token):
    headers = make_user_with_token(RoleName.VIEWER.value)
    r = client.post(
        "/api/v1/customers",
        json={"name": "Nope", "pin": "1234"},
        headers=headers,
    )
    assert r.status_code == 403
    assert "customer.create" in r.json()["detail"]


def test_owner_has_all_permissions(client, make_user_with_token):
    headers = make_user_with_token(RoleName.OWNER.value)
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert len(me["permissions"]) == 19  # 18 base + session.operate
    r = client.post(
        "/api/v1/customers",
        json={"name": "Yes", "pin": "1234"},
        headers=headers,
    )
    assert r.status_code == 201
