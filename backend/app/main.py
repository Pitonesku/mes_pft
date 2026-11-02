import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException

from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import Optional
import pathlib
import sys

# Reconfigure std streams to UTF-8 so emoji/unicode log lines (📁, →) don't crash
# the process on Windows consoles using a legacy codepage such as cp1251.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8")
        except Exception:
            pass


# PDF Upload (Google Drive + local archive)
if __package__:
    pdf_gen = __import__(f"{__package__}.pdf_generator", fromlist=['PDFReportGenerator'])
    PDFReportGenerator = pdf_gen.PDFReportGenerator
else:
    from pdf_generator import PDFReportGenerator

import importlib
if __package__:
    # running as a package (e.g., python -m production_api.main)
    models = importlib.import_module(f"{__package__}.models")
    database_mod = importlib.import_module(f"{__package__}.database")
    get_db = database_mod.get_db
    SessionLocal = database_mod.SessionLocal
else:
    # running as a script from inside the package folder
    import models
    from database import get_db, SessionLocal

# Admin Panel (SQLAdmin)
if __package__:
    admin_module = importlib.import_module(f"{__package__}.admin")
else:
    import admin as admin_module


# AI Analysis Router
if __package__:
    ai_routes_module = importlib.import_module(f"{__package__}.ai_routes")
else:
    import ai_routes as ai_routes_module

# DB Seeding (first-startup admin user + Telegram bot admin)
if __package__:
    seed_module = importlib.import_module(f"{__package__}.seed")
    seed_initial_admin = seed_module.seed_initial_admin
    seed_telegram_admin = seed_module.seed_telegram_admin
    seed_station_ingest = seed_module.seed_station_ingest
    seed_quality_roles = seed_module.seed_quality_roles
else:
    from seed import seed_initial_admin, seed_telegram_admin, seed_station_ingest, seed_quality_roles

# AI Read-Only DB User creation (idempotent, runs on every startup)
if __package__:
    init_db_module = importlib.import_module(f"{__package__}.init_db")
    ensure_ai_user = init_db_module.ensure_ai_user
else:
    from init_db import ensure_ai_user
# Software version constant (kept in sync with frontend/pubspec.yaml)
if __package__:
    version_mod = importlib.import_module(f"{__package__}.version")
else:
    import version as version_mod


# Station watcher (integrated ingester, replaces Data_Bridge daemon)
if __package__:
    station_watcher_mod = importlib.import_module(f"{__package__}.services.station_watcher")
else:
    from services import station_watcher as station_watcher_mod

# Unified v2 API (shifts, measurements, quality/certificate, odoo outbox)
if __package__:
    v2_routes_module = importlib.import_module(f"{__package__}.v2_routes")
else:
    import v2_routes as v2_routes_module


# Background workers (A4): moved to app/workers.py so they can run in a
# dedicated process instead of threads inside the web process.
if __package__:
    workers_mod = importlib.import_module(f"{__package__}.workers")
else:
    import workers as workers_mod




# .env is already loaded by database.py (imported above) with override=True.
# This second call is a no-op but kept as a safety net.
load_dotenv()

# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================
ENV = os.getenv("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"


# === Cross-platform path resolution ===
BASE_DIR = pathlib.Path(__file__).resolve().parent


def resolve_universal_path(env_var_name: str, default_folder_name: str) -> str:
    raw = os.getenv(env_var_name)

    if not raw:
        # Fallback: relative to the directory main.py lives in
        resolved = BASE_DIR / default_folder_name
    else:
        raw_path = raw.replace("\\", "/").strip()

        # Relative env values (e.g. ".\pdf_archive") resolved against BASE_DIR so
        # the result never depends on the process CWD (dev runs from backend/,
        # the service task from C:\mes_system).
        is_absolute = raw_path.startswith("/") or (
            len(raw_path) > 1 and raw_path[1] == ":")
        if not is_absolute:
            resolved = BASE_DIR / raw_path.lstrip("./")
            resolved.mkdir(parents=True, exist_ok=True)
            return str(resolved)

        if os.name != "nt":
            # Running on Linux / WSL / Docker
            if raw_path.lower().startswith("c:/"):
                # Windows absolute → WSL mount point
                rest = raw_path[3:]
                raw_path = f"/mnt/c/{rest}"
            # Collapse any double slashes
            while "//" in raw_path:
                raw_path = raw_path.replace("//", "/")
            resolved = pathlib.Path(raw_path)
        else:
            # Running on native Windows
            if raw_path.startswith("/mnt/") and len(raw_path) > 6:
                # WSL mount point → Windows absolute
                drive = raw_path[5:6].upper()
                rest = raw_path[7:]
                raw_path = f"{drive}:/{rest}"
            # Convert forward slashes back to backslashes for Windows
            raw_path = raw_path.replace("/", "\\")
            # Collapse double slashes (except \\\\ at start for UNC)
            while "\\\\" in raw_path:
                raw_path = raw_path.replace("\\\\", "\\")
            resolved = pathlib.Path(raw_path)

    # Ensure the directory exists
    resolved.mkdir(parents=True, exist_ok=True)

    # Return native string form
    return str(resolved)


# Resolve and override env vars so all downstream code reads the corrected paths
os.environ["LOCAL_PDF_ARCHIVE_PATH"] = resolve_universal_path(
    "LOCAL_PDF_ARCHIVE_PATH", "pdf_archive"
)
os.environ["APK_RELEASES_DIR"] = resolve_universal_path(
    "APK_RELEASES_DIR", "apk_releases"
)
print(
    f"📁 LOCAL_PDF_ARCHIVE_PATH → {os.environ['LOCAL_PDF_ARCHIVE_PATH']}"
)
print(f"📁 APK_RELEASES_DIR      → {os.environ['APK_RELEASES_DIR']}")

# Resolve Google Drive credential/token FILE paths relative to the repo root
# (where .env and Gdrive_secret.json live) so they work regardless of the CWD.
def _resolve_repo_file(env_var: str) -> str:
    raw = (os.getenv(env_var) or "").strip()
    if not raw:
        return raw
    p = pathlib.Path(raw)
    if not p.is_absolute():
        p = (BASE_DIR.parent.parent / raw).resolve()
    return str(p)


_GOOGLE_CREDS = _resolve_repo_file("GOOGLE_CREDENTIALS_PATH")
if _GOOGLE_CREDS:
    os.environ["GOOGLE_CREDENTIALS_PATH"] = _GOOGLE_CREDS
_GOOGLE_TOKEN = _resolve_repo_file("GOOGLE_TOKEN_PATH")
if _GOOGLE_TOKEN:
    os.environ["GOOGLE_TOKEN_PATH"] = _GOOGLE_TOKEN

# NOTE: no create_all() here - the schema is managed by Alembic migrations only
# (ROADMAP A3, resolved 2026-10-29 by migration 0029). Fresh databases are
# created with `alembic upgrade head`.

# --- GOOGLE DRIVE STARTUP VALIDATION ---
def validate_google_drive_at_startup():
    """Validate Google Drive credentials at server startup"""
    is_valid = PDFReportGenerator.validate_google_credentials_at_startup()

    if is_valid:
        print("✅ Google Drive credentials validated successfully")
    else:
        error_msg = PDFReportGenerator.google_drive_error_message or "Unknown error"
        print(f"⚠️  Google Drive credentials are invalid: {error_msg}")
        print("⚠️  Reports will be saved locally only. You can restart the server later when credentials are fixed.")

def _parse_watch_paths(paths_env: Optional[str], single_env: Optional[str]) -> list:
    """Return a deduplicated list of watch folders from env.

    ``STATION_WATCH_PATHS`` (``;`` or ``,`` separated) takes precedence over the
    legacy single ``STATION_WATCH_PATH``. Whitespace-only entries are dropped.
    """
    if paths_env:
        parts = [p.strip() for p in paths_env.replace(",", ";").split(";") if p.strip()]
        return list(dict.fromkeys(parts))
    if single_env and single_env.strip():
        return [single_env.strip()]
    return []


# --- LIFESPAN (modern FastAPI startup/shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — runs startup validation, DB migration, and the aiogram Telegram bot."""
    # =============================================
    # STARTUP
    # =============================================
    # NOTE: schema changes are Alembic-only (migration 0029 folded in the legacy
    # migrate_db.py effects). Run `alembic upgrade head` before starting.

    # 0.5. Background workers (A4): started here instead of at import time.
    # Skip when a dedicated worker process runs them (MES_RUN_BACKGROUND_WORKERS=0).
    if workers_mod.workers_enabled():
        workers_mod.start_background_workers()

    # 1. Seed Telegram Bot admin (now safe — columns exist after migration)
    seed_telegram_admin()

    # 2. Auto-seed web admin user if DB is empty (first startup)
    seed_initial_admin()

    # 2.5. Ensure the station_ingest service account exists for push-agent keys
    seed_station_ingest()

    # 2.6. Grant can_manage_quality to Chief Engineer / Quality Manager roles
    seed_quality_roles()

    # 3. Validate Google Drive credentials
    validate_google_drive_at_startup()

    # 3.5. Ensure AI read-only DB user exists for Text-to-SQL agent
    ensure_ai_user()

    # 3.6. Start the station watcher (integrated ingester).
    # Static paths come from .env (fallback); pull-mode station_profiles in the DB
    # are re-read every scan, so the Settings UI is the single source of truth and
    # no restart is needed when a pull station is added/updated.
    app.state.station_watchers = []
    static_paths = _parse_watch_paths(
        os.getenv("STATION_WATCH_PATHS"),
        os.getenv("STATION_WATCH_PATH"),
    )
    scan_interval = int(os.getenv("STATION_SCAN_INTERVAL", "30"))

    def _pull_profile_paths() -> list:
        session = SessionLocal()
        try:
            rows = (
                session.query(models.StationProfile)
                .filter(
                    models.StationProfile.delivery_mode == "pull",
                    models.StationProfile.watch_path.isnot(None),
                )
                .all()
            )
            return [r.watch_path.strip() for r in rows if r.watch_path and r.watch_path.strip()]
        finally:
            session.close()

    cfg = station_watcher_mod.WatcherConfig(
        watch_paths=static_paths,
        scan_interval=scan_interval,
        alias_field=os.getenv("STATION_MACHINE_ALIAS_FIELD", "maker"),
        mo_field=os.getenv("STATION_MO_FIELD", "batch_description"),
        dynamic_paths=_pull_profile_paths,
    )
    watcher = station_watcher_mod.StationWatcher(SessionLocal, cfg)
    await watcher.start()
    app.state.station_watchers.append(watcher)
    print(f"📡 Station watcher started (static paths={static_paths}; pull profiles read from DB each scan)")

    # 4. Initialize and start the Telegram Bot (aiogram)
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        print("⚠️  TELEGRAM_BOT_TOKEN not set — interactive bot disabled")
    else:
        # Import aiogram components
        from aiogram import Bot, Dispatcher
        from aiogram.fsm.storage.memory import MemoryStorage
        import importlib

        if __package__:
            bot_middleware_mod = importlib.import_module(f"{__package__}.bot_middleware")
            bot_handlers_mod = importlib.import_module(f"{__package__}.bot_handlers")
        else:
            import bot_middleware as bot_middleware_mod
            import bot_handlers as bot_handlers_mod

        DbAuthMiddleware = bot_middleware_mod.DbAuthMiddleware
        router = bot_handlers_mod.router

        bot = Bot(token=TOKEN)
        dp = Dispatcher(storage=MemoryStorage())

        # Register DbAuthMiddleware for message and callback_query updates
        # NOTE: Must register on dp.message and dp.callback_query separately —
        # dp.update middleware receives an Update object, not Message/CallbackQuery,
        # so isinstance checks inside the middleware would never match.
        dp.message.middleware(DbAuthMiddleware(SessionLocal))
        dp.callback_query.middleware(DbAuthMiddleware(SessionLocal))

        # Include bot handlers router
        dp.include_router(router)

        # Clear any leftover webhooks (e.g. from Google Scripts) and start long-polling
        await bot.delete_webhook(drop_pending_updates=True)
        poll_task = asyncio.create_task(dp.start_polling(bot))

        # Stash references on app state for shutdown
        app.state.bot = bot
        app.state.bot_task = poll_task
        print("🤖 Telegram Bot started in long-polling mode")

    # =============================================
    # YIELD — FastAPI serves requests here
    # =============================================
    yield

    # =============================================
    # SHUTDOWN
    # =============================================
    if hasattr(app.state, 'bot_task'):
        app.state.bot_task.cancel()
        try:
            await app.state.bot_task
        except asyncio.CancelledError:
            pass
        await app.state.bot.session.close()
        print("🤖 Telegram Bot stopped")

    for watcher in getattr(app.state, 'station_watchers', []):
        await watcher.stop()
        print("📡 Station watcher stopped")

# Create FastAPI app with the lifespan handler.
# In production, disable all OpenAPI/docs endpoints to avoid leaking API structure.
app = FastAPI(
    title="Production ERP API",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

def _cors_origins() -> list:
    """Origins allowed for browser CORS.

    The web console is served same-origin by this server and the tablet app is
    native (unaffected by CORS). Override with a comma-separated
    ``CORS_ALLOWED_ORIGINS`` if an external origin (e.g. a reverse-proxy domain)
    needs to call the API from a browser.
    """
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    origins = ["http://localhost:8000", "http://127.0.0.1:8000"]
    public = os.getenv("MES_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if public:
        origins.append(public)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "X-Station-Key"],
)

# Optional: require bearer token / station key on every API request (see
# app/require_auth_reads.py). Enable once the old tablet APKs are retired.
if __package__:
    require_auth_reads = importlib.import_module(f"{__package__}.require_auth_reads")
else:
    import require_auth_reads
if require_auth_reads.enabled():
    app.add_middleware(require_auth_reads.RequireAuthReadsMiddleware)
    print("🔒 REQUIRE_AUTH_READS is ON — all API reads now require authentication.")

# NOTE: SessionMiddleware is registered automatically by sqladmin AuthenticationBackend
# using the same SECRET_KEY passed to AdminAuthentication(). Do NOT add a second
# SessionMiddleware here -- two layers sign cookies with different keys and break login.

# Setup SQLAdmin
admin_module.setup_admin(app)


# AI Analysis endpoints (/api/ai/analyze, /api/ai/history)
app.include_router(ai_routes_module.router, prefix="/api")

# Unified v2 API endpoints (/api/v2/...)
app.include_router(v2_routes_module.router, prefix="/api")

# Data version
@app.get("/api/version")
def get_data_version(db: Session = Depends(get_db)):
    # Take record counts of the main tables to build the version string
    po_count = db.query(models.PurchaseOrder).count()
    machine_count = db.query(models.Machine).count()
    user_count = db.query(models.User).count()

    # Build the version string (e.g. "v_10_3_5_2_8")
    shift_count = db.query(models.Shift).count()
    material_count = db.query(models.MaterialDictionary).count()
    current_version = f"v_{po_count}_{machine_count}_{user_count}_{shift_count}_{material_count}"

    return {
        # counts-based data version (kept for old tablet compatibility)
        "version": current_version,
        # real software version (single source: app/version.py)
        "app_version": version_mod.SOFTWARE_VERSION,
        "data_version": current_version,
    }


# =============================================================================
# Legacy /api/* compatibility routes (extracted - ROADMAP A5)
if __package__:
    legacy_routes_module = importlib.import_module(f"{__package__}.legacy_routes")
else:
    import legacy_routes as legacy_routes_module
app.include_router(legacy_routes_module.router)

# FLUTTER WEB SPA — must be registered LAST so all /api/* routes take priority
# =============================================================================
# Flutter web build lives in the sibling frontend/ folder; override with WEB_BUILD_DIR.
from fastapi.responses import FileResponse as _FileResponse
from fastapi.staticfiles import StaticFiles

_default_web_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'frontend', 'build', 'web'
)
_web_dir = os.getenv('WEB_BUILD_DIR') or _default_web_dir

if os.path.isdir(_web_dir):
    # Mount individual sub-directories so their files are served with correct
    # MIME types and without interfering with the API router.
    for _sub in ('flutter_assets', 'assets', 'canvaskit', 'icons'):
        _sub_path = os.path.join(_web_dir, _sub)
        if os.path.isdir(_sub_path):
            app.mount(f'/{_sub}', StaticFiles(directory=_sub_path), name=_sub)

    # Catch-all: serve index.html for every path that wasn't matched above.
    # This enables Flutter Web's client-side routing (pushState navigation).
    @app.get('/{full_path:path}', include_in_schema=False)
    async def serve_flutter_spa(full_path: str):
        # Serve an actual file if it exists (e.g. main.dart.js, favicon.png)
        candidate = os.path.join(_web_dir, full_path.lstrip('/'))
        if os.path.isfile(candidate):
            return _FileResponse(candidate)
        # A path with a file extension is a static-asset request (e.g. flutter.js.map).
        # If the file is missing, 404 instead of falling back to index.html so the
        # browser devtools doesn't try to JSON.parse the HTML fallback.
        if os.path.splitext(full_path)[1]:
            raise HTTPException(status_code=404, detail='Not found')
        # Otherwise fall back to index.html (SPA entry point)
        index = os.path.join(_web_dir, 'index.html')
        if os.path.isfile(index):
            return _FileResponse(index)
        raise HTTPException(status_code=404, detail='Not found')
