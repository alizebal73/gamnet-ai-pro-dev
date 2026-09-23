import uuid

from gamenet.server.db import get_connection
from gamenet.server.realtime import presence
from gamenet.server.services import agent_service


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _pc_with_secret(client, headers):
    code = _uniq("PC")
    pc = client.post(
        "/api/v1/pcs",
        json={"device_code": code, "display_name": code},
        headers=headers,
    ).json()
    sec = client.post(f"/api/v1/pcs/{pc['id']}/rotate-secret",
                      headers=headers).json()
    return pc, code, sec["secret"]


def _agent_auth(client, device_code, secret):
    return client.post(
        "/api/v1/agent/auth",
        json={"device_code": device_code, "secret": secret,
              "agent_version": "2.1.0"},
    )


def _beat(client, token, **payload):
    return client.post(
        "/api/v1/agent/heartbeat", json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_auth_and_heartbeat_ok(client, owner_headers):
    presence.reset()
    _, code, secret = _pc_with_secret(client, owner_headers)
    auth = _agent_auth(client, code, secret)
    assert auth.status_code == 200, auth.text
    token = auth.json()["token"]
    beat = _beat(client, token, session_id="SES-1", cpu_pct=12.5)
    assert beat.status_code == 200
    body = beat.json()
    assert body["lease_sec"] == 45
    assert body["lease_until"] > body["server_time"]
    assert body["commands"] == []
    import time as _t
    assert presence.is_online(auth.json()["pc_id"], _t.time())
    rec = presence.get(auth.json()["pc_id"])
    assert rec.session_id == "SES-1"
    assert rec.agent_version == "2.1.0"
    presence.reset()


def test_auth_rejects_bad_secret_and_unknown_device(client, owner_headers):
    _, code, _ = _pc_with_secret(client, owner_headers)
    assert _agent_auth(client, code, "wrong").status_code == 401
    assert _agent_auth(client, "NOPE-99", "x").status_code == 401


def test_heartbeat_requires_valid_token(client):
    assert client.post("/api/v1/agent/heartbeat", json={}).status_code == 401
    assert _beat(client, "garbage").status_code == 401


def test_command_queue_deliver_ack_flow(client, owner_headers):
    presence.reset()
    pc, code, secret = _pc_with_secret(client, owner_headers)
    token = _agent_auth(client, code, secret).json()["token"]
    q = client.post(
        f"/api/v1/admin/pcs/{pc['id']}/commands",
        json={"type": "MESSAGE", "payload": {"text": "hi"}},
        headers=owner_headers,
    )
    assert q.status_code == 200, q.text
    assert q.json()["status"] == "PENDING"
    beat = _beat(client, token).json()
    assert len(beat["commands"]) == 1
    cmd = beat["commands"][0]
    assert cmd["type"] == "MESSAGE"
    assert cmd["payload"] == {"text": "hi"}
    ack = client.post(
        f"/api/v1/agent/commands/{cmd['id']}/ack",
        json={"ok": True, "result": {"shown": True}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "ACKED"
    assert ack.json()["result"] == {"shown": True}
    assert _beat(client, token).json()["commands"] == []
    listed = client.get(f"/api/v1/admin/pcs/{pc['id']}/commands",
                        headers=owner_headers).json()
    assert listed[0]["status"] == "ACKED"
    presence.reset()


def test_ack_wrong_pc_rejected(client, owner_headers):
    pc_a, code_a, sec_a = _pc_with_secret(client, owner_headers)
    _, code_b, sec_b = _pc_with_secret(client, owner_headers)
    tok_b = _agent_auth(client, code_b, sec_b).json()["token"]
    q = client.post(
        f"/api/v1/admin/pcs/{pc_a['id']}/commands",
        json={"type": "LOCK"}, headers=owner_headers,
    ).json()
    ack = client.post(
        f"/api/v1/agent/commands/{q['id']}/ack", json={"ok": True},
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert ack.status_code == 404
    assert _agent_auth(client, code_a, sec_a).status_code == 200


def test_rotate_secret_revokes_agent_tokens(client, owner_headers):
    pc, code, secret = _pc_with_secret(client, owner_headers)
    token = _agent_auth(client, code, secret).json()["token"]
    assert _beat(client, token).status_code == 200
    new_sec = client.post(f"/api/v1/pcs/{pc['id']}/rotate-secret",
                          headers=owner_headers).json()["secret"]
    assert _beat(client, token).status_code == 401
    assert _agent_auth(client, code, secret).status_code == 401
    token2 = _agent_auth(client, code, new_sec).json()["token"]
    assert _beat(client, token2).status_code == 200


def test_expired_commands_not_delivered(client, owner_headers):
    pc, code, secret = _pc_with_secret(client, owner_headers)
    token = _agent_auth(client, code, secret).json()["token"]
    q = client.post(
        f"/api/v1/admin/pcs/{pc['id']}/commands",
        json={"type": "SYNC"}, headers=owner_headers,
    ).json()
    with get_connection() as conn:
        conn.execute(
            "UPDATE agent_commands SET expires_at = '2000-01-01T00:00:00' WHERE id = ?",
            (q["id"],),
        )
    agent_service._last_expire_ts = 0.0  # force the sweep to run
    assert _beat(client, token).json()["commands"] == []
    listed = client.get(f"/api/v1/admin/pcs/{pc['id']}/commands",
                        headers=owner_headers).json()
    assert listed[0]["status"] == "EXPIRED"


def test_queue_validation_and_permissions(client, owner_headers,
                                          make_user_with_token):
    pc, _, _ = _pc_with_secret(client, owner_headers)
    operator = make_user_with_token("operator")
    denied = client.post(
        f"/api/v1/admin/pcs/{pc['id']}/commands",
        json={"type": "LOCK"}, headers=operator,
    )
    assert denied.status_code == 403
    bad = client.post(
        f"/api/v1/admin/pcs/{pc['id']}/commands",
        json={"type": "FORMAT_DISK"}, headers=owner_headers,
    )
    assert bad.status_code == 400
    missing = client.post(
        "/api/v1/admin/pcs/PC-NOPE/commands",
        json={"type": "LOCK"}, headers=owner_headers,
    )
    assert missing.status_code == 404


def test_agent_channel_live_in_safe_mode(client, owner_headers):
    _, code, secret = _pc_with_secret(client, owner_headers)
    token = _agent_auth(client, code, secret).json()["token"]
    try:
        client.post("/api/v1/admin/safe-mode",
                    json={"enabled": True, "reason": "agent drill"},
                    headers=owner_headers)
        assert _beat(client, token).status_code == 200
        assert _agent_auth(client, code, secret).status_code == 200
    finally:
        client.post("/api/v1/admin/safe-mode", json={"enabled": False},
                    headers=owner_headers)


def test_presence_flush_persists_last_seen(client, owner_headers):
    presence.reset()
    pc, code, secret = _pc_with_secret(client, owner_headers)
    token = _agent_auth(client, code, secret).json()["token"]
    _beat(client, token)
    with get_connection() as conn:
        n = presence.flush_to_db(conn, "2026-09-23T12:00:00")
        assert n >= 1
        row = conn.execute("SELECT last_seen_at, agent_version FROM pcs WHERE id = ?",
                           (pc["id"],)).fetchone()
        assert row["last_seen_at"] == "2026-09-23T12:00:00"
        assert row["agent_version"] == "2.1.0"
    presence.reset()
