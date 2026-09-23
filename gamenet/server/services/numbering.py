"""Traceable sequential IDs (Master Spec 78): SALE-20260921-000582 style.

The counter row is updated inside the caller's transaction; SQLite's
single-writer lock makes the read-increment-write sequence safe.
"""

import sqlite3
from datetime import UTC, datetime


def next_number(conn: sqlite3.Connection, *, name: str, prefix: str) -> str:
    day = datetime.now(UTC).strftime("%Y%m%d")
    row = conn.execute(
        "SELECT day, last_no FROM sequences WHERE name = ?", (name,)
    ).fetchone()
    if row is None or row["day"] != day:
        no = 1
        conn.execute(
            """
            INSERT INTO sequences (name, day, last_no) VALUES (?, ?, 1)
            ON CONFLICT(name) DO UPDATE SET day = excluded.day, last_no = 1
            """,
            (name, day),
        )
    else:
        no = row["last_no"] + 1
        conn.execute("UPDATE sequences SET last_no = ? WHERE name = ?", (no, name))
    return f"{prefix}-{day}-{no:06d}"
