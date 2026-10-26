"""
One-off data-fix script: close the plain-text / empty password-hash hole.

After ``password_utils.verify_password`` became bcrypt-only, any user whose
``password_hash`` is empty or plain text can no longer log in. This script
repairs those rows so the accounts stay usable where appropriate:

* valid bcrypt hash        -> left untouched
* empty / sentinel values  -> password is DISABLED (random bcrypt hash); these
                              accounts (Telegram bot users, station_ingest) are
                              not meant to authenticate with a password anyway
* plain-text value         -> re-hashed with bcrypt preserving the existing
                              password so the owner can still log in, with a
                              loud warning that it was stored in cleartext

Idempotent — safe to run repeatedly.

Run from the backend folder:
    .venv\\Scripts\\python.exe -m app.scripts.fix_plaintext_passwords
"""

import os
import sys
import pathlib

import bcrypt
import secrets
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Locate and load .env (mirrors create_admin.py).
# ---------------------------------------------------------------------------
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent          # app/scripts/
BACKEND_DIR = SCRIPT_DIR.parent.parent                        # backend/
_candidates = [BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env", SCRIPT_DIR / ".env"]
ENV_PATH = next((c for c in _candidates if c.is_file()), None)

if ENV_PATH is None:
    print("ERROR: .env file not found (searched repo root, backend/, scripts/).")
    sys.exit(1)

print(f"Loading .env from: {ENV_PATH}")
load_dotenv(dotenv_path=str(ENV_PATH), override=True)


def _check_env(var: str) -> str:
    value = os.getenv(var)
    if not value:
        raise RuntimeError(f"{var} is not set in .env (file: {ENV_PATH})")
    return value


DB_USER = _check_env("DB_USER")
DB_PASSWORD = _check_env("DB_PASSWORD")
DB_HOST = _check_env("DB_HOST")
DB_PORT = _check_env("DB_PORT")
DB_NAME = _check_env("DB_NAME")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")
# Values that are intentionally NOT real passwords; lock these accounts.
_LOCK_SENTINELS = {"", "!locked"}


def main() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, username, password_hash FROM users")).fetchall()

        locked: list[str] = []
        rehashed: list[str] = []
        skipped: list[str] = []

        for uid, username, pw in rows:
            pw = (pw or "").strip()
            if pw.startswith(_BCRYPT_PREFIXES):
                skipped.append(username)
                continue

            if pw in _LOCK_SENTINELS:
                new_hash = bcrypt.hashpw(
                    secrets.token_urlsafe(16).encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")
                conn.execute(
                    text("UPDATE users SET password_hash = :h WHERE id = :id"),
                    {"h": new_hash, "id": uid},
                )
                locked.append(username)
            else:
                new_hash = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                conn.execute(
                    text("UPDATE users SET password_hash = :h WHERE id = :id"),
                    {"h": new_hash, "id": uid},
                )
                rehashed.append(username)

    print()
    print("=" * 60)
    print("  Plain-text / empty password audit complete")
    print("=" * 60)
    print(f"  Already bcrypt-hashed (skipped): {len(skipped)}")
    print(f"  Password DISABLED (empty/sentinel): {len(locked)}")
    if locked:
        for u in locked:
            print(f"      - locked: {u}")
    print(f"  Plain-text RE-HASHED (password preserved): {len(rehashed)}")
    if rehashed:
        for u in rehashed:
            print(f"      - re-hashed: {u}")
    print()
    if rehashed:
        print("  !! WARNING: the re-hashed accounts above were stored in CLEARTEXT.")
        print("  !! Ask those users to change their password immediately.")
    if locked:
        print("  i  Locked accounts can no longer log in with a password (as intended).")
    print()


if __name__ == "__main__":
    main()
