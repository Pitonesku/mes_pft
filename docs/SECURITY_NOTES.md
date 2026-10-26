# Security Notes — Action Required

These notes document known credential-exposure risks in this deployment and the
steps to remediate them.

## 1. Rotate the exposed secrets (urgent)

The following were previously present in plaintext files in this directory tree
(some have already been removed). Because they may have been copied or shared,
treat them as compromised and rotate them immediately:

- **Telegram bot token** (`TELEGRAM_BOT_TOKEN`) — revoke via @BotFather and issue a new token.
- **Database password** (`DB_PASSWORD`) — change the PostgreSQL password and update `.env`.
- **`Secret_Key`** (`Secret_Key`) — rotate to a new random value.
- **Google Drive folder access** — if the folder ID / service account was exposed, review access.

After rotating, update `.env` (never commit `.env`).

## 2. Files that must never be committed

The following are runtime secrets and must stay out of version control
(already covered by `.gitignore`):

- `.env`, `.env.txt`
- `Gdrive_secret.json`
- `token.json`
- `nohup.out`
- `.venv/`, `__pycache__/`

## 3. Authentication (implemented & hardened)

Token-based authentication is in place — see `AUTHENTICATION.md`:

- `POST /api/auth/login` issues a signed bearer token.
- Report-submission, admin, and AI endpoints require `Authorization: Bearer <token>`.
- The legacy spoofable `X-User-Id` mechanism has been removed.

Additional hardening applied:

- **bcrypt-only password verification** (`app/password_utils.py`): plain-text and
  empty `password_hash` values are no longer accepted (no plain-text fallback).
- The legacy **passwordless** `POST /api/users/create-with-auth` endpoint has been
  removed.
- Login is throttled (brute-force lockout).
- The Flutter client no longer falls back to a hardcoded local `superadmin`
  (empty password) on offline login.
- Superadmin/authorization checks are role-based, not username-string checks.

Remaining actions:

1. Set a strong `SECRET_KEY` in `.env` (this key signs the tokens and SQLAdmin
   cookies). In development a random per-process key is used; in production a
   missing/placeholder key is a startup error.
2. Run the data-fix script against your database to re-hash/lock any users still
   stored with plain-text or empty passwords:

   ```bash
   cd backend
   .venv\Scripts\python.exe -m app.scripts.fix_plaintext_passwords
   ```

3. Change any account whose password was previously stored in plaintext
   (e.g. the legacy `superadmin` seeded with `123`).
