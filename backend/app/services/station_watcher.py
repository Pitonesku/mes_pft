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
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app import models
from app.config import local_to_utc
from app.quality_stats import is_triacetin_marker
from app.services import shift_resolver
from app.services.parsers import profiles

logger = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL = 30
DEFAULT_STABLE_SECONDS = 3


@dataclass
class WatcherConfig:
    watch_paths: List[str]
    scan_interval: int = DEFAULT_SCAN_INTERVAL
    stable_seconds: int = DEFAULT_STABLE_SECONDS
    source: str = "quantum_neo"
    alias_field: str = "maker"  # station column used to identify the machine
    mo_field: str = "batch_description"  # station column carrying the MO number
    dynamic_paths: Optional[Callable[[], List[str]]] = None


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
        logger.info("StationWatcher started on %s", self.config.watch_paths)

    async def stop(self) -> None:
        self._running = False
        for task in getattr(self, "_tasks", ()):
            task.cancel()
        logger.info("StationWatcher stopped")

    async def enqueue_path(self, path: str) -> None:
        """Enqueue a single file (used by the manual ingest endpoint)."""
        await self._queue.put(path)

    def _current_paths(self) -> List[str]:
        """Union of static (env) watch paths and DB pull-profile watch_paths."""
        paths = list(self.config.watch_paths)
        if self.config.dynamic_paths is not None:
            try:
                for p in self.config.dynamic_paths():
                    if p and p not in paths:
                        paths.append(p)
            except Exception:  # noqa: BLE001 - a DB hiccup must not kill scanning
                logger.exception("Failed to read dynamic pull paths")
        return paths

    async def _scan_loop(self) -> None:
        while self._running:
            for path in self._current_paths():
                if os.path.isdir(path):
                    for name in os.listdir(path):
                        if name.lower().endswith((".csv", ".xml")):
                            await self._queue.put(os.path.join(path, name))
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

        digest = hashlib.sha256(data).hexdigest()
        md5 = hashlib.md5(data).hexdigest()

        base = os.path.dirname(path) or "."
        archive_path = os.path.join(base, "Archive")
        error_path = os.path.join(base, "Errors")

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
                self._move(path, archive_path)
                return

            sample, profile = profiles.parse_file_with_profile(
                session, data, self.config.source, self.config.mo_field
            )
            self._persist(session, sample, profile, digest, md5, os.path.basename(path))
            session.commit()
            self._move(path, archive_path)
        except Exception:
            session.rollback()
            self._record_error(digest, md5, os.path.basename(path), traceback.format_exc())
            self._move(path, error_path)
            raise
        finally:
            session.close()

    def _persist(self, session: Session, sample, profile, sha256: str, md5: str, filename: str) -> None:
        machine_id = shift_resolver.resolve_machine(
            session, self.config.source, self.config.alias_field, sample.maker
        )

        produced_at = local_to_utc(sample.produced_on) or datetime.now(timezone.utc)

        kind, is_non_production = shift_resolver.classify_sample(sample.maker)
        if is_non_production:
            shift_id, link_status = None, shift_resolver.LINK_NON_PRODUCTION
        else:
            shift_id, link_status = shift_resolver.resolve_shift(session, machine_id, produced_at)

        run_id: Optional[int] = None
        if shift_id is not None:
            run_id, run_status = shift_resolver.resolve_run(
                session, shift_id, produced_at, sample.mo_ref, machine_id=machine_id,
                sample_id=sample.sample_id,
            )
            if run_status == shift_resolver.LINK_MO_MISMATCH:
                # Keep the rods (shift is known) but surface the label problem for review
                # instead of silently losing the MO attribution.
                link_status = shift_resolver.LINK_MO_MISMATCH
                logger.warning(
                    "Station MO label %r matches no run of shift %s (machine %s)",
                    sample.mo_ref, shift_id, machine_id,
                )

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
            comments=sample.reserve_1,
            produced_at=produced_at,
            batch_started_at=local_to_utc(sample.batch_start),
            batch_ended_at=local_to_utc(sample.batch_end),
            rods_declared=sample.rods_count,
            file_sha256=sha256,
            file_md5=md5,
            is_triacetin=is_triacetin_marker(sample.sample_id, sample.reserve_2, sample.reserve_1),
            custom_metrics=profiles.compute_custom_metrics(sample, profile),
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
                    length=rod.length,
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
