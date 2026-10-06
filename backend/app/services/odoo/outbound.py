"""Outbound MES -> Odoo: idempotent dispatch of shift summaries queued in
``odoo_outbox``. Modeled on the StationWatcher / report_outbox worker pattern."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app import models
from app.services import aggregation
from app.services.odoo.client import OdooClient, OdooConfig

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


def enabled(config: Optional[OdooConfig] = None) -> bool:
    cfg = config or OdooConfig.from_env()
    return bool(cfg.enabled and cfg.valid())


def enqueue_shift_summary(
    session: Session,
    shift_id: int,
    version: int,
    payload: Dict[str, Any],
    config: Optional[OdooConfig] = None,
) -> Optional[models.OdooOutbox]:
    """Queue a shift summary for Odoo dispatch (no-op when Odoo is disabled)."""
    if not enabled(config):
        return None
    key = payload.get("idempotency_key") or f"mes:shift:{shift_id}:v{version}"
    existing = (
        session.query(models.OdooOutbox)
        .filter(models.OdooOutbox.idempotency_key == key)
        .first()
    )
    if existing is not None:
        return existing
    item = models.OdooOutbox(
        aggregate_type="shift",
        aggregate_id=shift_id,
        shift_summary_version=version,
        idempotency_key=key,
        payload=payload,
        payload_hash=aggregation.fingerprint(payload),
        status="pending",
    )
    session.add(item)
    return item


def dispatch_pending(session_factory, config: OdooConfig, limit: int = 20) -> int:
    """Process up to ``limit`` pending outbox items. Returns count dispatched."""
    session: Session = session_factory()
    dispatched = 0
    client: Optional[OdooClient] = None
    try:
        items = (
            session.query(models.OdooOutbox)
            .filter(models.OdooOutbox.status == "pending")
            .order_by(models.OdooOutbox.id)
            .limit(limit)
            .all()
        )
        for item in items:
            try:
                if client is None:
                    client = OdooClient(config)
                    client.connect()
                _dispatch_item(session, client, item)
                item.status = "sent"
                item.last_error = None
                dispatched += 1
            except Exception as exc:  # noqa: BLE001
                item.attempts = (item.attempts or 0) + 1
                item.status = "failed" if item.attempts >= MAX_ATTEMPTS else "pending"
                item.last_error = str(exc)
                item.next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=5)
                logger.warning("Odoo dispatch failed for %s: %s", item.idempotency_key, exc)
            session.commit()
    finally:
        session.close()
    return dispatched


def _dispatch_item(session: Session, client: OdooClient, item: models.OdooOutbox) -> None:
    payload = item.payload or {}
    for run in payload.get("runs", []):
        run_id = run.get("run_id")
        if not run_id:
            continue
        db_run = session.get(models.ProductionRun, run_id)
        if db_run is None or db_run.odoo_mo_id is None:
            # Inbound sync must link the MO first; skip until then.
            continue
        _dispatch_run(session, client, db_run, run)


def _dispatch_run(session: Session, client: OdooClient, db_run, run) -> None:
    mo_id = db_run.odoo_mo_id

    # 1. Structured quality fields on mrp.production (custom addon), not chatter.
    client.write_mo_quality(mo_id, run)

    # 2. Finished quantity: partial completion -> Odoo auto-creates the backorder.
    #    NOTE: the authoritative produced quantity is the legacy production
    #    report's ``produced_rods``; until run<->report linkage lands, fall back
    #    to the number of measured rods.
    qty_rods = _produced_rods(run)
    if qty_rods:
        result = client.post_completion(mo_id, qty_rods)
        db_run.odoo_done_qty = result.get("qty")

    # 3. Resolve raw-material lot ids (stock.lot) for later move-line creation.
    _resolve_material_lots(session, client, db_run)

    db_run.odoo_sync_status = "synced"


def _resolve_material_lots(session: Session, client: OdooClient, db_run) -> None:
    logs = (
        session.query(models.MaterialLog)
        .filter(models.MaterialLog.shift_id == db_run.shift_id)
        .all()
    )
    for log in logs:
        if not log.odoo_lot_id and log.batch_no:
            lot = client.search_read(
                "stock.lot", [["name", "=", log.batch_no]], ["id"], limit=1
            )
            if lot:
                log.odoo_lot_id = int(lot[0]["id"])


def _produced_rods(run: Dict[str, Any]) -> float:
    for key in ("rods_used", "rods_total"):
        value = run.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0
