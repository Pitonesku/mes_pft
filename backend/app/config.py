"""
Centralized .env resolution and shared path helpers.

Every module that needs environment variables goes through ``load_env()`` so that
the location of the ``.env`` file is consistent whether the app runs locally
(``uvicorn app.main:app`` from ``backend/``), as a package, or inside Docker.

Search order (first match wins):
    1. repo root  (mes_pft/.env)
    2. backend/   (mes_pft/backend/.env)
    3. app/       (mes_pft/backend/app/.env)
If none exist, ``load_dotenv()`` falls back to the current working directory.
"""

import os
import pathlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

DEFAULT_PLANT_TIMEZONE = "Europe/Budapest"

APP_DIR = pathlib.Path(__file__).resolve().parent       # backend/app/
BACKEND_DIR = APP_DIR.parent                            # backend/
REPO_ROOT = BACKEND_DIR.parent                          # mes_pft/


def load_env() -> pathlib.Path:
    """Load the first .env found; returns its path, or None when none was loaded."""
    for candidate in (REPO_ROOT / ".env", BACKEND_DIR / ".env", APP_DIR / ".env"):
        if candidate.is_file():
            load_dotenv(dotenv_path=str(candidate), override=True)
            return candidate
    load_dotenv(override=True)
    return None


def get_plant_timezone() -> ZoneInfo:
    """Return the plant's local timezone used to interpret naive timestamps."""
    return ZoneInfo(os.getenv("MES_PLANT_TIMEZONE", DEFAULT_PLANT_TIMEZONE))


def local_to_utc(dt):
    """Interpret a naive datetime as plant-local time and return aware UTC.

    Already timezone-aware datetimes are converted to UTC unchanged; ``None``
    passes through as ``None``.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=get_plant_timezone()).astimezone(timezone.utc)
