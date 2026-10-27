# Authentication

The Production Log API uses **signed bearer tokens** for authentication. The
previous mechanism (a client-supplied `X-User-Id` header) was spoofable and has
been removed.

## Overview

1. A client authenticates with `POST /api/auth/login` (username + password).
2. The server verifies the password with bcrypt and returns a signed bearer
   token (`access_token`).
3. The client stores the token and sends it on every protected request as:

   ```
   Authorization: Bearer <access_token>
   ```

4. The server verifies the token signature and expiry, resolves the user, and
   allows the request.

## Token details

- **Format:** base64url-encoded JSON payload + HMAC-SHA256 signature
  (`payload.signature`).
- **Payload:** `{"uid": <user_id>, "exp": <unix_expiry>}`.
- **Signing key:** `SECRET_KEY` environment variable (falls back to the legacy
  `Secret_Key` if `SECRET_KEY` is unset).
- **Lifetime:** `AUTH_TOKEN_TTL_SECONDS` (default `604800` = 7 days).

Tokens are stateless — no session table is required. Rotating `SECRET_KEY`
invalidates all previously issued tokens.

## Environment variables

```env
# Required: signs bearer tokens. Keep this secret and use a strong random value.
SECRET_KEY=your-very-secure-random-key

# Optional: token lifetime in seconds (defaults to 604800 = 7 days)
AUTH_TOKEN_TTL_SECONDS=604800
```

Generate a strong key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Protected endpoints

The following endpoints require `Authorization: Bearer <token>`:

- Report submission
  - `POST /api/reports`
  - `POST /api/reports/sync`
  - `POST /api/reports/upload-pdf`
- Report management
  - `PUT /api/reports/{id}`
  - `DELETE /api/reports/{id}`
  - `POST /api/reports/{id}/restore`
  - `GET /api/reports/deleted`
  - `GET /api/reports/{id}/logs`
  - `GET /api/reports/{id}/edits`
- Users
  - `GET /api/users`
  - `POST /api/users`
  - `PUT /api/users/{id}`
  - `GET /api/users-sync`
  - `GET /api/sync/offline-auth`
- Purchase orders
  - `POST /api/purchase-orders`
  - `PUT /api/purchase-orders/{id}`
  - `DELETE /api/purchase-orders/{id}`
- AI analysis (`/api/ai/*`)

Public (read-only) endpoints such as `GET /api/reports`, `GET /api/materials`,
`GET /api/machines`, `GET /api/shifts`, and `GET /api/purchase-orders` do not
require a token.

## Obtaining a token (example)

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "operator", "password": "your-password"}'
```

Response:

```json
{
  "status": "success",
  "user_id": 3,
  "username": "operator",
  "email": "operator@factory.local",
  "role_id": 3,
  "access_token": "<signed-token>",
  "token_type": "bearer",
  "message": "User authenticated successfully"
}
```

Use the token:

```bash
curl -X POST http://localhost:8000/api/reports \
  -H "Authorization: Bearer <signed-token>" \
  -H "Content-Type: application/json" \
  -d '{ ... report data ... }'
```

## Client integration (Flutter)

- `ApiService.login()` stores the returned `access_token` in memory and in
  `SharedPreferences` (`auth_token` key).
- `ApiService._authHeaders()` adds `Authorization: Bearer <token>` to all
  authenticated requests automatically.
- The token is reloaded on app startup via `ApiService.loadSavedAuthToken()`.
- `ApiService.clearSession()` wipes the token (`auth_token`) and the saved user
  (`auth_user`) from `SharedPreferences`. The tablet logout buttons call it, so
  a killed-and-reopened app cannot silently restore a session.
- `SessionGate._restore()` re-validates a restored session against the server
  (a `401` clears the token and returns to the login screen) and syncs data
  before entering the shell, so a stale session can no longer show fallback/demo
  data.

## Token expiry and re-login

When a token expires (or is invalid), protected requests return `401`. The
Flutter client treats report submission failures as "offline" and keeps the
report in the local pending queue. The operator must log in again online to
obtain a fresh token before pending reports can sync.

## Password policy & hardening

- **bcrypt-only verification.** `app/password_utils.py` is the single source of
  truth for hashing/verifying passwords. Legacy plain-text or empty
  `password_hash` values are *never* accepted — there is no plain-text
  comparison fallback. This closes the old hole where an account with an empty
  `password_hash` could log in with an empty password.
- **Empty passwords are rejected** on login and on user create/update.
- **Login throttling.** `/api/auth/login` limits failed attempts in-memory
  (5 failures per username within 5 minutes → HTTP 429).
- **No offline/demo login fallback.** The Flutter client no longer falls back to
  a hardcoded local user list (which included a passwordless `superadmin`); a
  session can only be established by the server.
- **`POST /api/users/create-with-auth` was removed.** User creation must use the
  authenticated `POST /api/users` endpoint (admin-only).
- **Superadmin gating is role-based**, not a username-string check.

If any users were stored with plain-text or empty `password_hash` values, run:

```bash
cd backend
.venv\Scripts\python.exe -m app.scripts.fix_plaintext_passwords
```

to re-hash (or lock) those accounts.

## Deployment notes

1. Set a strong `SECRET_KEY` in `.env`.
2. Restart the backend.
3. Rebuild and redeploy the Flutter app (Android APK and web build) so clients
   send the bearer token instead of the removed `X-User-Id` header.
