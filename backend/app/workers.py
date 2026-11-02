"""Background workers as a standalone process (ROADMAP A4).

Until 2026-10-29 these six polling loops were defined in ``main.py`` and started
as daemon threads at IMPORT time, i.e. inside the web process. With multiple
uvicorn workers every process duplicated them (double Telegram sends, double
Odoo dispatches, ...).

Now the web process starts them from its lifespan UNLESS
``MES_RUN_BACKGROUND_WORKERS`` is set to ``0``/``false``, and a dedicated
process can run them alone:

    python -m app.workers

The station watcher and the interactive Telegram bot intentionally stay in the
web process (they are async and/or interactive).
"""

import os
import sys
import time
import base64
import tempfile
import threading
import importlib
from datetime import datetime, timedelta

import requests

if __package__:
    models = importlib.import_module(f"{__package__}.models")
    database_mod = importlib.import_module(f"{__package__}.database")
    pdf_gen = importlib.import_module(f"{__package__}.pdf_generator")
    SessionLocal = database_mod.SessionLocal
    PDFReportGenerator = pdf_gen.PDFReportGenerator
else:
    import models
    from database import SessionLocal
    from pdf_generator import PDFReportGenerator


def workers_enabled() -> bool:
    """False when a dedicated worker process runs the loops (web then skips them)."""
    raw = os.getenv("MES_RUN_BACKGROUND_WORKERS", "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "disabled")


# --- TELEGRAM BACKGROUND WORKER (legacy telegram_queue) ------------------------
def telegram_worker():
    """Background thread that sends queued Telegram messages."""
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
            print(f"Worker error: {e}")
        finally:
            db.close()
        time.sleep(30)


# --- PDF GOOGLE DRIVE BACKGROUND UPLOADER --------------------------------------
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


# --- TELEGRAM OUTBOX WORKER (report_outbox delivery_type='telegram') -----------
def telegram_outbox_worker():
    """Background thread that sends Telegram messages queued in report_outbox."""
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


# --- ODOO DISPATCHER (processes odoo_outbox pending items) ---------------------
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


# --- ODOO RECONCILER (re-reads the MO chain of linked, unfinished orders) ------
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


# --- SHIFT AUTO-CLOSE (IN_PROGRESS -> AUTO_CLOSED once scheduled end passes +30min)
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


# --- SHIFT SUMMARY RECOMPUTE (A7: rebuild summaries flagged stale) --------------
def shift_summary_recompute_worker():
    """Rebuild shift summaries flagged stale (e.g. after a run reassign).

    Writes a NEW version per stale shift (history preserved) and re-enqueues the
    fresh payload for Odoo so the ERP always converges to the corrected data.
    """
    from app.services import aggregation
    from app.services.odoo import outbound as odoo_outbound

    time.sleep(120)  # let the app finish starting
    while True:
        db = SessionLocal()
        try:
            done = aggregation.recompute_stale_summaries(db)
            for item in done:
                odoo_outbound.enqueue_shift_summary(
                    db, item["shift_id"], item["version"], item["payload"])
                print(f"[Shift] recomputed stale summary shift={item['shift_id']} "
                      f"-> v{item['version']}")
            if done:
                db.commit()
        except Exception as e:
            db.rollback()
            print(f"[Shift] summary recompute error: {e}")
        finally:
            db.close()
        time.sleep(300)


WORKER_THREADS = (
    telegram_worker,
    telegram_outbox_worker,
    gdrive_worker,
    odoo_dispatcher_worker,
    odoo_reconcile_worker,
    shift_auto_close_worker,
    shift_summary_recompute_worker,
)


def start_background_workers() -> list:
    """Start every polling worker as a daemon thread; returns the threads."""
    threads = []
    for fn in WORKER_THREADS:
        t = threading.Thread(target=fn, daemon=True, name=fn.__name__)
        t.start()
        threads.append(t)
    print(f"[Workers] started {len(threads)} background worker(s) in-process")
    return threads


def main() -> None:
    """CLI entrypoint: run ONLY the background workers (no web server).

    Usage: python -m app.workers
    Pair with MES_RUN_BACKGROUND_WORKERS=0 in the web process's environment.
    """
    if not workers_enabled():
        print("[Workers] MES_RUN_BACKGROUND_WORKERS is disabled - exiting.")
        sys.exit(0)
    threads = start_background_workers()
    print("[Workers] dedicated worker process running (Ctrl+C to stop).")
    try:
        for t in threads:
            while t.is_alive():
                t.join(timeout=10)
    except KeyboardInterrupt:
        print("[Workers] shutting down.")


if __name__ == "__main__":
    main()
