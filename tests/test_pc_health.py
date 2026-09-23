import uuid

from gamenet.server.realtime import presence


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


def test_heartbeat_records_health_history(client, owner_headers):
    presence.reset()
    pc, code, secret = _pc_with_secret(client, owner_headers)
    token = _agent_auth(client, code, secret).json()["token"]
    beat = _beat(client, token, cpu_pct=12.5, mem_pct=44.0,
                 disk_free_mb=12345, temp_c=55.0)
    assert beat.status_code == 200, beat.text
    _beat(client, token, cpu_pct=13.0)
    health = client.get(f"/api/v1/pcs/{pc['id']}/health",
                        headers=owner_headers)
    assert health.status_code == 200, health.text
    body = health.json()
    assert body["pc_id"] == pc["id"]
    assert body["latest"]["cpu_pct"] == 13.0
    assert len(body["samples"]) == 2
    first = body["samples"][1]
    assert first["mem_pct"] == 44.0
    assert first["disk_free_mb"] == 12345
    assert first["temp_c"] == 55.0


def test_health_empty_and_404(client, owner_headers):
    code = _uniq("PC")
    pc = client.post(
        "/api/v1/pcs",
        json={"device_code": code, "display_name": code},
        headers=owner_headers,
    ).json()
    body = client.get(f"/api/v1/pcs/{pc['id']}/health",
                      headers=owner_headers).json()
    assert body["latest"] is None
    assert body["samples"] == []
    assert client.get("/api/v1/pcs/PC-NOPE/health",
                      headers=owner_headers).status_code == 404


def test_diagnostics_bundle_shape(client, owner_headers):
    diag = client.get("/api/v1/admin/diagnostics",
                      headers=owner_headers)
    assert diag.status_code == 200, diag.text
    body = diag.json()
    assert body["server_time"]
    assert body["disk_total_mb"] > 0
    assert body["disk_free_mb"] >= 0
    assert body["db_size_bytes"] > 0
    assert isinstance(body["pcs_by_status"], dict)
    assert body["agents_connected"] >= 0
    assert body["sessions_active"] >= 0
    assert body["pending_commands"] >= 0
    assert body["open_alerts"] >= 0
    assert isinstance(body["recent_alerts"], list)


def test_health_permissions(client, owner_headers,
                            make_user_with_token):
    viewer = make_user_with_token("viewer")
    code = _uniq("PC")
    pc = client.post(
        "/api/v1/pcs",
        json={"device_code": code, "display_name": code},
        headers=owner_headers,
    ).json()
    assert client.get(f"/api/v1/pcs/{pc['id']}/health",
                      headers=viewer).status_code == 200
    assert client.get("/api/v1/admin/diagnostics",
                      headers=viewer).status_code == 200
