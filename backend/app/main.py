import os
import time
import threading
import asyncio
import hashlib
import secrets
import requests
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks

from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, inspect, text, or_
from datetime import datetime, timedelta, timezone
import json
from typing import TYPE_CHECKING, Optional
import pathlib
import bcrypt
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
import base64
if __package__:
    pdf_gen = __import__(f"{__package__}.pdf_generator", fromlist=['PDFReportGenerator'])
    PDFReportGenerator = pdf_gen.PDFReportGenerator
else:
    from pdf_generator import PDFReportGenerator

import importlib
if __package__:
    # running as a package (e.g., python -m production_api.main)
    models = importlib.import_module(f"{__package__}.models")
    schemas = importlib.import_module(f"{__package__}.schemas")
    database_mod = importlib.import_module(f"{__package__}.database")
    engine = database_mod.engine
    get_db = database_mod.get_db
    SessionLocal = database_mod.SessionLocal
else:
    # running as a script from inside the package folder
    import models
    import schemas
    from database import engine, get_db, SessionLocal

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

# Token-based auth (bearer token issuance + get_current_user dependency)
if __package__:
    auth_module = importlib.import_module(f"{__package__}.auth")
    create_access_token = auth_module.create_access_token
    get_current_user = auth_module.get_current_user
else:
    from auth import create_access_token, get_current_user

# DB Seeding (first-startup admin user + Telegram bot admin)
if __package__:
    seed_module = importlib.import_module(f"{__package__}.seed")
    seed_initial_admin = seed_module.seed_initial_admin
    seed_telegram_admin = seed_module.seed_telegram_admin
    seed_station_ingest = seed_module.seed_station_ingest
else:
    from seed import seed_initial_admin, seed_telegram_admin, seed_station_ingest

# AI Read-Only DB User creation (idempotent, runs on every startup)
if __package__:
    init_db_module = importlib.import_module(f"{__package__}.init_db")
    ensure_ai_user = init_db_module.ensure_ai_user
else:
    from init_db import ensure_ai_user

# DB Migration (schema fixes applied automatically on startup)
if __package__:
    migrate_module = importlib.import_module(f"{__package__}.migrate_db")
    migrate_roles_and_users = migrate_module.migrate_roles_and_users
    migrate_report_idempotency = migrate_module.migrate_report_idempotency
else:
    from migrate_db import migrate_roles_and_users, migrate_report_idempotency

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


# Shift / run lifecycle rules (report <-> run link, auto-close, ...)
if __package__:
    shift_lifecycle_mod = importlib.import_module(f"{__package__}.services.shift_lifecycle")
else:
    from services import shift_lifecycle as shift_lifecycle_mod


def shift_lifecycle_svc_link(db, db_report) -> None:
    """Best-effort: attach a saved report to its production run (never blocks a report)."""
    try:
        with db.begin_nested():
            shift_lifecycle_mod.link_report_to_run(db, db_report)
    except Exception as exc:  # noqa: BLE001 - linking is additive, the report must still save
        print(f"[Report] could not link report {getattr(db_report, 'id', '?')} to a run: {exc}")


# .env is already loaded by database.py (imported above) with override=True.
# This second call is a no-op but kept as a safety net.
load_dotenv()

# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================
ENV = os.getenv("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"

# =============================================================================
# AUTHENTICATION INFRASTRUCTURE
# =============================================================================

# Password hashing: native bcrypt (no passlib — incompatible with Python 3.12 + bcrypt 4.x)
# PBKDF2-SHA256 for offline mobile app verification.

def hash_password(plain_password: str) -> str:
    """Hash a plain-text password using bcrypt for server storage."""
    return bcrypt.hashpw(plain_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash.
    Falls back to direct comparison for legacy plain-text hashes."""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except (ValueError, TypeError):
        # If the stored hash is not a valid bcrypt hash (e.g., plain text from old seed),
        # fall back to direct comparison for backward compatibility.
        return plain_password == hashed_password

def generate_offline_pin(plain_password: str) -> str:
    """
    Generate a PBKDF2-SHA256 hash for offline mobile app verification.
    The Flutter app uses this to authenticate users when no server connection
    is available. Uses a deterministic salt derived from the password (same
    approach the Flutter app will use with dart:crypto or pointycastle).
    
    Format: pbkdf2:sha256:<iterations>$<salt_hex>$<hash_hex>
    """
    iterations = 100000
    salt = hashlib.sha256(plain_password.encode()).hexdigest()[:32].encode()
    dk = hashlib.pbkdf2_hmac('sha256', plain_password.encode(), salt, iterations)
    return f"pbkdf2:sha256:{iterations}${salt.hex()}${dk.hex()}"


# get_current_user is now imported from auth.py (bearer-token based) and
# replaces the previous spoofable X-User-Id header check.


# === Cross-platform path resolution ===
BASE_DIR = pathlib.Path(__file__).resolve().parent


def resolve_universal_path(env_var_name: str, default_folder_name: str) -> str:
    raw = os.getenv(env_var_name)
    
    if not raw:
        # Fallback: relative to the directory main.py lives in
        resolved = BASE_DIR / default_folder_name
    else:
        raw_path = raw.replace("\\", "/")

        if os.name != "nt":
            # Running on Linux / WSL / Docker
            if raw_path.lower().startswith("c:/"):
                # Windows absolute → WSL mount point
                rest = raw_path[3:]
                raw_path = f"/mnt/c/{rest}"
            # Collapse any double slashes
            while "//" in raw_path:
                raw_path = raw_path.replace("//", "/")
            resolved = pathlib.Path(raw_path)  # <-- ИСПРАВЛЕНО ТУТ
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
            resolved = pathlib.Path(raw_path)  # <-- ИСПРАВЛЕНО ТУТ

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

# Автоматическое создание таблиц
models.Base.metadata.create_all(bind=engine)

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

# --- ФОНОВЫЙ ПОЧТАЛЬОН TELEGRAM ---
def telegram_worker():
    """Фоновый поток для отправки очереди сообщений"""
    while True:
        db = SessionLocal()
        try:
            pending_items = db.query(models.TelegramQueue).filter(
                models.TelegramQueue.status == "pending"
            ).all()

            for item in pending_items:
                # Give up after repeated failures to avoid retrying a malformed message forever.
                if item.attempts >= 10:
                    item.status = "failed"
                    item.last_error = item.last_error or "Max attempts exceeded"
                    db.commit()
                    continue

                TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
                CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
                if not TOKEN or not CHAT_ID: continue

                url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                try:
                    res = requests.post(url, json={
                        "chat_id": CHAT_ID,
                        "text": item.message_text,
                    }, timeout=10)

                    if res.status_code == 200:
                        item.status = "sent"
                        item.last_error = None
                    else:
                        item.attempts += 1
                        item.last_error = res.text
                except Exception as e:
                    item.attempts += 1
                    item.last_error = str(e)

                db.commit()
                time.sleep(1)
        except Exception as e:
            print(f"Ошибка воркера: {e}")
        finally:
            db.close()
        time.sleep(30)

# --- ФОНОВЫЙ ЗАГРУЗЧИК PDF В GOOGLE DRIVE ---
def gdrive_worker():
    """Background thread that processes PDF outbox items and uploads to Google Drive."""
    while True:
        if not PDFReportGenerator.google_drive_available:
            time.sleep(60)
            continue

        db = SessionLocal()
        try:
            pending_items = db.query(models.ReportOutbox).filter(
                models.ReportOutbox.delivery_type == "pdf_gdrive",
                models.ReportOutbox.status == "pending"
            ).all()

            for item in pending_items:
                try:
                    import tempfile
                    from googleapiclient.discovery import build
                    from googleapiclient.http import MediaFileUpload

                    credentials, error = PDFReportGenerator._get_oauth_credentials()
                    if credentials and not error:
                        service = build('drive', 'v3', credentials=credentials)
                        root_folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
                        if root_folder_id:
                            gen = PDFReportGenerator()

                            # Determine year/month from report_date if available
                            report = db.query(models.ProductionReport).filter(
                                models.ProductionReport.id == item.report_id
                            ).first()
                            if report and report.report_date:
                                try:
                                    date_obj = datetime.strptime(report.report_date.split('T')[0], '%Y-%m-%d')
                                except Exception:
                                    date_obj = datetime.now()
                            else:
                                date_obj = datetime.now()
                            year = date_obj.strftime('%Y')
                            month = date_obj.strftime('%m')

                            production_log_id = gen._get_or_create_folder(service, root_folder_id, 'Production log')
                            year_folder_id = gen._get_or_create_folder(service, production_log_id, year)
                            month_folder_id = gen._get_or_create_folder(service, year_folder_id, month)

                            # Decode base64 PDF
                            pdf_bytes = base64.b64decode(item.payload_pdf_base64)

                            # Save locally
                            local_path_env = os.getenv('LOCAL_PDF_ARCHIVE_PATH', './pdf_archive')
                            local_dir = os.path.join(local_path_env, year, month)
                            os.makedirs(local_dir, exist_ok=True)
                            filename = item.filename or f"report_{item.report_id}_{date_obj.strftime('%Y%m%d')}.pdf"
                            local_file_path = os.path.join(local_dir, filename)
                            with open(local_file_path, 'wb') as f:
                                f.write(pdf_bytes)
                            print(f"✅ PDF saved locally from outbox: {local_file_path}")

                            # Upload to GDrive
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                                tmp.write(pdf_bytes)
                                tmp_path = tmp.name

                            file_metadata = {'name': filename, 'parents': [month_folder_id]}
                            media = MediaFileUpload(tmp_path, mimetype='application/pdf')
                            file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
                            os.unlink(tmp_path)

                            item.status = "sent"
                            print(f"✅ PDF uploaded to Google Drive from outbox: {file.get('webViewLink')}")
                        else:
                            item.attempts += 1
                            item.last_error = "GOOGLE_DRIVE_FOLDER_ID not set"
                    else:
                        item.attempts += 1
                        item.last_error = error or "Auth failed"
                except Exception as e:
                    item.attempts += 1
                    item.last_error = str(e)
                    print(f"⚠️  GDrive worker error for report {item.report_id}: {e}")

                db.commit()
                time.sleep(0.5)
        except Exception as e:
            print(f"GDrive worker error: {e}")
        finally:
            db.close()
        time.sleep(30)

# --- TELEGRAM OUTBOX WORKER (processes report_outbox delivery_type='telegram') ---
def telegram_outbox_worker():
    """Background thread that sends Telegram messages queued in report_outbox.

    This is the worker that delivers Telegram notifications for reports that
    arrive via POST /api/reports/sync (offline-submitted reports). Previously
    these items were queued but never processed, so no Telegram message was sent.
    """
    while True:
        db = SessionLocal()
        try:
            pending_items = db.query(models.ReportOutbox).filter(
                models.ReportOutbox.delivery_type == "telegram",
                models.ReportOutbox.status == "pending"
            ).all()

            for item in pending_items:
                # Give up after repeated failures to avoid retrying a malformed message forever.
                if item.attempts >= 10:
                    item.status = "failed"
                    item.last_error = item.last_error or "Max attempts exceeded"
                    db.commit()
                    continue

                TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
                CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
                if not TOKEN or not CHAT_ID:
                    item.attempts += 1
                    item.last_error = "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"
                    db.commit()
                    continue

                url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                try:
                    res = requests.post(url, json={
                        "chat_id": CHAT_ID,
                        "text": item.payload_text,
                    }, timeout=10)

                    if res.status_code == 200:
                        item.status = "sent"
                        item.last_error = None
                    else:
                        item.attempts += 1
                        item.last_error = res.text
                except Exception as e:
                    item.attempts += 1
                    item.last_error = str(e)

                db.commit()
                time.sleep(1)
        except Exception as e:
            print(f"Telegram outbox worker error: {e}")
        finally:
            db.close()
        time.sleep(30)


# --- ODOO DISPATCHER (processes odoo_outbox pending items) ---
def odoo_dispatcher_worker():
    """Background thread that dispatches pending odoo_outbox items to Odoo.

    No-op unless ODOO_ENABLED=true and ODOO_URL/DB/USER/API_KEY are set.
    """
    from app.services.odoo import outbound as odoo_outbound

    config = odoo_outbound.OdooConfig.from_env()
    if not (config.enabled and config.valid()):
        print("[Odoo] disabled or incomplete config - dispatcher not started.")
        return

    poll = 30
    while True:
        try:
            db = SessionLocal()
            shadow = odoo_outbound.shadow_enabled(db)
            poll = odoo_outbound.poll_seconds(db)
            db.close()
            dispatched = odoo_outbound.dispatch_pending(SessionLocal, config, shadow=shadow)
            if dispatched:
                print(f"[Odoo] dispatched {dispatched} outbox item(s)")
        except Exception as e:
            print(f"[Odoo] dispatcher error: {e}")
            poll = 30
        time.sleep(poll)


# --- ODOO RECONCILER (re-reads the MO chain of linked, unfinished orders) ---
def odoo_reconcile_worker():
    """Safety net for missed webhooks: refresh Odoo state of linked orders.

    Interval: ``odoo_reconcile_minutes`` setting (default 10, 0 disables). An
    unreachable Odoo only logs - MES keeps working standalone.
    """
    from app.services.odoo import outbound as odoo_outbound
    from app.services.odoo import reconcile as odoo_reconcile_svc
    from app.services.odoo.client import OdooClient, OdooConfig

    config = OdooConfig.from_env()
    if not (config.enabled and config.valid()):
        return

    time.sleep(60)  # let the app finish starting
    while True:
        db = SessionLocal()
        minutes = odoo_outbound.reconcile_minutes(db)
        if minutes <= 0:
            db.close()
            time.sleep(60)  # re-check periodically while disabled
            continue
        try:
            client = OdooClient(config)
            client.connect()
            result = odoo_reconcile_svc.reconcile_all(db, client)
            if result["changed"] or result["errors"]:
                print(f"[Odoo] reconcile: {len(result['changed'])} changed, {len(result['errors'])} errors")
        except Exception as e:
            db.rollback()
            print(f"[Odoo] reconcile error: {e}")
        finally:
            db.close()
        time.sleep(minutes * 60)


# --- SHIFT AUTO-CLOSE (IN_PROGRESS -> AUTO_CLOSED once scheduled end passes +30min) ---
def shift_auto_close_worker():
    """Auto-close shifts whose scheduled end passed >30 min ago without a final report.

    Never discards data: AUTO_CLOSED keeps rods, QC checks and drafts intact — it only
    frees the machine for the next operator. Finalization (Odoo sync) happens later via
    the operator/supervisor submitting the report for that shift.
    """
    from datetime import timezone
    if __package__:
        shift_lifecycle_svc = importlib.import_module(f"{__package__}.services.shift_lifecycle")
    else:
        from services import shift_lifecycle as shift_lifecycle_svc

    time.sleep(60)  # let the app finish starting
    while True:
        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
            stale = (
                db.query(models.ShiftSession)
                .filter(
                    models.ShiftSession.ended_at.is_(None),
                    models.ShiftSession.scheduled_end_at.isnot(None),
                    models.ShiftSession.scheduled_end_at < cutoff,
                    # never auto-close a shift that was opened *after* its scheduled end
                    # (overnight early-open bug): it must have started before that end
                    models.ShiftSession.started_at < models.ShiftSession.scheduled_end_at,
                )
                .all()
            )
            for s in stale:
                s.status = "AUTO_CLOSED"
                s.ended_at = s.scheduled_end_at
                s.closed_at = datetime.now(timezone.utc)
                # Close the shift's open runs too, otherwise the machine keeps a phantom
                # running MO and the "one open run per machine" index blocks the next shift.
                shift_lifecycle_svc.close_shift_runs(db, s, s.scheduled_end_at)
                print(f"[Shift] auto-closed shift {s.id} (scheduled end {s.scheduled_end_at})")
            if stale:
                db.commit()
        except Exception as e:
            db.rollback()
            print(f"[Shift] auto-close error: {e}")
        finally:
            db.close()
        time.sleep(60)


threading.Thread(target=telegram_worker, daemon=True).start()
threading.Thread(target=telegram_outbox_worker, daemon=True).start()
threading.Thread(target=gdrive_worker, daemon=True).start()
threading.Thread(target=odoo_dispatcher_worker, daemon=True).start()
threading.Thread(target=odoo_reconcile_worker, daemon=True).start()
threading.Thread(target=shift_auto_close_worker, daemon=True).start()

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
    # 0. Migrate legacy DB schema (includes adding telegram_id + role columns)
    raw_conn = engine.raw_connection()
    try:
        migrate_roles_and_users(raw_conn)
        migrate_report_idempotency(raw_conn)
    finally:
        raw_conn.close()

    # 1. Seed Telegram Bot admin (now safe — columns exist after migration)
    seed_telegram_admin()

    # 2. Auto-seed web admin user if DB is empty (first startup)
    seed_initial_admin()

    # 2.5. Ensure the station_ingest service account exists for push-agent keys
    seed_station_ingest()

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# NOTE: SessionMiddleware is registered automatically by sqladmin AuthenticationBackend
# using the same SECRET_KEY passed to AdminAuthentication(). Do NOT add a second
# SessionMiddleware here -- two layers sign cookies with different keys and break login.

# Setup SQLAdmin
admin_module.setup_admin(app)


# AI Analysis endpoints (/api/ai/analyze, /api/ai/history)
app.include_router(ai_routes_module.router, prefix="/api")

# Unified v2 API endpoints (/api/v2/...)
app.include_router(v2_routes_module.router, prefix="/api")

# Версия данных
@app.get("/api/version")
def get_data_version(db: Session = Depends(get_db)):
    # Берем количество записей в основных таблицах для формирования версии
    po_count = db.query(models.PurchaseOrder).count()
    machine_count = db.query(models.Machine).count()
    user_count = db.query(models.User).count()

    # Формируем строку-версию (например: "v_10_3_5_2_8")
    shift_count = db.query(models.Shift).count()
    material_count = db.query(models.MaterialDictionary).count()
    current_version = f"v_{po_count}_{machine_count}_{user_count}_{shift_count}_{material_count}"

    return {"version": current_version}

# --- 1. УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ (ADMIN) ---

@app.get("/api/users", response_model=list[schemas.User])
def read_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return db.query(models.User).all()

@app.post("/api/users", response_model=schemas.User)
def create_user(
    user: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    print(f"--- SERVER: Creating user ---")
    print(f"Username: {user.username}, Email: {user.email}, Role: {user.role_id}")

    # Проверяем, что пользователь с таким username не существует
    existing = db.query(models.User).filter(models.User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"User '{user.username}' already exists")

    # Hash password with bcrypt before storing
    try:
        db_user = models.User(
            username=user.username,
            email=user.email,
            password_hash=hash_password(user.password),
            role_id=user.role_id,
            is_inactive=user.is_inactive
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        print(f"--- SERVER: User {user.username} created successfully ---")
        return db_user
    except Exception as e:
        db.rollback()
        print(f"--- SERVER ERROR: {e} ---")
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")

@app.put("/api/users/{user_id}", response_model=schemas.User)
def update_user(
    user_id: int,
    user_data: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Guard: superadmin cannot be deactivated and always has AI access
    is_superadmin = db_user.role and db_user.role.role_name.lower() == "superadmin"

    parsed = user_data.model_dump(exclude_none=True)
    password = parsed.pop("password", None)

    for key, value in parsed.items():
        if is_superadmin:
            if key == "is_inactive" and value is True:
                continue  # ignore attempt to deactivate superadmin
            if key == "can_use_ai" and value is False:
                continue  # ignore attempt to revoke AI from superadmin
            if key == "role_id":
                continue  # superadmin role is immutable
        setattr(db_user, key, value)

    if password is not None and password != "":
        db_user.password_hash = hash_password(password)

    db.commit()
    db.refresh(db_user)
    return db_user

# --- 1.1 Аутентификация и авторизация пользователей ---

@app.post("/api/auth/login")
def login(credentials: dict, db: Session = Depends(get_db)):
    """
    Authenticate a user by username and password.
    Uses bcrypt verification. No passwordless superadmin bypass.
    """
    username = credentials.get("username")
    password = credentials.get("password", "")

    user = db.query(models.User).filter(models.User.username == username).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user.is_inactive:
        raise HTTPException(status_code=403, detail="User account is inactive")

    # Verify password using bcrypt (with plain-text backward compat)
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    return {
        "status": "success",
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "role_id": user.role_id,
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "message": "User authenticated successfully"
    }

@app.get("/api/users-sync", response_model=list[schemas.User])
def sync_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Returns active users with their password_pin for offline mobile auth.
    The password_pin is a PBKDF2-SHA256 hash used for offline authentication.
    """
    users = db.query(models.User).filter(models.User.is_inactive == False).all()
    return users

@app.get("/api/sync/offline-auth")
def get_offline_auth_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Returns a minimal list of users for offline authentication caching.
    Protected endpoint — requires a bearer token from an authenticated user.
    
    Returns: id, username, role_id, email, password_pin (PBKDF2 hash for offline verification)
    """
    users = db.query(models.User).filter(models.User.is_inactive == False).all()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "role_id": u.role_id,
                "email": u.email,
                "password_pin": u.password_pin or "",
                "is_inactive": u.is_inactive,
            }
            for u in users
        ]
    }

@app.get("/api/reports", response_model=list[schemas.Report])
def get_reports(start_date: str | None = None, end_date: str | None = None, include_deleted: bool = False, db: Session = Depends(get_db)):
    """
    Возвращает производственные отчеты за указанный период.
    Если даты не указаны, возвращает последние 3 дня.
    Deleted reports are excluded by default; pass include_deleted=true to include them.
    """
    if start_date is None or end_date is None:
        today = datetime.now().date()
        end_date = today.isoformat()
        start_date = (today - timedelta(days=3)).isoformat()

    try:
        datetime.fromisoformat(start_date)
        datetime.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    query = db.query(models.ProductionReport).filter(
        models.ProductionReport.report_date >= start_date,
        models.ProductionReport.report_date <= end_date,
    )
    if not include_deleted:
        query = query.filter(
            or_(models.ProductionReport.is_deleted == False, models.ProductionReport.is_deleted == None)
        )
    reports = query.order_by(
        models.ProductionReport.sync_at.desc(),
        models.ProductionReport.id.desc(),
    ).all()

    result = []
    for report in reports:
        report_item = {col.name: getattr(report, col.name) for col in report.__table__.columns}
        # Ensure sync_at is returned as UTC ISO string with 'Z' suffix so Flutter can parse timezone correctly
        if report_item.get('sync_at') is not None:
            sync_val = report_item['sync_at']
            if hasattr(sync_val, 'isoformat'):
                report_item['sync_at'] = sync_val.strftime('%Y-%m-%dT%H:%M:%SZ')
            elif isinstance(sync_val, str) and sync_val and not sync_val.endswith('Z') and '+' not in sync_val:
                report_item['sync_at'] = sync_val.replace(' ', 'T') + 'Z'

        # Prefer returning original submitted lists stored in materials_json
        try:
            if getattr(report, 'materials_json', None):
                parsed = json.loads(report.materials_json or "{}")
                report_item['acetate_list'] = parsed.get('acetate_list', [])
                report_item['paper_list'] = parsed.get('paper_list', [])
                report_item['pva_list'] = parsed.get('pva_list', [])
                report_item['hm_list'] = parsed.get('hm_list', [])
                report_item['tri_list'] = parsed.get('tri_list', [])
                result.append(report_item)
                continue
        except Exception:
            pass

        # Fallback: single-entry lists derived from stored totals
        def build_material_list(material_type, batch, total):
            if total and total > 0:
                return [
                    {
                        "type": material_type or "Unknown",
                        "batch": batch or "No Batch",
                        "used": round(total, 2),
                    }
                ]
            return []

        report_item["acetate_list"] = build_material_list(
            report.acetate_type,
            report.acetate_batch,
            report.total_acetate,
        )
        report_item["paper_list"] = build_material_list(
            report.paper_type,
            report.paper_batch,
            report.total_paper,
        )
        report_item["pva_list"] = build_material_list(
            report.pva_glue_type,
            report.pva_batch,
            report.total_pva,
        )
        report_item["hm_list"] = build_material_list(
            report.hm_glue_type,
            report.hm_batch,
            report.total_hm,
        )
        report_item["tri_list"] = build_material_list(
            report.triacetin_type,
            report.tri_batch,
            report.total_triacetin,
        )
        result.append(report_item)

    return result


# --- GET SINGLE REPORT BY ID (full detail with nested material lists) ---
@app.get("/api/reports/{report_id}")
def get_report_by_id(report_id: int, db: Session = Depends(get_db)):
    """
    Returns a single production report with ALL nested material lists
    (acetate_list, paper_list, pva_list, hm_list, tri_list) extracted
    from materials_json. Used by the mobile audit screen to fetch
    complete report details when drilling into server-side records.
    """
    r = db.query(models.ProductionReport).filter(
        models.ProductionReport.id == report_id
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")

    report_item = {col.name: getattr(r, col.name) for col in r.__table__.columns}

    # Ensure sync_at is returned as UTC ISO string with 'Z' suffix
    if report_item.get('sync_at') is not None:
        sync_val = report_item['sync_at']
        if hasattr(sync_val, 'isoformat'):
            report_item['sync_at'] = sync_val.strftime('%Y-%m-%dT%H:%M:%SZ')
        elif isinstance(sync_val, str) and sync_val and not sync_val.endswith('Z') and '+' not in sync_val:
            report_item['sync_at'] = sync_val.replace(' ', 'T') + 'Z'

    # Prefer returning original submitted lists stored in materials_json
    try:
        if getattr(r, 'materials_json', None):
            parsed = json.loads(r.materials_json or "{}")
            report_item['acetate_list'] = parsed.get('acetate_list', [])
            report_item['paper_list'] = parsed.get('paper_list', [])
            report_item['pva_list'] = parsed.get('pva_list', [])
            report_item['hm_list'] = parsed.get('hm_list', [])
            report_item['tri_list'] = parsed.get('tri_list', [])
            return report_item
    except Exception:
        pass

    # Fallback: single-entry lists derived from stored totals
    def build_material_list(material_type, batch, total):
        if total and total > 0:
            return [
                {
                    "type": material_type or "Unknown",
                    "batch": batch or "No Batch",
                    "used": round(total, 2),
                }
            ]
        return []

    report_item["acetate_list"] = build_material_list(
        r.acetate_type, r.acetate_batch, r.total_acetate,
    )
    report_item["paper_list"] = build_material_list(
        r.paper_type, r.paper_batch, r.total_paper,
    )
    report_item["pva_list"] = build_material_list(
        r.pva_glue_type, r.pva_batch, r.total_pva,
    )
    report_item["hm_list"] = build_material_list(
        r.hm_glue_type, r.hm_batch, r.total_hm,
    )
    report_item["tri_list"] = build_material_list(
        r.triacetin_type, r.tri_batch, r.total_triacetin,
    )
    return report_item

@app.post("/api/users/create-with-auth", response_model=schemas.User)
def create_user_with_auth(payload: dict, db: Session = Depends(get_db)):
    """
    Создает нового пользователя (только superadmin).
    Payload должен содержать: admin_username, admin_password, и данные нового пользователя.
    """
    admin_username = payload.get("admin_username")
    admin_password = payload.get("admin_password", "")

    # Проверяем, что это superadmin
    admin_user = db.query(models.User).filter(models.User.username == admin_username).first()
    if not admin_user or admin_username != "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin can create users")

    # Для superadmin - вход без пароля
    if admin_username != "superadmin" or (admin_username == "superadmin" and admin_password != ""):
        raise HTTPException(status_code=403, detail="Invalid admin credentials")

    # Получаем данные нового пользователя
    new_user_data = payload.get("user_data", {})

    # Проверяем, что пользователь с таким username не существует
    existing = db.query(models.User).filter(models.User.username == new_user_data.get("username")).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    # Создаем нового пользователя
    new_user = models.User(
        username=new_user_data.get("username"),
        email=new_user_data.get("email", ""),
        password_hash=new_user_data.get("password", ""),
        role_id=new_user_data.get("role_id", 3),  # 3 = operator по умолчанию
        is_inactive=False
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user

# --- 2. УПРАВЛЕНИЕ ЗАКАЗАМИ (PURCHASE ORDERS) ---

def _apply_po_tolerance_specs(db, db_po, diameter_tol, pd_tol):
    """Upsert per-PO quality_specs rows from ± tolerance overrides.

    Creates/updates ``quality_specs`` rows (scope='po') for diameter and pressure
    drop so the quality overview and charts pick up PO-specific limits.
    """
    def _upsert(parameter, nominal, tol, unit, decimals):
        if nominal is None or tol is None:
            return
        try:
            nominal_f = float(nominal)
            tol_f = float(tol)
        except (TypeError, ValueError):
            return
        row = (
            db.query(models.QualitySpec)
            .filter(
                models.QualitySpec.scope == "po",
                models.QualitySpec.po_id == db_po.id,
                models.QualitySpec.parameter == parameter,
            )
            .first()
        )
        lower = nominal_f - tol_f
        upper = nominal_f + tol_f
        if row is None:
            db.add(models.QualitySpec(
                scope="po", po_id=db_po.id, parameter=parameter,
                nominal=nominal_f, lower_limit=lower, upper_limit=upper,
                reject_multiplier=3, rod_count=100, report_unit=unit,
                report_scale=1, decimals=decimals,
            ))
        else:
            row.nominal = nominal_f
            row.lower_limit = lower
            row.upper_limit = upper
    _upsert("diameter", db_po.diameter, diameter_tol, "mm", 3)
    _upsert("pd", db_po.pd, pd_tol, "mm WG", 1)


@app.get("/api/purchase-orders", response_model=list[schemas.PO])
def read_pos(db: Session = Depends(get_db)):
    pos = db.query(models.PurchaseOrder).all()
    _attach_allowed_materials(db, pos)
    return pos


def _attach_allowed_materials(db: Session, pos) -> None:
    """Attach the per-category allowed materials dict onto PO instances."""
    items = pos if isinstance(pos, list) else [pos]
    for po in items:
        comps = (
            db.query(models.ProductionRunComponent)
            .filter(models.ProductionRunComponent.po_id == po.id)
            .order_by(models.ProductionRunComponent.seq)
            .all()
        )
        grouped: dict = {}
        for c in comps:
            grouped.setdefault(c.category, []).append({
                "material_id": c.material_id,
                "product_name": c.product_name,
            })
        po.allowed_materials = grouped or None


@app.get("/api/settings/odoo")
def get_odoo_settings(db: Session = Depends(get_db)):
    row = db.get(models.SystemSetting, "odoo_integration")
    mode = "hybrid"
    if row is not None and isinstance(row.value, dict):
        mode = row.value.get("mode", "hybrid")
    return {"mode": mode}


@app.put("/api/settings/odoo")
def set_odoo_settings(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    user_role = current_user.role
    is_admin = user_role is not None and user_role.role_name.lower() in ("admin", "superadmin")
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    mode = str(payload.get("mode", "hybrid")).strip().lower()
    if mode not in ("hybrid", "strict"):
        raise HTTPException(status_code=400, detail="mode must be 'hybrid' or 'strict'")
    row = db.get(models.SystemSetting, "odoo_integration")
    if row is None:
        row = models.SystemSetting(key="odoo_integration", value={})
        db.add(row)
    row.value = {"mode": mode}
    db.commit()
    return {"mode": mode}


@app.post("/api/purchase-orders", response_model=schemas.PO)
def create_po(
    po: schemas.POCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    user_role = current_user.role
    is_admin = user_role is not None and user_role.role_name.lower() in ("admin", "superadmin")
    can_create = is_admin or (user_role is not None and user_role.can_create_po) or getattr(current_user, 'can_create_po', False)
    if not can_create:
        raise HTTPException(status_code=403, detail="You do not have permission to create purchase orders.")
    db_po = models.PurchaseOrder(**po.model_dump(exclude_unset=True, exclude={"diameter_tolerance", "pd_tolerance", "allowed_materials"}))
    db_po.source = "local"
    db.add(db_po)
    db.flush()
    _apply_po_tolerance_specs(db, db_po, po.diameter_tolerance, po.pd_tolerance)
    db.commit()
    db.refresh(db_po)
    return db_po


@app.put("/api/purchase-orders/{po_id}", response_model=schemas.PO)
def update_po(
    po_id: int,
    po_data: schemas.POCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == po_id).first()
    if not db_po: raise HTTPException(status_code=404, detail="PO not found")
    user_role = current_user.role
    is_admin = user_role is not None and user_role.role_name.lower() in ("admin", "superadmin")
    can_edit = is_admin or (user_role is not None and user_role.can_edit_po) or getattr(current_user, 'can_edit_po', False)
    if not can_edit:
        raise HTTPException(status_code=403, detail="You do not have permission to edit purchase orders.")
    for key, value in po_data.model_dump(exclude_unset=True, exclude={"diameter_tolerance", "pd_tolerance", "allowed_materials"}).items():
        setattr(db_po, key, value)
    _apply_po_tolerance_specs(db, db_po, po_data.diameter_tolerance, po_data.pd_tolerance)
    db.commit()
    return db_po

@app.delete("/api/purchase-orders/{po_id}")
def delete_po(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    print(f"--- SERVER: Attempting to delete PO with ID: {po_id} ---")
    db_po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == po_id).first()
    if not db_po:
        return {"status": "not_found"}
    user_role = current_user.role
    is_admin = user_role is not None and user_role.role_name.lower() in ("admin", "superadmin")
    can_edit = is_admin or (user_role is not None and user_role.can_edit_po) or getattr(current_user, 'can_edit_po', False)
    if not can_edit:
        raise HTTPException(status_code=403, detail="You do not have permission to delete purchase orders.")
    try:
        db.delete(db_po)
        db.commit()
        print("--- SERVER: Delete successful ---")
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        print(f"--- SERVER ERROR: {e} ---")
        raise HTTPException(status_code=400, detail="Related data exists")

# --- 3. Материалы, Станки и Смены ---

@app.get("/api/materials", response_model=list[schemas.Material])
def get_materials(db: Session = Depends(get_db)):
    return db.query(models.MaterialDictionary).all()

@app.post("/api/materials", response_model=schemas.Material)
def create_material(mat: schemas.MaterialBase, db: Session = Depends(get_db)):
    db_mat = models.MaterialDictionary(**mat.model_dump())
    db_mat.source = "local"
    db.add(db_mat)
    db.commit()
    db.refresh(db_mat)
    return db_mat

@app.put("/api/materials/{old_name:path}", response_model=schemas.Material)
def update_material(old_name: str, mat: schemas.MaterialBase, db: Session = Depends(get_db)):
    # Ищем существующий материал
    db_mat = db.query(models.MaterialDictionary).filter(
        models.MaterialDictionary.type_name == old_name
    ).first()

    if not db_mat:
        raise HTTPException(status_code=404, detail="Material not found")

    # Обновляем поля
    db_mat.category = mat.category
    db_mat.type_name = mat.type_name
    db_mat.default_batch = mat.default_batch
    db_mat.is_hidden = mat.is_hidden
    if mat.odoo_product_id is not None:
        db_mat.odoo_product_id = mat.odoo_product_id

    db.commit()
    db.refresh(db_mat)
    return db_mat



@app.delete("/api/materials/{material_name:path}")
def delete_material(material_name: str, db: Session = Depends(get_db)):
    # Ищем материал по type_name
    db_mat = db.query(models.MaterialDictionary).filter(
        models.MaterialDictionary.type_name == material_name
    ).first()

    if db_mat:
        db.delete(db_mat)
        db.commit()
        return {"status": "success"}
    else:
        # Если нет в базе, это нормально (например, уже удален)
        return {"status": "already_deleted"}

@app.get("/api/machines", response_model=list[schemas.Machine])
def get_machines(db: Session = Depends(get_db)):
    return db.query(models.Machine).all()

@app.post("/api/machines", response_model=schemas.Machine)
def create_machine(machine: schemas.MachineBase, db: Session = Depends(get_db)):
    db_m = models.Machine(
        name=machine.name,
        remarks=machine.remarks,
        is_inactive=machine.is_inactive,
    )
    db.add(db_m)
    db.commit()
    db.refresh(db_m)
    return db_m

@app.put("/api/machines/{old_name}", response_model=schemas.Machine)
def update_machine(old_name: str, machine: schemas.MachineBase, db: Session = Depends(get_db)):
    db_m = db.query(models.Machine).filter(models.Machine.name == old_name).first()
    if not db_m:
        raise HTTPException(status_code=404, detail="Machine not found")
    db_m.name = machine.name
    db_m.remarks = machine.remarks
    db_m.is_inactive = machine.is_inactive
    db.commit()
    db.refresh(db_m)
    return db_m

@app.delete("/api/machines/{machine_name}")
def delete_machine(machine_name: str, db: Session = Depends(get_db)):
    db_m = db.query(models.Machine).filter(models.Machine.name == machine_name).first()
    if db_m:
        db.delete(db_m)
        db.commit()
        return {"status": "success"}
    return {"status": "already_deleted"}

@app.get("/api/shifts", response_model=list[schemas.Shift])
def get_shifts(db: Session = Depends(get_db)):
    return db.query(models.Shift).all()

@app.post("/api/shifts", response_model=schemas.Shift)
def create_shift(shift: schemas.ShiftBase, db: Session = Depends(get_db)):
    db_s = models.Shift(name=shift.name)
    db_s.start = shift.start
    db_s.end = shift.end
    db.add(db_s)
    db.commit()
    db.refresh(db_s)
    return db_s

@app.put("/api/shifts/{old_name}", response_model=schemas.Shift)
def update_shift(old_name: str, shift: schemas.ShiftBase, db: Session = Depends(get_db)):
    db_s = db.query(models.Shift).filter(models.Shift.name == old_name).first()
    if not db_s:
        raise HTTPException(status_code=404, detail="Shift not found")
    db_s.name = shift.name
    db_s.start = shift.start
    db_s.end = shift.end
    db.commit()
    db.refresh(db_s)
    return db_s

@app.delete("/api/shifts/{shift_name}")
def delete_shift(shift_name: str, db: Session = Depends(get_db)):
    db_s = db.query(models.Shift).filter(models.Shift.name == shift_name).first()
    if db_s:
        db.delete(db_s)
        db.commit()
        return {"status": "success"}
    return {"status": "already_deleted"}

# --- 3.5 PDF UPLOAD ENDPOINT (receives pre-generated PDF bytes from Flutter) ---

@app.post("/api/reports/upload-pdf")
async def upload_pdf_report(
    payload: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Receive a pre-generated PDF (as base64) from the Flutter app.
    Save to LOCAL_PDF_ARCHIVE_PATH and upload to Google Drive.
    The PDF is generated by Flutter (same design as the app).
    """
    try:
        pdf_base64 = payload.get('pdf_base64', '')
        filename = payload.get('filename', 'report.pdf')
        report_date = payload.get('report_date', '')

        if not pdf_base64:
            raise HTTPException(status_code=400, detail="No PDF data provided")

        # Decode base64 to bytes
        pdf_bytes = base64.b64decode(pdf_base64)

        # Persist the exact PDF into ReportOutbox so the Odoo dispatcher can attach
        # the SAME file that goes to Google Drive (the "exact stream" requirement).
        # Marked "sent" because this endpoint uploads to Drive directly, so the
        # gdrive_worker must not re-send it; the dispatcher only reads the base64.
        report_id = payload.get('report_id')
        if report_id:
            try:
                db_report = db.get(models.ProductionReport, int(report_id))
            except (TypeError, ValueError):
                db_report = None
            if db_report is not None:
                db.add(models.ReportOutbox(
                    report_id=db_report.id,
                    delivery_type='pdf_gdrive',
                    payload_pdf_base64=pdf_base64,
                    filename=filename,
                    status='sent',
                ))
                db.commit()

        # --- Save to local archive ---
        local_path_env = os.getenv('LOCAL_PDF_ARCHIVE_PATH', './pdf_archive')
        # Build folder structure: YYYY/MM/
        try:
            date_obj = datetime.strptime(report_date.split('T')[0], '%Y-%m-%d')
        except Exception:
            date_obj = datetime.now()
        year = date_obj.strftime('%Y')
        month = date_obj.strftime('%m')
        local_dir = os.path.join(local_path_env, year, month)
        os.makedirs(local_dir, exist_ok=True)
        local_file_path = os.path.join(local_dir, filename)
        with open(local_file_path, 'wb') as f:
            f.write(pdf_bytes)
        print(f"✅ PDF saved locally: {local_file_path}")

        # --- Upload to Google Drive ---
        drive_result = {'success': False, 'error': 'Not attempted'}
        if PDFReportGenerator.google_drive_available:
            try:
                import tempfile
                from googleapiclient.discovery import build
                from googleapiclient.http import MediaFileUpload

                credentials, error = PDFReportGenerator._get_oauth_credentials()
                if credentials and not error:
                    service = build('drive', 'v3', credentials=credentials)
                    root_folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
                    if root_folder_id:
                        gen = PDFReportGenerator()
                        production_log_id = gen._get_or_create_folder(service, root_folder_id, 'Production log')
                        year_folder_id = gen._get_or_create_folder(service, production_log_id, year)
                        month_folder_id = gen._get_or_create_folder(service, year_folder_id, month)

                        # Write bytes to temp file for upload
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                            tmp.write(pdf_bytes)
                            tmp_path = tmp.name

                        file_metadata = {'name': filename, 'parents': [month_folder_id]}
                        media = MediaFileUpload(tmp_path, mimetype='application/pdf')
                        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
                        os.unlink(tmp_path)

                        drive_result = {'success': True, 'web_link': file.get('webViewLink')}
                        print(f"✅ PDF uploaded to Google Drive: {file.get('webViewLink')}")
                    else:
                        drive_result = {'success': False, 'error': 'GOOGLE_DRIVE_FOLDER_ID not set'}
                else:
                    drive_result = {'success': False, 'error': error or 'Auth failed'}
            except Exception as e:
                drive_result = {'success': False, 'error': str(e)}
                print(f"⚠️  Google Drive upload failed: {e}")
        else:
            drive_result = {'success': False, 'error': PDFReportGenerator.google_drive_error_message or 'Google Drive not available'}

        return {
            'status': 'success',
            'local_path': local_file_path,
            'filename': filename,
            'google_drive_success': drive_result.get('success', False),
            'google_drive_link': drive_result.get('web_link'),
            'google_drive_error': drive_result.get('error') if not drive_result.get('success') else None,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading PDF: {str(e)}")

# --- 4. Прием отчетов (с телеграм ботом) ---

@app.post("/api/reports")
def create_report(
    report_data: schemas.ReportCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        # Idempotency guard: if the client already submitted this report, return it
        client_report_id = (report_data.client_report_id or "").strip()
        if client_report_id:
            existing = db.query(models.ProductionReport).filter(
                models.ProductionReport.client_report_id == client_report_id
            ).first()
            if existing:
                return {"status": "duplicate", "report_id": existing.id}

        def resolve_material_fields(list_items, existing_type, existing_batch):
            material_type = (existing_type or "").strip()
            material_batch = (existing_batch or "").strip() or "No Batch"
            if list_items:
                for item in list_items:
                    if not isinstance(item, dict):
                        continue
                    candidate_type = str(item.get('type') or '').strip()
                    candidate_batch = str(item.get('batch') or '').strip() or "No Batch"
                    if candidate_type:
                        material_type = candidate_type
                        material_batch = candidate_batch
                        break
                if not material_type and list_items:
                    first_item = list_items[0]
                    if isinstance(first_item, dict):
                        material_type = str(first_item.get('type') or '').strip()
                        material_batch = str(first_item.get('batch') or '').strip() or "No Batch"

            return material_type, material_batch

        payload = report_data.model_dump()
        acetate_list = payload.pop('acetate_list', None)
        paper_list = payload.pop('paper_list', None)
        pva_list = payload.pop('pva_list', None)
        hm_list = payload.pop('hm_list', None)
        tri_list = payload.pop('tri_list', None)

        acetate_type, acetate_batch = resolve_material_fields(
            acetate_list,
            payload.get('acetate_type', ''),
            payload.get('acetate_batch', ''),
        )
        paper_type, paper_batch = resolve_material_fields(
            paper_list,
            payload.get('paper_type', ''),
            payload.get('paper_batch', ''),
        )
        pva_type, pva_batch = resolve_material_fields(
            pva_list,
            payload.get('pva_glue_type', ''),
            payload.get('pva_batch', ''),
        )
        hm_type, hm_batch = resolve_material_fields(
            hm_list,
            payload.get('hm_glue_type', ''),
            payload.get('hm_batch', ''),
        )
        tri_type, tri_batch = resolve_material_fields(
            tri_list,
            payload.get('triacetin_type', ''),
            payload.get('tri_batch', ''),
        )

        payload['acetate_type'] = acetate_type
        payload['acetate_batch'] = acetate_batch
        payload['paper_type'] = paper_type
        payload['paper_batch'] = paper_batch
        payload['pva_glue_type'] = pva_type
        payload['pva_batch'] = pva_batch
        payload['hm_glue_type'] = hm_type
        payload['hm_batch'] = hm_batch
        payload['triacetin_type'] = tri_type
        payload['tri_batch'] = tri_batch
        # store original submitted lists as JSON for detail views
        try:
            payload['materials_json'] = json.dumps({
                'acetate_list': acetate_list or [],
                'paper_list': paper_list or [],
                'pva_list': pva_list or [],
                'hm_list': hm_list or [],
                'tri_list': tri_list or [],
            })
        except Exception:
            payload['materials_json'] = ''

        # 1. Сохраняем отчет в БД
        # Always store sync_at as naive UTC (never func.now(), which uses the
        # database session timezone).
        submitted_utc = payload.pop('submitted_at_utc', None)
        if submitted_utc:
            if getattr(submitted_utc, 'tzinfo', None) is not None:
                submitted_utc = submitted_utc.astimezone(timezone.utc).replace(tzinfo=None)
            payload['sync_at'] = submitted_utc
        else:
            payload['sync_at'] = datetime.now(timezone.utc).replace(tzinfo=None)
        db_report = models.ProductionReport(**payload)
        db.add(db_report)
        db.flush() # Получаем ID отчета до коммита
        shift_lifecycle_svc_link(db, db_report)

        # --- ВАЖНО: Обновляем АБСОЛЮТНЫЙ счет отчетов из БД ---
        remaining_qty = 0
        total_produced_absolute = 0

        # Lock the PO row first to serialize concurrent submissions for the same PO,
        # then compute the absolute produced_qty from all reports (excluding soft-deleted).
        po_to_update = db.query(models.PurchaseOrder).filter(
            models.PurchaseOrder.po_number == report_data.po_number
        ).with_for_update().first()

        total_sum_query = db.query(func.sum(models.ProductionReport.produced_rods))\
                            .filter(
                                models.ProductionReport.po_number == report_data.po_number,
                                or_(models.ProductionReport.is_deleted == False, models.ProductionReport.is_deleted == None),
                            )\
                            .scalar()

        total_produced_absolute = total_sum_query or 0

        # Находим PO и обновляем produced_qty
        if po_to_update:
            po_to_update.produced_qty = total_produced_absolute # Обновляем абсолютный счет
            remaining_qty = po_to_update.target_qty - total_produced_absolute
        else:
            remaining_qty = 0
        # -------------------------------------------------------------

        # 2. Формируем строку времени смены
        if report_data.shift_time_range:
            shift_display = f"{report_data.shift_name} ({report_data.shift_time_range})"
        else:
            shift_display = datetime.now().strftime("%H:%M:%S")

        # 3. Строим текст Telegram (берется из report_data перед коммитом!)
        if report_data.parent_report_id or report_data.edited_by:
            text = (
                f"Edited report from {report_data.report_date}/{report_data.shift_name}/{report_data.operator_name}/{report_data.machine_name}\n"
                f"Edited by: {report_data.edited_by or report_data.operator_name}\n"
                f"Date: {report_data.report_date}\n"
                f"Time: {shift_display}\n"
                f"Operator: {report_data.operator_name}\n"
                f"Machine #: {report_data.machine_name}\n\n"
            )
        else:
            text = (
                f"Production report submitted\n"
                f"Date: {report_data.report_date}\n"
                f"Time: {shift_display}\n"
                f"Operator: {report_data.operator_name}\n"
                f"Machine #: {report_data.machine_name}\n\n"
            )

        # Build diff_percent display (strip trailing % if present, add markers)
        raw_diff_pct_str = str(report_data.diff_percent or "0").replace('%', '').strip()
        try:
            diff_pct_val = float(raw_diff_pct_str)
        except ValueError:
            diff_pct_val = 0.0

        if diff_pct_val < 0 and abs(diff_pct_val) > 0.5:
            diff_marker = "🔴"
        elif abs(diff_pct_val) > 2.0:
            diff_marker = "🟠⚠"
        elif abs(diff_pct_val) > 1.0:
            diff_marker = "⚠️"
        else:
            diff_marker = ""

        text += (
            f"PO #: {report_data.po_number}\n"
            f"Lot #: {getattr(report_data, 'lot_number', '') or ''}\n"
            f"Box type: {report_data.box_type}\n"
            f"Diameter (mm): {report_data.diameter}\n"
            f"Length (mm): {report_data.length}\n"
            f"PD (mmWg): {report_data.pd}\n"
            f"CU (Porosity): {report_data.cu if hasattr(report_data, 'cu') and report_data.cu else getattr(report_data, 'cu', 0)}\n"
            f"Weight (mg): {report_data.weight}\n\n"

            f"Box produced: {report_data.boxes_produced}\n"
            f"Produced rods: {report_data.produced_rods}\n"
            f"Machine counter: {report_data.machine_counter}\n"
            f"Difference: {report_data.difference}\n"
            f"Diff,%: {raw_diff_pct_str} {diff_marker}\n"
            f"Waste (kg): {report_data.waste_kg}\n"
            f"Machine efficiency %: {report_data.machine_efficiency}\n\n"

            f"Remarks: {report_data.remarks}"
        )

        # 4. Добавляем суммарный расход материалов (если хоть один > 0)
        if report_data.total_acetate or report_data.total_paper or report_data.total_pva or report_data.total_hm or report_data.total_triacetin:
            text += "\n\nTotal used:\n"
            text += f"Acetate: {report_data.total_acetate} kg | "
            text += f"Paper: {report_data.total_paper} Bob | "
            text += f"PVA Glue: {report_data.total_pva} kg | "
            text += f"Hot Melt Glue: {report_data.total_hm} kg | "
            text += f"Triacetin: {report_data.total_triacetin} kg"

        text += (
            f"\n\nTotal PO Produced: {total_produced_absolute}\n"
            f"Remaining to produce: {remaining_qty}"
        )

        # 5. Кладем в очередь и коммитим
        db.add(models.TelegramQueue(report_id=db_report.id, message_text=text))
        db.commit() # <-- Коммитим и отчет, и обновленный PO, и телеграм в одной транзакции!

        # PDF is now generated by Flutter app and sent via /api/reports/upload-pdf endpoint
        return {"status": "success", "report_id": db_report.id}
    except Exception as e:
        db.rollback()
        print(f"[ERROR] create_report failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- COMBINED SYNC ENDPOINT (report data + PDF in one call) ---
@app.post("/api/reports/sync")
def sync_report(
    payload: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Combined sync endpoint: accepts report JSON + optional PDF (base64).
    Saves the report to DB, updates PO counters, queues Telegram message,
    and queues PDF for Google Drive upload via ReportOutbox.
    
    Used by the Flutter app when syncing offline-submitted reports.
    """
    try:
        report_data = schemas.ReportCreate(**payload)

        # Idempotency guard: if the client already submitted this report, return it
        client_report_id = (report_data.client_report_id or "").strip()
        if client_report_id:
            existing = db.query(models.ProductionReport).filter(
                models.ProductionReport.client_report_id == client_report_id
            ).first()
            if existing:
                return {"status": "duplicate", "report_id": existing.id}
        
        # --- Same logic as create_report (save report + resolve materials) ---
        def resolve_material_fields(list_items, existing_type, existing_batch):
            material_type = (existing_type or "").strip()
            material_batch = (existing_batch or "").strip() or "No Batch"
            if list_items:
                for item in list_items:
                    if not isinstance(item, dict):
                        continue
                    candidate_type = str(item.get('type') or '').strip()
                    candidate_batch = str(item.get('batch') or '').strip() or "No Batch"
                    if candidate_type:
                        material_type = candidate_type
                        material_batch = candidate_batch
                        break
                if not material_type and list_items:
                    first_item = list_items[0]
                    if isinstance(first_item, dict):
                        material_type = str(first_item.get('type') or '').strip()
                        material_batch = str(first_item.get('batch') or '').strip() or "No Batch"
            return material_type, material_batch

        p = report_data.model_dump()
        acetate_list = p.pop('acetate_list', None)
        paper_list = p.pop('paper_list', None)
        pva_list = p.pop('pva_list', None)
        hm_list = p.pop('hm_list', None)
        tri_list = p.pop('tri_list', None)

        acetate_type, acetate_batch = resolve_material_fields(acetate_list, p.get('acetate_type', ''), p.get('acetate_batch', ''))
        paper_type, paper_batch = resolve_material_fields(paper_list, p.get('paper_type', ''), p.get('paper_batch', ''))
        pva_type, pva_batch = resolve_material_fields(pva_list, p.get('pva_glue_type', ''), p.get('pva_batch', ''))
        hm_type, hm_batch = resolve_material_fields(hm_list, p.get('hm_glue_type', ''), p.get('hm_batch', ''))
        tri_type, tri_batch = resolve_material_fields(tri_list, p.get('triacetin_type', ''), p.get('tri_batch', ''))

        p['acetate_type'] = acetate_type
        p['acetate_batch'] = acetate_batch
        p['paper_type'] = paper_type
        p['paper_batch'] = paper_batch
        p['pva_glue_type'] = pva_type
        p['pva_batch'] = pva_batch
        p['hm_glue_type'] = hm_type
        p['hm_batch'] = hm_batch
        p['triacetin_type'] = tri_type
        p['tri_batch'] = tri_batch
        try:
            p['materials_json'] = json.dumps({
                'acetate_list': acetate_list or [],
                'paper_list': paper_list or [],
                'pva_list': pva_list or [],
                'hm_list': hm_list or [],
                'tri_list': tri_list or [],
            })
        except Exception:
            p['materials_json'] = ''

        # 1. Save report to DB (sync_at always naive UTC).
        submitted_utc_sync = p.pop('submitted_at_utc', None)
        if submitted_utc_sync:
            if getattr(submitted_utc_sync, 'tzinfo', None) is not None:
                submitted_utc_sync = submitted_utc_sync.astimezone(timezone.utc).replace(tzinfo=None)
            p['sync_at'] = submitted_utc_sync
        else:
            p['sync_at'] = datetime.now(timezone.utc).replace(tzinfo=None)
        db_report = models.ProductionReport(**p)
        db.add(db_report)
        db.flush()
        shift_lifecycle_svc_link(db, db_report)

        # 2. Update PO produced_qty (excluding soft-deleted)
        # Lock the PO row first to serialize concurrent submissions for the same PO.
        po_to_update = db.query(models.PurchaseOrder).filter(
            models.PurchaseOrder.po_number == report_data.po_number
        ).with_for_update().first()

        total_sum_query = db.query(func.sum(models.ProductionReport.produced_rods))\
                            .filter(
                                models.ProductionReport.po_number == report_data.po_number,
                                or_(models.ProductionReport.is_deleted == False, models.ProductionReport.is_deleted == None),
                            )\
                            .scalar()
        total_produced_absolute = total_sum_query or 0
        if po_to_update:
            po_to_update.produced_qty = total_produced_absolute
            remaining_qty = po_to_update.target_qty - total_produced_absolute
        else:
            remaining_qty = 0

        # 3. Build Telegram text
        if report_data.shift_time_range:
            shift_display = f"{report_data.shift_name} ({report_data.shift_time_range})"
        else:
            shift_display = datetime.now().strftime("%H:%M:%S")
        
        if report_data.parent_report_id or report_data.edited_by:
            text = (
                f"Edited report from {report_data.report_date}/{report_data.shift_name}/{report_data.operator_name}/{report_data.machine_name}\n"
                f"Edited by: {report_data.edited_by or report_data.operator_name}\n"
                f"Date: {report_data.report_date}\n"
                f"Time: {shift_display}\n"
                f"Operator: {report_data.operator_name}\n"
                f"Machine #: {report_data.machine_name}\n\n"
            )
        else:
            text = (
                f"Production report submitted\n"
                f"Date: {report_data.report_date}\n"
                f"Time: {shift_display}\n"
                f"Operator: {report_data.operator_name}\n"
                f"Machine #: {report_data.machine_name}\n\n"
            )
        text += (
            f"PO #: {report_data.po_number}\n"
            f"Box produced: {report_data.boxes_produced}\n"
            f"Produced rods: {report_data.produced_rods}\n"
            f"Waste (kg): {report_data.waste_kg}\n"
            f"\nTotal PO Produced: {total_produced_absolute}\n"
            f"Remaining to produce: {remaining_qty}"
        )

        # 4. Queue Telegram in ReportOutbox (instead of TelegramQueue directly)
        db.add(models.ReportOutbox(
            report_id=db_report.id,
            delivery_type='telegram',
            payload_text=text,
            status='pending'
        ))

        # 5. Queue PDF for GDrive if provided
        pdf_base64_data = payload.get('pdf_base64', '') or payload.get('pdf_base64', '')
        pdf_filename = payload.get('pdf_filename', '') or payload.get('pdf_filename', '')
        if pdf_base64_data and len(pdf_base64_data) > 10:
            db.add(models.ReportOutbox(
                report_id=db_report.id,
                delivery_type='pdf_gdrive',
                payload_pdf_base64=pdf_base64_data,
                filename=pdf_filename or f"report_{db_report.id}.pdf",
                status='pending'
            ))
            print(f"📄 PDF queued for GDrive upload: report {db_report.id}")

        db.commit()

        return {
            "status": "success",
            "report_id": db_report.id,
            "pdf_queued": bool(pdf_base64_data and len(pdf_base64_data) > 10),
        }
    except Exception as e:
        db.rollback()
        print(f"[ERROR] sync_report failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- DELETE REPORT (soft-delete to bin) ---
@app.delete("/api/reports/{report_id}")
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Soft-delete a production report (moves to bin).
    Deleted reports still count in all statistics calculations.
    Requires: admin/superadmin role OR manager role OR user.can_edit_report.
    """
    db_report = db.query(models.ProductionReport).filter(
        models.ProductionReport.id == report_id
    ).first()
    if not db_report:
        raise HTTPException(status_code=404, detail="Report not found")

    user_role = current_user.role
    is_admin = user_role is not None and user_role.role_name.lower() in ("admin", "superadmin")
    is_manager = user_role is not None and user_role.role_name.lower() == "manager"
    can_delete = is_admin or is_manager or getattr(current_user, 'can_edit_report', False)

    if not can_delete:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to delete reports.",
        )

    db_report.is_deleted = True
    db_report.status = 'obsolete'
    db_report.deleted_by = current_user.username
    db_report.deleted_at = datetime.utcnow()

    # Log the deletion in audit trail
    import json as _json
    edit_log = models.ReportEditLog(
        report_id=db_report.id,
        user_id=current_user.id,
        username=current_user.username,
        changed_fields=_json.dumps(["is_deleted"], ensure_ascii=False),
        old_values=_json.dumps({"is_deleted": "False"}, ensure_ascii=False),
        new_values=_json.dumps({"is_deleted": "True"}, ensure_ascii=False),
    )
    db.add(edit_log)
    audit_log = models.ReportAuditLog(
        report_id=db_report.id,
        user_id=current_user.id,
        username=current_user.username,
        action="DELETED",
        changed_fields=_json.dumps({"is_deleted": {"old": "False", "new": "True"}}, ensure_ascii=False),
    )
    db.add(audit_log)
    db.commit()

    return {"status": "success", "report_id": report_id, "deleted_by": current_user.username}


@app.post("/api/reports/{report_id}/restore")
def restore_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Restore a soft-deleted report from the bin.
    Requires: admin/superadmin role OR manager role OR user.can_edit_report.
    """
    db_report = db.query(models.ProductionReport).filter(
        models.ProductionReport.id == report_id
    ).first()
    if not db_report:
        raise HTTPException(status_code=404, detail="Report not found")

    user_role = current_user.role
    is_admin = user_role is not None and user_role.role_name.lower() in ("admin", "superadmin")
    is_manager = user_role is not None and user_role.role_name.lower() == "manager"
    can_restore = is_admin or is_manager or getattr(current_user, 'can_edit_report', False)

    if not can_restore:
        raise HTTPException(status_code=403, detail="You do not have permission to restore reports.")

    db_report.is_deleted = False
    db_report.deleted_by = None
    db_report.deleted_at = None

    import json as _json
    edit_log = models.ReportEditLog(
        report_id=db_report.id,
        user_id=current_user.id,
        username=current_user.username,
        changed_fields=_json.dumps(["is_deleted"], ensure_ascii=False),
        old_values=_json.dumps({"is_deleted": "True"}, ensure_ascii=False),
        new_values=_json.dumps({"is_deleted": "False"}, ensure_ascii=False),
    )
    db.add(edit_log)
    audit_log = models.ReportAuditLog(
        report_id=db_report.id,
        user_id=current_user.id,
        username=current_user.username,
        action="RESTORED",
        changed_fields=_json.dumps({"is_deleted": {"old": "True", "new": "False"}}, ensure_ascii=False),
    )
    db.add(audit_log)
    db.commit()

    return {"status": "success", "report_id": report_id, "restored_by": current_user.username}


@app.get("/api/reports/deleted")
def get_deleted_reports(
    po_number: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Returns soft-deleted reports (bin).
    Optionally filter by po_number.
    """
    query = db.query(models.ProductionReport).filter(
        models.ProductionReport.is_deleted == True
    )
    if po_number:
        query = query.filter(models.ProductionReport.po_number == po_number)
    reports = query.order_by(models.ProductionReport.deleted_at.desc()).all()

    result = []
    for report in reports:
        report_item = {col.name: getattr(report, col.name) for col in report.__table__.columns}
        if report_item.get('sync_at') is not None:
            sync_val = report_item['sync_at']
            if hasattr(sync_val, 'isoformat'):
                report_item['sync_at'] = sync_val.strftime('%Y-%m-%dT%H:%M:%SZ')
        try:
            if getattr(report, 'materials_json', None):
                parsed = json.loads(report.materials_json or "{}")
                report_item['acetate_list'] = parsed.get('acetate_list', [])
                report_item['paper_list'] = parsed.get('paper_list', [])
                report_item['pva_list'] = parsed.get('pva_list', [])
                report_item['hm_list'] = parsed.get('hm_list', [])
                report_item['tri_list'] = parsed.get('tri_list', [])
        except Exception:
            pass
        result.append(report_item)
    return result


# --- UPDATE / ARCHIVE REPORT ---
EDITABLE_REPORT_FIELDS = {
    # Production output
    "boxes_produced", "waste_kg", "produced_rods", "machine_counter",
    # Materials
    "acetate_type", "acetate_batch", "paper_type", "paper_batch",
    "pva_glue_type", "pva_batch", "hm_glue_type", "hm_batch",
    "triacetin_type", "tri_batch",
    # General info
    "operator_name", "po_number", "report_date", "shift_name",
    "machine_name", "shift_time_range",
    # Technical specs
    "box_type", "diameter", "length", "pd", "weight", "cu",
    "lot_number",
    # Calculated fields
    "machine_efficiency", "difference", "diff_percent",
    "efficiency_box_min",
    # Material totals
    "total_acetate", "total_paper", "total_pva", "total_hm",
    "total_triacetin",
    # Metadata
    "materials_json", "remarks", "is_archived",
    "is_modified_manually",
}


@app.put("/api/reports/{report_id}")
def update_report(
    report_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Update a production report. Requires authentication.
    
    - Archive/unarchive (is_archived): any authenticated user can do this.
    - Editing production fields: requires can_edit_report permission OR
      role name in ('admin', 'superadmin').
    
    All edits are logged to report_edit_log for immutable audit trail.
    """
    db_report = db.query(models.ProductionReport).filter(
        models.ProductionReport.id == report_id
    ).first()
    if not db_report:
        raise HTTPException(status_code=404, detail="Report not found")

    user_role = current_user.role
    is_admin = (
        user_role is not None
        and user_role.role_name.lower() in ("admin", "superadmin")
    )
    can_edit = is_admin or (user_role is not None and user_role.can_edit_report)

    # Separate archive-only keys from content-editing keys
    archive_keys = {"is_archived"}
    editing_keys = set(payload.keys()) - archive_keys

    # If the payload contains editing fields, require edit permission
    if editing_keys and not can_edit:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to edit report data. "
                   "Required: can_edit_report or admin/superadmin role.",
        )

    # Apply only the allowed editable fields present in the payload
    # For archive-only requests, allow is_archived through always
    applicable_fields = EDITABLE_REPORT_FIELDS if editing_keys else EDITABLE_REPORT_FIELDS | archive_keys

    # The MO / machine of a report that belongs to a production run must change
    # together with the run, its QC checks and the shift summary: only the audited
    # supervisor endpoint (POST /api/v2/runs/{id}/reassign) may do that.
    if db_report.run_id is not None:
        for locked in ("po_number", "machine_name"):
            if locked in payload and str(payload[locked]) != str(getattr(db_report, locked, None)):
                raise HTTPException(
                    status_code=409,
                    detail=f"'{locked}' is bound to production run {db_report.run_id}; "
                           f"use POST /api/v2/runs/{db_report.run_id}/reassign instead.",
                )

    changed_fields = []
    old_values = {}
    new_values = {}

    for key, value in payload.items():
        if key in applicable_fields and key != 'id':
            old_val = getattr(db_report, key, None)
            # Normalize for comparison
            if isinstance(old_val, (int, float)) and isinstance(value, (int, float)):
                if old_val == value:
                    continue
            elif str(old_val) == str(value):
                continue
            changed_fields.append(key)
            old_values[key] = str(old_val) if old_val is not None else None
            new_values[key] = str(value) if value is not None else None
            setattr(db_report, key, value)

    if changed_fields:
        db_report.is_modified_manually = True
        db_report.status = "edited"
        # Editing invalidates any prior verification — data must be re-approved.
        db_report.verification_status = "pending"
        db_report.verified_by = None
        db_report.verified_at = None

    db.commit()
    db.refresh(db_report)

    # Log the edit to the immutable audit trail
    if changed_fields:
        import json as _json
        edit_log = models.ReportEditLog(
            report_id=db_report.id,
            user_id=current_user.id,
            username=current_user.username,
            changed_fields=_json.dumps(changed_fields, ensure_ascii=False),
            old_values=_json.dumps(old_values, ensure_ascii=False),
            new_values=_json.dumps(new_values, ensure_ascii=False),
        )
        db.add(edit_log)
        # Also record a high-level audit log entry
        audit_diff = {}
        for f in changed_fields:
            audit_diff[f] = {"old": old_values.get(f), "new": new_values.get(f)}
        audit_log = models.ReportAuditLog(
            report_id=db_report.id,
            user_id=current_user.id,
            username=current_user.username,
            action="EDITED",
            changed_fields=_json.dumps(audit_diff, ensure_ascii=False),
        )
        db.add(audit_log)
        db.commit()

    return {
        "status": "success",
        "report_id": db_report.id,
        "changed_fields": changed_fields,
    }


def _attach_production_report_async(report_id: int) -> None:
    """Best-effort: attach the Production Report PDF to the report's Odoo MO.

    Runs in a daemon thread after a report is approved, so a slow or unreachable Odoo
    never blocks the approval response. Failures are logged, never raised.
    """
    try:
        from app.pdf_generator import PDFReportGenerator, report_to_dict
        from app.services.odoo import legacy_push
        from app.services.odoo.client import OdooClient, OdooConfig

        cfg = OdooConfig.from_env()
        if not (cfg.enabled and cfg.valid()):
            return
        db = SessionLocal()
        try:
            report = db.query(models.ProductionReport).get(report_id)
            if report is None:
                return
            po = db.query(models.PurchaseOrder).filter(
                models.PurchaseOrder.po_number == report.po_number).first()
            if po is None or not po.odoo_mo_id:
                return
            client = OdooClient(cfg)
            client.connect()
            mo = legacy_push.resolve_report_mo(client, po, report.produced_rods)
            if mo is None:
                print(f"[Odoo] production-report attach skipped (no unique MO) for report {report_id}")
                return
            mo_id, mo_name = mo
            pdf = PDFReportGenerator().generate_pdf_bytes(report_to_dict(report))
            if not pdf:
                return
            safe = legacy_push.safe_name(mo_name)
            client.attach_file(
                f"Production_Report_{safe}_#{report.id}.pdf",
                "mrp.production", mo_id, pdf, "application/pdf",
            )
            print(f"[Odoo] attached production report #{report.id} to {mo_name}")
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - must never affect approval
        print(f"[Odoo] production-report attach failed for report {report_id}: {exc}")


@app.post("/api/reports/{report_id}/verify")
def verify_report(
    report_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Human-in-the-loop verification of operator-entered report data.

    A supervisor/admin approves (``{"action": "approve"}``) or rejects
    (``{"action": "reject"}``) the report. Only approved reports are considered
    authoritative for Odoo sync. Rejecting keeps the record but marks it out of
    the verified set; the operator/admin can correct and re-submit for approval.
    """
    db_report = db.query(models.ProductionReport).filter(
        models.ProductionReport.id == report_id
    ).first()
    if not db_report:
        raise HTTPException(status_code=404, detail="Report not found")

    user_role = current_user.role
    is_admin = (
        user_role is not None
        and user_role.role_name.lower() in ("admin", "superadmin")
    )
    can_verify = is_admin or (user_role is not None and user_role.can_edit_report)
    if not can_verify:
        raise HTTPException(
            status_code=403,
            detail="Only admin/superadmin (or can_edit_report) may verify reports.",
        )

    action = str(payload.get("action", "")).strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    db_report.verification_status = "approved" if action == "approve" else "rejected"
    db_report.verified_by = current_user.username
    db_report.verified_at = datetime.utcnow()
    db.commit()

    import json as _json
    audit_log = models.ReportAuditLog(
        report_id=db_report.id,
        user_id=current_user.id,
        username=current_user.username,
        action="VERIFIED" if action == "approve" else "REJECTED",
        changed_fields=_json.dumps({"verification_status": db_report.verification_status}),
    )
    db.add(audit_log)
    db.commit()

    if action == "approve":
        # Dispatch the run to Odoo immediately: the approved report is authoritative
        # even while the shift is still open (a shift may span multiple orders).
        if db_report.run_id:
            try:
                from app.services.odoo import outbound as odoo_outbound
                odoo_outbound.enqueue_run_dispatch(db, db_report.run_id)
                db.commit()
            except Exception as exc:  # noqa: BLE001 - approval must never fail
                print(f"[Odoo] run dispatch enqueue failed for report {db_report.id}: {exc}")

    return {
        "status": "success",
        "report_id": db_report.id,
        "verification_status": db_report.verification_status,
        "verified_by": db_report.verified_by,
    }


@app.get("/api/reports/{report_id}/logs")
def get_report_audit_logs(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Returns the high-level audit log (CREATED, EDITED, DELETED, RESTORED)
    for a specific report, sorted by created_at DESC. Includes editor username.
    Requires authentication.
    """
    db_report = db.query(models.ProductionReport).filter(
        models.ProductionReport.id == report_id
    ).first()
    if not db_report:
        raise HTTPException(status_code=404, detail="Report not found")

    logs = (
        db.query(models.ReportAuditLog)
        .filter(models.ReportAuditLog.report_id == report_id)
        .order_by(models.ReportAuditLog.created_at.desc())
        .all()
    )

    import json as _json

    return {
        "report_id": report_id,
        "logs": [
            {
                "id": l.id,
                "username": l.username,
                "action": l.action,
                "changed_fields": _json.loads(l.changed_fields) if l.changed_fields else None,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }


@app.get("/api/reports/{report_id}/edits")
def get_report_edits(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Returns the edit history for a specific report.
    Requires authentication.
    """
    db_report = db.query(models.ProductionReport).filter(
        models.ProductionReport.id == report_id
    ).first()
    if not db_report:
        raise HTTPException(status_code=404, detail="Report not found")

    edits = (
        db.query(models.ReportEditLog)
        .filter(models.ReportEditLog.report_id == report_id)
        .order_by(models.ReportEditLog.edited_at.desc())
        .all()
    )

    import json as _json

    return {
        "report_id": report_id,
        "edits": [
            {
                "id": e.id,
                "username": e.username,
                "changed_fields": _json.loads(e.changed_fields),
                "old_values": _json.loads(e.old_values),
                "new_values": _json.loads(e.new_values),
                "edited_at": e.edited_at.isoformat() if e.edited_at else None,
            }
            for e in edits
        ],
    }

def _coerce_report_value(col_type, value):
    """Coerce a stringified audit value back to the column's Python type."""
    if value is None:
        return None
    type_name = str(col_type).lower()
    if any(t in type_name for t in ("integer", "bigint", "smallint")):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
    if any(t in type_name for t in ("float", "numeric", "double", "decimal")):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if "bool" in type_name:
        return str(value).strip().lower() in ("true", "1", "yes", "t")
    return value


# Fields that are lifecycle/identity flags and must never be "restored" back to
# an earlier snapshot (archive state, verification, soft-delete, timestamps, ...).
_REVERT_EXCLUDED_FIELDS = {
    "id", "client_report_id", "is_archived", "is_deleted", "deleted_by",
    "deleted_at", "status", "verification_status", "verified_by", "verified_at",
    "edited_by", "edited_at", "parent_report_id", "parent_local_report_id",
    "sync_at", "submitted_at_utc", "timezone_offset", "shift_id", "run_id",
    "is_modified_manually",
}


@app.post("/api/reports/{report_id}/revert")
def revert_report_to_original(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Revert a production report to its original (pre-edit) values.

    Reconstructs the initial value of every data field from the immutable
    ``ReportEditLog`` history (the earliest ``old_values`` per field), applies
    them, resets the report to ``status='original'`` and forces re-verification,
    then writes a ``RESTORED`` audit log entry.

    Requires: admin/superadmin role OR user.can_edit_report.
    """
    db_report = db.query(models.ProductionReport).filter(
        models.ProductionReport.id == report_id
    ).first()
    if not db_report:
        raise HTTPException(status_code=404, detail="Report not found")

    user_role = current_user.role
    is_admin = (
        user_role is not None
        and user_role.role_name.lower() in ("admin", "superadmin")
    )
    can_edit = is_admin or (user_role is not None and user_role.can_edit_report)
    if not can_edit:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to revert report data. "
                   "Required: can_edit_report or admin/superadmin role.",
        )

    edits = (
        db.query(models.ReportEditLog)
        .filter(models.ReportEditLog.report_id == report_id)
        .order_by(models.ReportEditLog.edited_at.asc())
        .all()
    )
    if not edits:
        raise HTTPException(status_code=400, detail="Report has no edit history to revert.")

    columns = models.ProductionReport.__table__.columns

    # Earliest recorded old_value wins -> the value before any edit was applied.
    original = {}
    for e in edits:
        try:
            old_values = json.loads(e.old_values) if e.old_values else {}
        except Exception:
            old_values = {}
        if not isinstance(old_values, dict):
            continue
        for field, val in old_values.items():
            if field in original:
                continue
            if field in _REVERT_EXCLUDED_FIELDS:
                continue
            if field not in columns:
                continue
            original[field] = val

    if not original:
        raise HTTPException(status_code=400, detail="Nothing to revert.")

    changed = {}
    for field, val in original.items():
        col = columns[field]
        new_val = _coerce_report_value(col.type, val)
        old_val = getattr(db_report, field, None)
        if str(old_val) == str(new_val):
            continue
        setattr(db_report, field, new_val)
        changed[field] = {"old": old_val, "new": new_val}

    db_report.status = "original"
    db_report.verification_status = "pending"
    db_report.verified_by = None
    db_report.verified_at = None
    db_report.is_modified_manually = False

    db.commit()
    db.refresh(db_report)

    if changed:
        import json as _json
        edit_log = models.ReportEditLog(
            report_id=db_report.id,
            user_id=current_user.id,
            username=current_user.username,
            changed_fields=_json.dumps(list(changed.keys()), ensure_ascii=False),
            old_values=_json.dumps(
                {f: (str(v["old"]) if v["old"] is not None else None) for f, v in changed.items()},
                ensure_ascii=False,
            ),
            new_values=_json.dumps(
                {f: (str(v["new"]) if v["new"] is not None else None) for f, v in changed.items()},
                ensure_ascii=False,
            ),
        )
        db.add(edit_log)
        audit_diff = {
            f: {"old": str(v["old"]) if v["old"] is not None else None,
                "new": str(v["new"]) if v["new"] is not None else None}
            for f, v in changed.items()
        }
        audit_log = models.ReportAuditLog(
            report_id=db_report.id,
            user_id=current_user.id,
            username=current_user.username,
            action="RESTORED",
            changed_fields=_json.dumps(audit_diff, ensure_ascii=False),
        )
        db.add(audit_log)
        db.commit()

    return {
        "status": "success",
        "report_id": db_report.id,
        "restored_fields": list(changed.keys()),
        "verification_status": db_report.verification_status,
    }


# --- LAST REPORT BY MACHINE (for "copy from previous" feature) ---
@app.get("/api/reports/last-by-machine")
def get_last_report_by_machine(machine_name: str, db: Session = Depends(get_db)):
    """
    Returns the most recent production report for a given machine.
    Query parameter: machine_name (supports any characters including # / spaces)
    Used by the Flutter app to pre-fill the new report form.
    """
    report = db.query(models.ProductionReport)\
        .filter(models.ProductionReport.machine_name == machine_name)\
        .order_by(models.ProductionReport.id.desc())\
        .first()

    if not report:
        raise HTTPException(status_code=404, detail="No reports found for this machine")

    report_item = {col.name: getattr(report, col.name) for col in report.__table__.columns}

    # Include material lists from materials_json if available
    try:
        if getattr(report, 'materials_json', None):
            parsed = json.loads(report.materials_json or "{}")
            report_item['acetate_list'] = parsed.get('acetate_list', [])
            report_item['paper_list'] = parsed.get('paper_list', [])
            report_item['pva_list'] = parsed.get('pva_list', [])
            report_item['hm_list'] = parsed.get('hm_list', [])
            report_item['tri_list'] = parsed.get('tri_list', [])
            return report_item
    except Exception:
        pass

    # Fallback: build single-item lists from stored fields
    def build_list(m_type, m_batch, total):
        if total and total > 0:
            return [{"type": m_type or "", "batch": m_batch or "No Batch", "used": round(total, 2)}]
        return []

    report_item['acetate_list'] = build_list(report.acetate_type, report.acetate_batch, report.total_acetate)
    report_item['paper_list'] = build_list(report.paper_type, report.paper_batch, report.total_paper)
    report_item['pva_list'] = build_list(report.pva_glue_type, report.pva_batch, report.total_pva)
    report_item['hm_list'] = build_list(report.hm_glue_type, report.hm_batch, report.total_hm)
    report_item['tri_list'] = build_list(report.triacetin_type, report.tri_batch, report.total_triacetin)

    return report_item

# --- APP UPDATE ENDPOINTS ---
import glob
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse as _FileResponse

def _get_latest_apk_info():
    """
    Scans APK_RELEASES_DIR for the newest APK file.
    Tries to extract versionName and versionCode using androguard.
    Falls back to parsing the filename (prod_log_v1.0.3_b4.apk).
    Returns dict with version_name, build_number, apk_path or None.
    """
    apk_dir = os.environ.get("APK_RELEASES_DIR", "./apk_releases")
    os.makedirs(apk_dir, exist_ok=True)
    apk_files = sorted(glob.glob(os.path.join(apk_dir, "*.apk")), key=os.path.getmtime, reverse=True)
    if not apk_files:
        return None

    apk_path = apk_files[0]
    version_name = "unknown"
    build_number = 0

    # Try androguard first
    try:
        from androguard.core.bytecodes.apk import APK
        apk = APK(apk_path)
        version_name = apk.get_androidversion_name() or "unknown"
        build_number = int(apk.get_androidversion_code() or 0)
    except Exception:
        # Fallback: parse filename like prod_log_v1.0.3_b4.apk
        import re
        fname = os.path.basename(apk_path)
        m = re.search(r'v([\d.]+)_b(\d+)', fname)
        if m:
            version_name = m.group(1)
            build_number = int(m.group(2))

    return {
        "version_name": version_name,
        "build_number": build_number,
        "apk_path": apk_path,
        "filename": os.path.basename(apk_path),
    }


@app.get("/api/app/latest-version")
def get_latest_app_version():
    """
    Returns the latest APK version info.
    Flutter app calls this on startup to check if an update is available.
    """
    info = _get_latest_apk_info()
    if not info:
        raise HTTPException(status_code=404, detail="No APK release found on server")

    return {
        "version_name": info["version_name"],
        "build_number": info["build_number"],
        "filename": info["filename"],
        "download_url": f"/api/app/download",
    }


@app.get("/api/app/download")
def download_latest_apk():
    """
    Streams the latest APK file for download/install on Android devices.
    """
    info = _get_latest_apk_info()
    if not info:
        raise HTTPException(status_code=404, detail="No APK release found on server")

    return FileResponse(
        path=info["apk_path"],
        media_type="application/vnd.android.package-archive",
        filename=info["filename"],
    )


# Статистика и аудит по заказам
@app.get("/api/stats/po-audit/{po_id}")
def get_po_audit_summary(po_id: int, db: Session = Depends(get_db)):
    print(f"--- SERVER: Запрос аудита отчетов для PO ID: {po_id} ---")

    # 1. Получаем сам заказ
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Заказ (PO) не найден")

    # 2. Ищем отчеты по po_number (так как в самих ОТ хранится строка, а не ID)
    # EXCLUDE soft-deleted reports from analytics
    reports = db.query(models.ProductionReport).filter(
        models.ProductionReport.po_number == po.po_number,
        or_(models.ProductionReport.is_deleted == False, models.ProductionReport.is_deleted == None),
    ).all()

    if not reports:
        return {
            "po_id": po.id,
            "po_number": po.po_number,
            "msg": "По данному заказу отчетов еще нет."
        }

    # 3. Считаем итоги по отчетам
    total_rods = 0
    total_boxes = 0
    total_waste = 0.0

    # Собираем счетчики
    counters = [r.machine_counter for r in reports if r.machine_counter and r.machine_counter > 0]
    mc_start = min(counters) if counters else 0
    mc_end = max(counters) if counters else 0
    mc_diff = mc_end - mc_start if counters else 0

    # Собираем данные по материалам. Ключ: (Категория, Тип, Сорт, Единица измерения)
    materials_dict = {}

    def add_material(cat, m_type, m_batch, val, unit):
        if val and val > 0:
            key = (cat, m_type, m_batch, unit)
            materials_dict[key] = materials_dict.get(key, 0.0) + val

    report_rows = []

    for r in reports:
        total_rods += (r.produced_rods or 0)
        total_boxes += (r.boxes_produced or 0)
        total_waste += (r.waste_kg or 0.0)

        shift_time = getattr(r, 'shift_time_range', None)
        if not shift_time:
            start = getattr(r, 'start_time', '') or ''
            end = getattr(r, 'end_time', '') or ''
            shift_time = f"{start} - {end}".strip()

        operator_name = getattr(r, 'operator_name', None) or getattr(r, 'operator', None) or 'Unknown'
        raw_machine_counter = getattr(r, 'machine_counter', 0) or 0
        raw_produced_rods = getattr(r, 'produced_rods', 0) or 0
        raw_difference = getattr(r, 'difference', None)
        if raw_difference is None:
            raw_difference = raw_machine_counter - raw_produced_rods
        raw_diff_percent = getattr(r, 'diff_percent', None)
        if raw_diff_percent is None:
            raw_diff_percent = 0.0

        report_rows.append({
            'id': r.id,
            'date': str(getattr(r, 'report_date', '') or ''),
            'time': shift_time,
            'operator': operator_name,
            'produced_rods': raw_produced_rods,
            'machine_counter': raw_machine_counter,
            'difference': raw_difference,
            'diff_percent': raw_diff_percent,
            'scrap': getattr(r, 'waste_kg', 0.0) or 0.0,
        })

        # Если в отчете есть materials_json (новый формат), читаем из него.
        # Если нет materials_json, читаем из плоских колонок PO.
        ac_type = getattr(r, 'acetate_type', po.acetate_type) or "Unknown Acetate"
        pap_type = getattr(r, 'paper_type', po.paper_type) or "Unknown Paper"
        pva_type = getattr(r, 'pva_glue_type', po.pva_glue_type) or "Unknown PVA"
        hm_type = getattr(r, 'hm_glue_type', po.hm_glue_type) or "Unknown Hot Melt"
        tri_type = getattr(r, 'triacetin_type', po.triacetin_type) or "Unknown Triacetin"

        # Сорта (если есть)
        ac_batch = getattr(r, 'acetate_batch', 'No Batch')
        pap_batch = getattr(r, 'paper_batch', 'No Batch')
        pva_batch = getattr(r, 'pva_batch', 'No Batch')
        hm_batch = getattr(r, 'hm_batch', 'No Batch')
        tri_batch = getattr(r, 'tri_batch', 'No Batch')

        # Добавляем расходы материалов
        add_material("Acetate", ac_type, ac_batch, getattr(r, 'total_acetate', 0), "kg")
        add_material("Paper", pap_type, pap_batch, getattr(r, 'total_paper', 0), "Bob")
        add_material("PVA Glue", pva_type, pva_batch, getattr(r, 'total_pva', 0), "kg")
        add_material("Hot Melt", hm_type, hm_batch, getattr(r, 'total_hm', 0), "kg")
        add_material("Triacetin", tri_type, tri_batch, getattr(r, 'total_triacetin', 0), "kg")

    # Преобразуем накопленные данные в список для JSON
    materials_used = []
    for (cat, m_type, m_batch, unit), amount in materials_dict.items():
        materials_used.append({
            "category": cat,
            "type": m_type,
            "batch": m_batch,
            "consumed": round(amount, 2),
            "unit": unit
        })

    # Сортируем материалы по категории, чтобы выглядело "красиво"
    materials_used.sort(key=lambda x: x["category"])


    # --- НОВАЯ ДРЕВОВИДНАЯ СТРУКТУРА ---
    # Строим структуру, которая группирует по "дереву категорий"
    material_tree = {}

    for r in reports:
        # Try to read per-batch material data from materials_json first (new format)
        mj = getattr(r, 'materials_json', None)
        parsed_mj = None
        if mj:
            try:
                parsed_mj = json.loads(mj)
            except Exception:
                parsed_mj = None

        def _add_from_list(cat, items, unit):
            """Add per-batch items from materials_json list into material_tree."""
            if not items:
                return
            for item in items:
                t_name = (item.get('type') or item.get('material_type') or 'Unknown').strip()
                b_name = (item.get('batch') or 'No Batch').strip() or 'No Batch'
                # 'used' field preferred; fallback: start - stop
                used = item.get('used')
                if used is None:
                    try:
                        used = float(item.get('start', 0) or 0) - float(item.get('stop', 0) or 0)
                    except Exception:
                        used = 0.0
                try:
                    used = float(used)
                except Exception:
                    used = 0.0
                if used > 0:
                    if cat not in material_tree:
                        material_tree[cat] = {"unit": unit, "types": {}}
                    if t_name not in material_tree[cat]["types"]:
                        material_tree[cat]["types"][t_name] = {}
                    material_tree[cat]["types"][t_name][b_name] = \
                        material_tree[cat]["types"][t_name].get(b_name, 0.0) + used

        if parsed_mj:
            # New format: read per-batch lists
            _add_from_list("Acetate",  parsed_mj.get('acetate_list', []), "kg")
            _add_from_list("Paper",    parsed_mj.get('paper_list',   []), "Bob")
            _add_from_list("PVA Glue", parsed_mj.get('pva_list',     []), "kg")
            _add_from_list("Hot Melt", parsed_mj.get('hm_list',      []), "kg")
            _add_from_list("Triacetin",parsed_mj.get('tri_list',     []), "kg")
        else:
            # Old format: flat total columns
            materials_data = [
                ("Acetate",  getattr(r, 'acetate_type',  po.acetate_type  or "Unknown"), getattr(r, 'acetate_batch', "No Batch"), r.total_acetate,  "kg"),
                ("Paper",    getattr(r, 'paper_type',    po.paper_type    or "Unknown"), getattr(r, 'paper_batch',   "No Batch"), r.total_paper,    "Bob"),
                ("PVA Glue", getattr(r, 'pva_glue_type', po.pva_glue_type or "Unknown"), getattr(r, 'pva_batch',    "No Batch"), r.total_pva,      "kg"),
                ("Hot Melt", getattr(r, 'hm_glue_type',  po.hm_glue_type  or "Unknown"), getattr(r, 'hm_batch',    "No Batch"), r.total_hm,       "kg"),
                ("Triacetin",getattr(r, 'triacetin_type',po.triacetin_type or "Unknown"), getattr(r, 'tri_batch',   "No Batch"), r.total_triacetin,"kg"),
            ]
            for cat, t_name, b_name, val, unit in materials_data:
                if val and val > 0:
                    if cat not in material_tree:
                        material_tree[cat] = {"unit": unit, "types": {}}
                    if t_name not in material_tree[cat]["types"]:
                        material_tree[cat]["types"][t_name] = {}
                    material_tree[cat]["types"][t_name][b_name] = \
                        material_tree[cat]["types"][t_name].get(b_name, 0.0) + val

    # Формируем структурированный JSON с промежуточными итогами
    structured_materials_json = []

    for cat, cat_data in material_tree.items():
        category_total = 0.0
        types_list = []

        for t_name, batches_dict in cat_data["types"].items():
            type_total = sum(batches_dict.values())
            category_total += type_total

            batches_list = []
            for b_name, b_val in batches_dict.items():
                batches_list.append({
                    "batch_number": b_name,
                    "consumed": round(b_val, 2)
                })

            types_list.append({
                "type_name": t_name,
                "type_total": round(type_total, 2),
                "batches": batches_list
            })

        structured_materials_json.append({
            "category": cat,
            "category_total": round(category_total, 2),
            "unit": cat_data["unit"],
            "breakdown": types_list
        })

    # Считаем оставшееся количество
    remaining_qty = po.target_qty - total_rods

    # Считаем расхождение счетчика и отчетов (Фикция)
    # Расхождение счетчика = в счетчике "больше" чем в отчетах (недосчитанные)
    # Отрицательное значение = в счетчике меньше чем в отчетах (пересчитанные без счетчика)
    discrepancy = total_rods - mc_diff

    # 5. Возвращаем ответ сервера
    return {
        "po_id": po.id,
        "po_number": po.po_number,
        "target_qty": po.target_qty,
        "produced_qty": total_rods,
        "remaining_qty": remaining_qty,
        "audit_totals": {
            "total_boxes_submitted": total_boxes,
            "total_rods_produced": total_rods,
            "total_waste_kg": round(total_waste, 2),
            "machine_counter_value": mc_end,
            "machine_counter_difference": mc_diff,
            "discrepancy_boxes_vs_machine": discrepancy
        },
        "report_rows": report_rows,
        "materials_consumed": structured_materials_json # Наш новый древовидный массив
    }

# =============================================================================
# FLUTTER WEB SPA — must be registered LAST so all /api/* routes take priority
# =============================================================================
# Flutter web build lives in the sibling frontend/ folder; override with WEB_BUILD_DIR.
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
