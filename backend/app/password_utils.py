"""Password hashing / verification helpers (bcrypt-only).

Kept import-safe (no DB or framework imports) so it can be unit-tested and
reused by ``main.py`` (API login), ``admin.py`` (SQLAdmin login) and any
one-off scripts that need to verify credentials.

Security policy
---------------
* Only bcrypt hashes are ever accepted as stored credentials.
* Empty plaintext passwords are always rejected.
* Legacy plain-text / empty stored values are rejected (there is no
  plain-text comparison fallback) — this closes the old hole where an account
  with an empty ``password_hash`` could log in with an empty password.
"""

import bcrypt

_BCRYPT_PREFIXES = (b"$2a$", b"$2b$", b"$2y$")


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password using bcrypt for server storage."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def is_bcrypt_hash(value: str) -> bool:
    """Return True when ``value`` looks like a bcrypt hash."""
    try:
        return value.encode("utf-8").startswith(_BCRYPT_PREFIXES)
    except (AttributeError, TypeError):
        return False


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash.

    Returns False for empty plaintext and for any stored value that is not a
    valid bcrypt hash, so plain-text/empty ``password_hash`` rows can never be
    used to authenticate.
    """
    if not plain_password:
        return False
    try:
        stored = hashed_password.encode("utf-8")
        if not stored.startswith(_BCRYPT_PREFIXES):
            return False
        return bcrypt.checkpw(plain_password.encode("utf-8"), stored)
    except (ValueError, TypeError):
        return False
