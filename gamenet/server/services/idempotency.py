"""Request-ID based idempotency (Master Spec 79).

Clients may send ``X-Request-ID`` with mutating requests. A replay of the
same (request_id, payload) returns the stored response without re-executing
the operation; the same request_id with a different payload is rejected.

Design: the key row is written in the SAME transaction as the business
effect, so a crash can never leave "effect without record" or
"record without effect". Concurrent duplicates serialize on SQLite's
write lock; the loser reads the winner's committed record.
"""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gamenet.server.db import utc_now_iso


class IdempotencyConflict(Exception):
    """Same request_id was used with a different payload."""


@dataclass
class IdempotentResult:
    status_code: int
    body: dict[str, Any] | None
    replayed: bool


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def idempotent_call(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    action: str,
    payload: dict[str, Any],
    fn: Callable[[], tuple[int, dict[str, Any] | None]],
    _attempt: int = 0,
) -> IdempotentResult:
    wanted = _payload_hash(payload)
    try:
        conn.execute(
            """
            INSERT INTO idempotency_keys (request_id, action, request_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (request_id, action, wanted, utc_now_iso()),
        )
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT * FROM idempotency_keys WHERE request_id = ?", (request_id,)
        ).fetchone()
        if row is None:
            # Lost a race with a rolled-back executor; retry as executor.
            if _attempt >= 2:
                raise IdempotencyConflict("Concurrent duplicate request; please retry.")
            return idempotent_call(
                conn, request_id=request_id, action=action,
                payload=payload, fn=fn, _attempt=_attempt + 1,
            )
        if row["request_hash"] != wanted:
            raise IdempotencyConflict(
                "X-Request-ID was already used with a different payload."
            )
        body = json.loads(row["response_body"]) if row["response_body"] else None
        return IdempotentResult(
            status_code=row["status_code"], body=body, replayed=True
        )

    status_code, body = fn()
    conn.execute(
        "UPDATE idempotency_keys SET status_code = ?, response_body = ? WHERE request_id = ?",
        (
            status_code,
            json.dumps(body, ensure_ascii=True) if body is not None else None,
            request_id,
        ),
    )
    return IdempotentResult(status_code=status_code, body=body, replayed=False)
