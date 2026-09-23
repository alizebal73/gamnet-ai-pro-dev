import json
import shutil
import sqlite3

import pytest

from gamenet.server.db import get_connection
from gamenet.server.services.backup_service import (
    BackupError,
    BackupService,
)
from gamenet.server.services.errors import NotFound


def _conn_for(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, "
        "value TEXT, updated_at TEXT)")
    return conn


def test_service_create_list_verify(tmp_path):
    db_path = tmp_path / "gamenet.db"
    src = sqlite3.connect(str(db_path))
    src.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    src.execute("INSERT INTO t VALUES (1, 'hello')")
    src.commit()
    src.close()

    conn = _conn_for(tmp_path / "settings.db")
    service = BackupService(conn)
    monkey_dir = tmp_path / "backups"
    conn.execute(
        "INSERT INTO settings VALUES ('backup_dir', ?, 'now')",
        (str(monkey_dir),),
    )
    # Point the service at our scratch DB by overriding settings:
    from gamenet.server import config

    original = config.settings.database_path
    config.settings.database_path = str(db_path)
    try:
        manifest = service.create()
        assert manifest["id"].startswith("BKP-")
        assert (monkey_dir / manifest["filename"]).exists()
        assert (monkey_dir / f"{manifest['id']}.json").exists()
        items = service.list_backups()
        assert [m["id"] for m in items] == [manifest["id"]]
        verified = service.verify(manifest["id"])
        assert verified["hash_ok"] is True
        assert verified["integrity_ok"] is True
        with pytest.raises(NotFound):
            service.verify("BKP-NOPE")
        with pytest.raises(NotFound):
            service.verify("../evil")
    finally:
        config.settings.database_path = original
        conn.close()


def test_service_verify_detects_tampering(tmp_path):
    db_path = tmp_path / "gamenet.db"
    src = sqlite3.connect(str(db_path))
    src.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    src.commit()
    src.close()

    conn = _conn_for(tmp_path / "settings.db")
    conn.execute(
        "INSERT INTO settings VALUES ('backup_dir', ?, 'now')",
        (str(tmp_path / "backups"),),
    )
    from gamenet.server import config

    original = config.settings.database_path
    config.settings.database_path = str(db_path)
    try:
        service = BackupService(conn)
        manifest = service.create()
        target = tmp_path / "backups" / manifest["filename"]
        with open(target, "r+b") as fh:
            fh.seek(100)
            fh.write(b"XX")
        verified = service.verify(manifest["id"])
        assert verified["hash_ok"] is False
    finally:
        config.settings.database_path = original
        conn.close()


def test_service_restore_roundtrip(tmp_path):
    db_path = tmp_path / "gamenet.db"
    src = sqlite3.connect(str(db_path))
    src.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    src.execute("INSERT INTO t VALUES (1, 'before')")
    src.commit()
    src.close()

    conn = _conn_for(tmp_path / "settings.db")
    conn.execute(
        "INSERT INTO settings VALUES ('backup_dir', ?, 'now')",
        (str(tmp_path / "backups"),),
    )
    from gamenet.server import config

    original = config.settings.database_path
    config.settings.database_path = str(db_path)
    try:
        service = BackupService(conn)
        manifest = service.create()
        # Diverge the live DB, then restore:
        live = sqlite3.connect(str(db_path))
        live.execute("UPDATE t SET v = 'after' WHERE id = 1")
        live.commit()
        live.close()
        with pytest.raises(BackupError):
            service.restore(manifest["id"], confirm="wrong")
        result = service.restore(manifest["id"],
                                 confirm=manifest["id"])
        assert result["restored"] == manifest["id"]
        safety = tmp_path / result["safety_copy"]
        assert safety.exists()
        check = sqlite3.connect(str(db_path))
        value = check.execute("SELECT v FROM t WHERE id = 1"
                              ).fetchone()[0]
        check.close()
        assert value == "before"
    finally:
        config.settings.database_path = original
        conn.close()


def test_backup_routes_create_list_verify(client, owner_headers,
                                          tmp_path):
    backup_dir = tmp_path / "route-backups"
    r = client.put("/api/v1/settings/backup_dir",
                   json={"value": str(backup_dir)},
                   headers=owner_headers)
    assert r.status_code == 200, r.text
    try:
        created = client.post("/api/v1/admin/backups",
                              headers=owner_headers)
        assert created.status_code == 201, created.text
        manifest = created.json()
        assert manifest["id"].startswith("BKP-")
        assert (backup_dir / manifest["filename"]).exists()
        listed = client.get("/api/v1/admin/backups",
                            headers=owner_headers).json()
        assert manifest["id"] in [m["id"] for m in listed["items"]]
        verified = client.get(
            f"/api/v1/admin/backups/{manifest['id']}/verify",
            headers=owner_headers).json()
        assert verified["hash_ok"] is True
        assert verified["integrity_ok"] is True
        assert client.get("/api/v1/admin/backups/BKP-NOPE/verify",
                          headers=owner_headers).status_code == 404
        # Restore guards (never restore the live test DB here):
        assert client.post(
            "/api/v1/admin/backups/BKP-NOPE/restore",
            json={"confirm": "BKP-NOPE"},
            headers=owner_headers).status_code == 404
        mismatch = client.post(
            f"/api/v1/admin/backups/{manifest['id']}/restore",
            json={"confirm": "wrong"},
            headers=owner_headers)
        assert mismatch.status_code == 409
    finally:
        client.put("/api/v1/settings/backup_dir", json={"value": ""},
                   headers=owner_headers)


def test_backup_permissions(client, make_user_with_token):
    viewer = make_user_with_token("viewer")
    assert client.post("/api/v1/admin/backups",
                       headers=viewer).status_code == 403
    assert client.get("/api/v1/admin/backups",
                      headers=viewer).status_code == 403


def test_backup_manifest_sidecar_shape(client, owner_headers, tmp_path):
    backup_dir = tmp_path / "shape-backups"
    client.put("/api/v1/settings/backup_dir",
               json={"value": str(backup_dir)}, headers=owner_headers)
    try:
        manifest = client.post("/api/v1/admin/backups",
                               headers=owner_headers).json()
        sidecar = json.loads(
            (backup_dir / f"{manifest['id']}.json").read_text())
        assert sidecar["sha256"] == manifest["sha256"]
        assert sidecar["size_bytes"] > 0
    finally:
        client.put("/api/v1/settings/backup_dir", json={"value": ""},
                   headers=owner_headers)
        with get_connection():
            pass
