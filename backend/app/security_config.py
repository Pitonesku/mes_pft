"""
Central handling of security-critical configuration.

Single source of truth for the signing secret used by:
  - bearer tokens   (auth.py)
  - SQLAdmin cookies (admin.py)

Rules
-----
* SECRET_KEY (or the legacy Secret_Key spelling) is read from the environment.
  Both spellings are accepted on every OS, because environment variable names are
  case-sensitive on Linux/Docker but not on Windows.
* ENV=production  -> a missing or placeholder secret is a startup error.
* anything else   -> a clearly-marked development fallback is used and a warning
                     is printed once.
"""

import os
import secrets

# Values that must never be used to sign anything outside a developer machine.
_PLACEHOLDER_SECRETS = {
    "",
    "insecure-dev-secret-change-me",
    "change-this-in-production",
    "your-very-secure-random-key-change-in-production",
}

# Default admin passwords that must not survive in production.
_PLACEHOLDER_ADMIN_PASSWORDS = {
    "",
    "admin",
    "change_me_before_production",
}

_DEV_FALLBACK_SECRET = None
_warned = False


def is_production() -> bool:
    """True when ENV=production (same rule as main.py)."""
    return os.getenv("ENV", "development").lower() == "production"


def get_secret_key() -> str:
    """Return the signing secret, enforcing the rules described in the module docstring."""
    global _warned, _DEV_FALLBACK_SECRET
    secret = (os.getenv("SECRET_KEY") or os.getenv("Secret_Key") or "").strip()

    if secret and secret not in _PLACEHOLDER_SECRETS:
        return secret

    if is_production():
        raise RuntimeError(
            "SECRET_KEY is missing or still a placeholder while ENV=production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\" "
            "and set it in the environment / .env file."
        )

    # Development only: generate a random per-process secret instead of reusing a
    # fixed, source-committed string, so tokens cannot be forged by anyone who can
    # read the code. Tokens/sessions do not survive a restart in dev (acceptable).
    if _DEV_FALLBACK_SECRET is None:
        _DEV_FALLBACK_SECRET = secrets.token_urlsafe(32)
    if not _warned:
        print(
            "!! [Security] SECRET_KEY is not set (or is a placeholder) -- using a random "
            "per-process development key. Set SECRET_KEY in .env before deploying."
        )
        _warned = True
    return _DEV_FALLBACK_SECRET


def check_admin_seed_password(password: str) -> None:
    """Refuse to seed a default admin password when running in production."""
    if is_production() and password in _PLACEHOLDER_ADMIN_PASSWORDS:
        raise RuntimeError(
            "Refusing to create the first admin user with a default/empty password while "
            "ENV=production. Set ADMIN_USERNAME and a strong ADMIN_PASSWORD in the environment."
        )
