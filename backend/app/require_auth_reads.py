"""Optional authentication for read endpoints (ROADMAP: restrict legacy reads).

Legacy compatibility keeps many GET endpoints unauthenticated (old tablet APKs).
When ``REQUIRE_AUTH_READS`` is set (``1``/``true``/``yes``/``on``), this
middleware requires a valid bearer token or station key on EVERY request except:

* non-API paths (static files, the Flutter SPA, SQLAdmin assets) and
  ``/api/auth/login``, ``/api/version``;
* endpoints that authenticate themselves differently: the Odoo webhooks
  (HMAC), the order-summary PDF proxy (HMAC) and the station ingest endpoint
  (station key / bearer).

Enable the flag once every old tablet APK in the field is retired.
"""

import os

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def enabled() -> bool:
    raw = os.getenv("REQUIRE_AUTH_READS", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


# API paths that keep their own authentication (or must stay public).
_PUBLIC_API_PREFIXES = (
    "/api/auth/login",
    "/api/version",
    "/api/v2/odoo/mo-event",
    "/api/v2/odoo/mo-recall",
    "/api/v2/odoo/order-summary-pdf",
    "/api/v2/quality/ingest",
    "/api/v2/odoo/mo-event/",  # defensive
)


def is_public_api(path: str) -> bool:
    """True when ``path`` needs no bearer token / station key."""
    if not path.startswith("/api"):
        return True  # static / SPA / admin assets
    return any(path == p or path.startswith(p + "/") for p in _PUBLIC_API_PREFIXES)


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": "Authentication required"})


def _authenticate(authorization: str, station_key: str) -> bool:
    """True when the request carries a valid bearer token or station key.

    Imports app modules lazily so importing this module stays cheap and safe
    (no DB connection, no .env side effects) in unit tests.
    """
    import importlib

    auth = importlib.import_module("app.auth")
    models = importlib.import_module("app.models")
    database = importlib.import_module("app.database")

    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    from fastapi import HTTPException

    if token:
        try:
            user_id = auth.decode_access_token(token)
        except HTTPException:
            return False
        db = database.SessionLocal()
        try:
            user = (
                db.query(models.User)
                .filter(models.User.id == user_id, models.User.is_inactive == False)
                .first()
            )
            return user is not None
        finally:
            db.close()

    if station_key:
        db = database.SessionLocal()
        try:
            auth._resolve_station_key(db, station_key)
            return True
        except HTTPException:
            return False
        finally:
            db.close()

    return False


class RequireAuthReadsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if is_public_api(request.url.path):
            return await call_next(request)
        authorization = request.headers.get("authorization", "")
        station_key = request.headers.get("x-station-key", "")
        if not _authenticate(authorization, station_key):
            return _unauthorized()
        return await call_next(request)
