"""Opaque auth tokens (Master Spec 136).

Tokens are random strings; only their SHA-256 hash is stored in the
``auth_sessions`` table, so a database leak does not expose live tokens.
Unlike JWT this needs no secret-key management and every token is
individually revocable (logout) and expirable.
"""

import hashlib
import secrets


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
