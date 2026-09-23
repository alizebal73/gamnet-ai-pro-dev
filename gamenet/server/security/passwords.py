"""PIN/password hashing with bcrypt (direct, no passlib).

passlib 1.7.4 is unmaintained and incompatible with bcrypt >= 4.1
(its internal self-check crashes on the 72-byte limit), so we use
the ``bcrypt`` package directly.

bcrypt only uses the first 72 bytes of a secret. To make sure every
byte of a long (or non-ASCII) secret affects the hash, secrets
longer than 72 bytes are pre-hashed with SHA-256 first.
"""

import hashlib

import bcrypt

_BCRYPT_LIMIT_BYTES = 72


def _to_bcrypt_bytes(secret: str) -> bytes:
    raw = secret.encode("utf-8")
    if len(raw) > _BCRYPT_LIMIT_BYTES:
        raw = hashlib.sha256(raw).digest()
    return raw


def hash_secret(plain: str) -> str:
    """Hash a PIN/password. Returns the bcrypt hash as ASCII text."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(_to_bcrypt_bytes(plain), salt).decode("ascii")


def verify_secret(plain: str, hashed: str) -> bool:
    """Verify a PIN/password against a stored hash. Never raises."""
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False
