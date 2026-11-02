# Security Notes

Current security posture of this deployment plus the incident history that led
to it. See also `AUTHENTICATION.md` for the auth implementation.

## Current posture (implemented & hardened)

- **Token-based authentication** (`AUTHENTICATION.md`): `POST /api/auth/login`
  issues HMAC-SHA256-signed bearer tokens; report-submission, admin, AI and Odoo
  admin endpoints require `Authorization: Bearer <token>`. The legacy spoofable
  `X-User-Id` mechanism has been removed.
- **bcrypt-only password verification** (`app/password_utils.py`): plain-text and
  empty `password_hash` values are never accepted (no plain-text fallback); the
  legacy passwordless `POST /api/users/create-with-auth` endpoint is removed.
- **Login throttling**: 5 failures per username within 5 minutes → HTTP 429
  (in-memory, per process — see roadmap A4 re: multi-worker deployments).
- **Station push agent keys**: long-lived keys are stored only as SHA-256 hashes
  (`station_keys`), scoped exclusively to `POST /api/v2/quality/ingest`.
- **Odoo webhooks** (`mo-event`, `mo-recall`) are HMAC-verified against
  `ODOO_WEBHOOK_SECRET`; enabling `ODOO_WEBHOOK_REQUIRE_TIMESTAMP` additionally
  rejects unsigned/old timestamps (recommended once the addon is upgraded).
- **AI Text-to-SQL agent** runs with a separate SELECT-only database user
  (`AI_DB_USER`/`AI_DB_PASSWORD`, created by `init_db.ensure_ai_user`).
- **CORS** is an explicit allowlist (`CORS_ALLOWED_ORIGINS` + localhost + public
  base URL) with `allow_credentials=False`.
- **Production hardening** (`ENV=production`): missing/placeholder `SECRET_KEY`
  or default admin password refuse startup; OpenAPI/docs endpoints disabled;
  superadmin/authorization checks are role-based.

## Known exposure (legacy read endpoints)

Several read-only endpoints remain unauthenticated for compatibility with old
tablet APKs: `GET /api/reports`, `GET /api/purchase-orders`, `GET /api/materials`,
`GET /api/machines`, `GET /api/shifts`, and the v2 shift/quality/dashboard reads.
The fix ships as an opt-in switch: set `REQUIRE_AUTH_READS=true`
(`app/require_auth_reads.py` middleware, tracked in `ROADMAP.md`) to require a
bearer token or station key on every API request — enable it once every field
APK is retired. Webhooks, station ingest and login keep their own auth.

## Incident history (rotations already applied or still due)

The following were at some point present in plaintext files in this directory
tree. Treat them as compromised and rotate them immediately if you have not yet
done so:

- **Telegram bot token** (`TELEGRAM_BOT_TOKEN`) — revoke via @BotFather and issue a new token.
- **Database password** (`DB_PASSWORD`) — change the PostgreSQL password and update `.env`.
- **`Secret_Key`** (`Secret_Key`) — rotate to a new random value.
- **Google Drive folder access** — if the folder ID / service account was exposed, review access.

After rotating, update `.env` (never commit `.env`).

## Files that must never be committed

The following are runtime secrets and must stay out of version control
(already covered by `.gitignore`):

- `.env`, `.env.txt`
- `Gdrive_secret.json`
- `token.json`
- `nohup.out`
- `.venv/`, `__pycache__/`

## Data-fix scripts

If any users were stored with plain-text or empty `password_hash` values, run:

```bash
cd backend
.venv\Scripts\python.exe -m app.scripts.fix_plaintext_passwords
```

to re-hash (or lock) those accounts. Change any account whose password was
previously stored in plaintext (e.g. the legacy `superadmin` seeded with `123`).
