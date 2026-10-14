import os
import pathlib
import importlib

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Load .env via the shared helper (searches repo root, backend/, then app/).
# ---------------------------------------------------------------------------
if __package__:
    config = importlib.import_module(f"{__package__}.config")
else:
    import config

ENV_PATH = config.load_env()
print(f"[Database] Loaded .env from: {ENV_PATH}")

# ---------------------------------------------------------------------------
# Read required DB credentials from environment ONLY — no hardcoded fallbacks.
# Missing values cause a clear RuntimeError so misconfiguration is obvious.
# ---------------------------------------------------------------------------
def _check_env(var: str) -> str:
    """Get a required environment variable or raise a self-diagnosing error."""
    value = os.getenv(var)
    if not value:
        env_exists = ENV_PATH.is_file()
        # List all DB_* variables currently in the environment (masked)
        db_keys = {k: v for k, v in os.environ.items() if k.startswith("DB_")}
        masked = {}
        for k, v in db_keys.items():
            if "PASSWORD" in k:
                masked[k] = "***" if v else "(empty)"
            elif "USER" in k:
                masked[k] = v[:2] + "***" if len(v) > 2 else v
            else:
                masked[k] = v
        raise RuntimeError(
            f"{var} is not set.\n"
            f"  .env path: {ENV_PATH}\n"
            f"  File exists: {env_exists}\n"
            f"  Loaded DB_ vars: {masked if masked else '(none)'}\n"
            f"  Please configure {var} in your .env file."
        )
    return value

DB_USER = _check_env("DB_USER")
DB_PASSWORD = _check_env("DB_PASSWORD")
DB_HOST = _check_env("DB_HOST")
DB_PORT = _check_env("DB_PORT")
DB_NAME = _check_env("DB_NAME")

# ---------------------------------------------------------------------------
# Build the connection string and create the engine / session factory
# ---------------------------------------------------------------------------
SQLALCHEMY_DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Log masked connection info so admins can verify the correct database is in use
_masked_user = DB_USER[:2] + "***" if len(DB_USER) > 2 else "***"
print(f"[Database] Connecting to: postgresql://{_masked_user}:***@{DB_HOST}:{DB_PORT}/{DB_NAME}")

engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, connect_args={"options": "-c timezone=utc"})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# AI Read-Only Session — separate credentials for Text-to-SQL agent safety.
# The AI user has only SELECT permissions (granted by init_db.py/ensure_ai_user).
# ---------------------------------------------------------------------------
AI_DB_USER = os.getenv("AI_DB_USER")
AI_DB_PASSWORD = os.getenv("AI_DB_PASSWORD")
if not AI_DB_USER or not AI_DB_PASSWORD:
    AI_DB_USER = None
    AI_DB_PASSWORD = None
    SessionAI = None
    print("⚠️  [Database] AI read-only DB credentials not set — Text-to-SQL agent disabled.")
else:
    AI_SQLALCHEMY_URL = (
        f"postgresql://{AI_DB_USER}:{AI_DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    ai_engine = create_engine(AI_SQLALCHEMY_URL, pool_pre_ping=True, connect_args={"options": "-c timezone=utc"})
    SessionAI = sessionmaker(autocommit=False, autoflush=False, bind=ai_engine)
    _masked_ai = AI_DB_USER[:2] + "***" if len(AI_DB_USER) > 2 else "***"
    print(f"[Database] AI read-only session: postgresql://{_masked_ai}:***@{DB_HOST}:{DB_PORT}/{DB_NAME}")
