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

## Token expiry and re-login

When a token expires (or is invalid), protected requests return `401`. The
Flutter client treats report submission failures as "offline" and keeps the
report in the local pending queue. The operator must log in again online to
obtain a fresh token before pending reports can sync.

## Deployment notes

1. Set a strong `SECRET_KEY` in `.env`.
2. Restart the backend.
3. Rebuild and redeploy the Flutter app (Android APK and web build) so clients
   send the bearer token instead of the removed `X-User-Id` header.
