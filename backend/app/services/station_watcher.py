"""
Asynchronous station watcher: replaces the Data_Bridge desktop daemon.

Polls a watch folder (usually a network share) for new Quantum Neo CSV/XML files,
parses them, resolves the shift/run, and persists the sample + rods. It runs as a
background asyncio task inside the FastAPI lifespan, replacing the old
watchdog + Tkinter + SQLite stack.

Concurrency and correctness:
  * a single-consumer asyncio.Queue replaces the old threading.Lock;
  * file identity is a SHA-256 (plus legacy MD5) recorded in ingestion_files, so a
    file is never processed twice even across restarts;
  * a file is only picked up once it has non-zero size (stable), replacing the old
    sleep(2) hack;
  * persistence is per-file transactional: parse -> resolve -> insert -> record
    ledger -> commit, then the file is moved to the archive.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app import models
from app.services import shift_resolver
from app.services.parsers.quantum_csv import parse_bytes

logger = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL = 30
DEFAULT_STABLE_SECONDS = 3


@dataclass
class WatcherConfig:
    watch_path: str
    archive_path: str
    error_path: str
    scan_interval: int = DEFAULT_SCAN_INTERVAL
    stable_seconds: int = DEFAULT_STABLE_SECONDS
    source: str = "quantum_neo"
    alias_field: str = "maker"  # station column used to identify the machine


class StationWatcher:
    """Polling ingester. One instance per FastAPI process."""

    def __init__(self, session_factory, config: WatcherConfig) -> None:
        self.session_factory = session_factory
        self.config = config
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def start(self) -> None:
        self._running = True
        producer = asyncio.create_task(self._scan_loop())
        consumer = asyncio.create_task(self._consume_loop())
        self._tasks = (producer, consumer)
        logger.info("StationWatcher started on %s", self.config.watch_path)

    async def stop(self) -> None:
        self._running = False
        for task in getattr(self, "_tasks", ()):
            task.cancel()
        logger.info("StationWatcher stopped")

    async def enqueue_path(self, path: str) -> None:
        """Enqueue a single file (used by the manual ingest endpoint)."""
        await self._queue.put(path)

    async def _scan_loop(self) -> None:
        while self._running:
            if os.path.isdir(self.config.watch_path):
                for name in os.listdir(self.config.watch_path):
                    if name.lower().endswith((".csv", ".xml")):
                        await self._queue.put(os.path.join(self.config.watch_path, name))
            await asyncio.sleep(self.config.scan_interval)

    async def _consume_loop(self) -> None:
        while self._running:
            path = await self._queue.get()
            try:
                await asyncio.to_thread(self._process_file, path)
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                logger.exception("Failed to process %s: %s", path, exc)
            finally:
                self._queue.task_done()

    def _process_file(self, path: str) -> None:
        if not _is_stable(path):
            return  # file still being written; re-scanned next cycle

        data = _read_file(path)
        if data is None:
            return

        sample = parse_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        md5 = hashlib.md5(data).hexdigest()

        session: Session = self.session_factory()
        try:
            existing = (
                session.query(models.IngestionFile)
                .filter(
                    models.IngestionFile.status == "processed",
                    (models.IngestionFile.sha256 == digest) | (models.IngestionFile.md5 == md5),
                )
                .first()
            )
            if existing:
                self._move(path, self.config.archive_path)
                return

            self._persist(session, sample, digest, md5, os.path.basename(path))
            session.commit()
            self._move(path, self.config.archive_path)
        except Exception:
            session.rollback()
            self._record_error(digest, md5, os.path.basename(path), traceback.format_exc())
            self._move(path, self.config.error_path)
            raise
        finally:
            session.close()

    def _persist(self, session: Session, sample, sha256: str, md5: str, filename: str) -> None:
        machine_id = shift_resolver.resolve_machine(
            session, self.config.source, self.config.alias_field, sample.maker
        )

        produced_at = sample.produced_on or datetime.now(timezone.utc)
        if produced_at.tzinfo is None:
            produced_at = produced_at.replace(tzinfo=timezone.utc)

        kind, is_non_production = shift_resolver.classify_sample(sample.maker)
        if is_non_production:
            shift_id, link_status = None, shift_resolver.LINK_NON_PRODUCTION
        else:
            shift_id, link_status = shift_resolver.resolve_shift(session, machine_id, produced_at)

        run_id: Optional[int] = None
        if shift_id is not None:
            run_id, _ = shift_resolver.resolve_run(session, shift_id, produced_at, sample.mo_ref)

        db_sample = models.QualitySample(
            shift_id=shift_id,
            run_id=run_id,
            machine_id=machine_id,
            link_status=link_status,
            link_source="auto",
            kind=kind,
            source_instrument_id=sample.instrument_id,
            source_maker=sample.maker,
            source_team=sample.team,
            sample_id=sample.sample_id,
            mo_ref=sample.mo_ref,
            brand=sample.brand,
            operator=sample.operator,
            produced_at=produced_at,
            batch_started_at=sample.batch_start,
            batch_ended_at=sample.batch_end,
            rods_declared=sample.rods_count,
            file_sha256=sha256,
            file_md5=md5,
        )
        session.add(db_sample)
        session.flush()

        for rod in sample.rods:
            session.add(
                models.QualityMeasurement(
                    sample_id=db_sample.id,
                    shift_id=shift_id,
                    run_id=run_id,
                    machine_id=machine_id,
                    measured_at=produced_at,
                    rod_no=rod.rod_no,
                    pd=rod.pd,
                    weight=rod.weight,
                    diameter=rod.diameter,
                    ovality=rod.ovality,
                    roundness=rod.roundness,
                    shape=rod.shape,
                    hardness=rod.hardness,
                )
            )

        ledger = (
            session.query(models.IngestionFile)
            .filter(
                (models.IngestionFile.sha256 == sha256) | (models.IngestionFile.md5 == md5)
            )
            .first()
        )
        if ledger is None:
            ledger = models.IngestionFile(sha256=sha256, md5=md5, filename=filename)
            session.add(ledger)
        ledger.status = "processed"
        ledger.filename = filename
        ledger.error = None
        ledger.attempts = (ledger.attempts or 0) + 1
        ledger.sample_id = db_sample.id
        ledger.processed_at = datetime.now(timezone.utc)

    def _record_error(self, sha256: str, md5: str, filename: str, error: str) -> None:
        session: Session = self.session_factory()
        try:
            ledger = (
                session.query(models.IngestionFile)
                .filter(
                    (models.IngestionFile.sha256 == sha256) | (models.IngestionFile.md5 == md5)
                )
                .first()
            )
            if ledger is None:
                ledger = models.IngestionFile(sha256=sha256, md5=md5, filename=filename)
                session.add(ledger)
            ledger.status = "error"
            ledger.filename = filename
            ledger.error = error
            ledger.attempts = (ledger.attempts or 0) + 1
            session.commit()
        finally:
            session.close()

    def _move(self, path: str, target_dir: str) -> None:
        os.makedirs(target_dir, exist_ok=True)
        dest = os.path.join(target_dir, os.path.basename(path))
        if os.path.exists(dest):
            os.remove(dest)
        try:
            os.replace(path, dest)
        except OSError:
            logger.exception("Could not move %s to %s", path, dest)


def _read_file(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _is_stable(path: str) -> bool:
    try:
        return os.stat(path).st_size > 0
    except OSError:
        return False
