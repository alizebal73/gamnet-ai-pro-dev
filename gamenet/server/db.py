import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from gamenet.server.config import settings


def to_utc_iso(value: datetime) -> str:
    """Format a datetime as UTC ISO-8601 with Z suffix (Master Spec 147-148)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_iso() -> str:
    return to_utc_iso(datetime.now(UTC))


def ensure_data_dir() -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(settings.database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def get_connection():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_in_transaction(fn):
    """Run ``fn(conn)`` atomically (Master Spec 81).

    Multi-step operations (sale + payment + activation + audit) must run
    inside one transaction so a failure never leaves a half-applied state.
    """
    with get_connection() as conn:
        return fn(conn)


def run_migrations(migrations_dir: Path | None = None) -> list[int]:
    """Apply pending SQL migrations. Returns list of applied version numbers."""
    migrations_dir = migrations_dir or settings.migrations_dir
    applied: list[int] = []

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        applied_versions = {row["version"] for row in rows}

        migration_files = sorted(migrations_dir.glob("*.sql"))
        for path in migration_files:
            version = int(path.name.split("_", 1)[0])
            if version in applied_versions:
                continue
            sql = path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, path.name, utc_now_iso()),
            )
            applied.append(version)

    return applied
