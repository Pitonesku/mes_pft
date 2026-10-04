"""
Shared token-based authentication.

Issues and verifies HMAC-SHA256 signed bearer tokens so API clients can be
authenticated without the spoofable X-User-Id header.

The signing key is read from SECRET_KEY (or the legacy Secret_Key) environment
variable. Tokens are stateless and expire after AUTH_TOKEN_TTL_SECONDS.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

import importlib
if __package__:
    models = importlib.import_module(f"{__package__}.models")
    database_mod = importlib.import_module(f"{__package__}.database")
    security_config = importlib.import_module(f"{__package__}.security_config")
    get_db = database_mod.get_db
else:
    import models
    import security_config
    from database import get_db


_AUTH_TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))


def _auth_signing_key() -> bytes:
    return security_config.get_secret_key().encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(user_id: int) -> str:
    """Create a signed bearer token embedding the given user id."""
    payload = {"uid": int(user_id), "exp": int(time.time()) + _AUTH_TOKEN_TTL_SECONDS}
    payload_b64 = _b64url_encode(json.dumps(payload).encode("utf-8"))
    sig = hmac.new(_auth_signing_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return payload_b64 + "." + _b64url_encode(sig)


def decode_access_token(token: str) -> int:
    """Validate a bearer token and return the embedded user id.

    Raises HTTPException(401) if the token is malformed, expired, or has an
    invalid signature.
    """
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected = hmac.new(_auth_signing_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        provided = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected, provided):
            raise ValueError("bad signature")

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("token expired")
        return int(payload["uid"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> models.User:
    """FastAPI dependency: resolve the authenticated user from a bearer token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")

    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_access_token(token)

    user = (
        db.query(models.User)
        .filter(models.User.id == user_id, models.User.is_inactive == False)
        .first()
    )
    if not user:
        raise HTTPException(status_code=403, detail="User not found or inactive")

    return user
