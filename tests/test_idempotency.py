import uuid


def _rid() -> str:
    return f"req-{uuid.uuid4().hex}"


def test_same_request_id_returns_same_customer(client, owner_headers):
    rid = _rid()
    body = {"name": "Idem Potent", "pin": "1212"}
    headers = {**owner_headers, "X-Request-ID": rid}
    first = client.post("/api/v1/customers", json=body, headers=headers)
    second = client.post("/api/v1/customers", json=body, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    # Only one customer was actually created:
    search = client.get(
        "/api/v1/customers/search",
        params={"q": "Idem Potent"},
        headers=owner_headers,
    ).json()
    assert sum(1 for c in search["items"] if c["name"] == "Idem Potent") == 1


def test_same_request_id_different_payload_conflicts(client, owner_headers):
    rid = _rid()
    headers = {**owner_headers, "X-Request-ID": rid}
    first = client.post(
        "/api/v1/customers", json={"name": "Original", "pin": "1212"}, headers=headers
    )
    assert first.status_code == 201
    second = client.post(
        "/api/v1/customers", json={"name": "Different", "pin": "3434"}, headers=headers
    )
    assert second.status_code == 422


def test_different_request_ids_create_different_customers(client, owner_headers):
    a = client.post(
        "/api/v1/customers",
        json={"name": "Multi A", "pin": "1212"},
        headers={**owner_headers, "X-Request-ID": _rid()},
    )
    b = client.post(
        "/api/v1/customers",
        json={"name": "Multi B", "pin": "1212"},
        headers={**owner_headers, "X-Request-ID": _rid()},
    )
    assert a.json()["id"] != b.json()["id"]


def test_invalid_request_id_rejected(client, owner_headers):
    r = client.post(
        "/api/v1/customers",
        json={"name": "Bad", "pin": "1212"},
        headers={**owner_headers, "X-Request-ID": "x" * 65},
    )
    assert r.status_code == 422
