"""SQLite backup / restore (P4-4).

Backups use the online SQLite backup API (safe while the server runs)
plus a JSON sidecar manifest with a SHA-256 hash. Restore always keeps
a timestamped safety copy of the current database first and requires
the caller to echo the backup id as confirmation.
"""

import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from gamenet.server.db import to_utc_iso
from gamenet.server.repositories.settings_repository import (
    SettingsRepository,
)
from gamenet.server.services.errors import NotFound


class BackupError(Exception):
    pass


class BackupService:
    def __init__(self, conn: sqlite3.Connection):
        self._settings = SettingsRepository(conn)

    def paths(self) -> tuple[Path, Path]:
        from gamenet.server.config import settings

        db_path = Path(settings.database_path)
        override = (self._settings.get("backup_dir") or "").strip()
        backup_dir = Path(override) if override else (
            db_path.parent / "backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        return db_path, backup_dir

    def create(self) -> dict:
        db_path, backup_dir = self.paths()
        if not db_path.exists():
            raise BackupError("Database file not found")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_id = f"BKP-{stamp}-{uuid.uuid4().hex[:6].upper()}"
        dest = backup_dir / f"{backup_id}.db"
        src = sqlite3.connect(str(db_path))
        try:
            dst = sqlite3.connect(str(dest))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        manifest = {
            "id": backup_id,
            "filename": dest.name,
            "size_bytes": dest.stat().st_size,
            "sha256": _sha256(dest),
            "created_at": to_utc_iso(datetime.now(timezone.utc)),
        }
        (backup_dir / f"{backup_id}.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def list_backups(self) -> list[dict]:
        _, backup_dir = self.paths()
        manifests = []
        for sidecar in sorted(backup_dir.glob("BKP-*.json"),
                              reverse=True):
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (backup_dir / data.get("filename", "")).exists():
                manifests.append(data)
        return manifests

    def verify(self, backup_id: str) -> dict:
        _, backup_dir = self.paths()
        manifest = self._manifest(backup_dir, backup_id)
        target = backup_dir / manifest["filename"]
        actual = _sha256(target)
        try:
            ro = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
            try:
                integrity = ro.execute(
                    "PRAGMA integrity_check").fetchone()[0]
            finally:
                ro.close()
        except sqlite3.Error:
            integrity = "unreadable"
        return {**manifest, "hash_ok": actual == manifest["sha256"],
                "integrity_ok": integrity == "ok"}

    def restore(self, backup_id: str, *, confirm: str) -> dict:
        db_path, backup_dir = self.paths()
        manifest = self._manifest(backup_dir, backup_id)
        if confirm != backup_id:
            raise BackupError(
                "Confirmation mismatch: echo the backup id to restore")
        target = backup_dir / manifest["filename"]
        if _sha256(target) != manifest["sha256"]:
            raise BackupError("Backup file hash mismatch (corrupt?)")
        try:
            ro = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
            try:
                integrity = ro.execute(
                    "PRAGMA integrity_check").fetchone()[0]
            finally:
                ro.close()
        except sqlite3.Error as exc:
            raise BackupError(
                f"Backup is unreadable: {exc}")
        if integrity != "ok":
            raise BackupError(
                f"Backup failed integrity check: {integrity}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safety = db_path.parent / (
            f"{db_path.stem}.pre-restore-{stamp}{db_path.suffix}")
        live = sqlite3.connect(str(db_path))
        try:
            live.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            live.close()
        shutil.copy2(db_path, safety)
        shutil.copy2(target, db_path)
        return {"restored": backup_id,
                "safety_copy": safety.name}

    def _manifest(self, backup_dir: Path, backup_id: str) -> dict:
        if "/" in backup_id or "\\" in backup_id or ".." in backup_id:
            raise NotFound("Backup not found")
        sidecar = backup_dir / f"{backup_id}.json"
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise NotFound("Backup not found")
        if not (backup_dir / data.get("filename", "")).exists():
            raise NotFound("Backup not found")
        return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
