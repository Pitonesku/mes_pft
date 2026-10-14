"""Safe MO recall guardrails (Odoo -> MES).

Kept free of FastAPI/framework imports so it stays unit-testable. ``recall_mo``
raises :class:`MoRecallError` (carrying an HTTP status) when the MO must not be
recalled, and returns a success dict when the unstarted MO is safely archived.

Invariant #2 is preserved: a recalled MO is **archived/hidden**, never deleted,
and its ``sync_mode`` is downgraded to ``link_only`` so nothing can be posted to
a dead MO.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app import models


class MoRecallError(Exception):
    """A recall rejection: carries the HTTP status + a human-readable detail."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _resolve_runs(session: Session, mo_ref: Optional[str], mo_id: Optional[int]) -> List[models.ProductionRun]:
    runs: List[models.ProductionRun] = []
    if mo_id:
        runs = session.query(models.ProductionRun).filter(
            models.ProductionRun.odoo_mo_id == int(mo_id)
        ).all()
    if not runs and mo_ref:
        runs = session.query(models.ProductionRun).filter(
            models.ProductionRun.mo_ref == mo_ref
        ).all()
    return runs


def _resolve_po(session: Session, mo_ref: Optional[str], mo_id: Optional[int]) -> Optional[models.PurchaseOrder]:
    if mo_id:
        po = session.query(models.PurchaseOrder).filter(
            models.PurchaseOrder.odoo_mo_id == int(mo_id)
        ).first()
        if po is not None:
            return po
    if mo_ref:
        po = session.query(models.PurchaseOrder).filter(
            (models.PurchaseOrder.odoo_mo_name == mo_ref)
            | (models.PurchaseOrder.po_number == mo_ref)
        ).first()
        if po is not None:
            return po
    return None


def recall_mo(session: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and recall an MO, or raise :class:`MoRecallError`.

    Guardrails (in order):
      1. 409 - the MO is open on a machine right now (an open run exists).
      2. 409 - production data already exists (end_counter, manual QC checks or
         station measurements).
      3. 200 - no active session and no data: archive the unstarted order.
    """
    mo_ref = str(payload.get("mo_ref") or "").strip() or None
    mo_id = payload.get("mo_id")

    if not mo_ref and not mo_id:
        raise MoRecallError(400, "mo_ref or mo_id is required")

    runs = _resolve_runs(session, mo_ref, mo_id)
    run_ids = [r.id for r in runs]

    # 1. Open on a machine?
    open_runs = [r for r in runs if r.ended_at is None]
    if open_runs:
        names = []
        for r in open_runs:
            m = session.get(models.Machine, r.machine_id) if r.machine_id else None
            names.append(m.name if m else "?")
        label = "/".join(sorted(set(names))) or "?"
        raise MoRecallError(
            409,
            f"MO is currently open on machine [{label}]. Operator must switch order first.",
        )

    # 2. Production data already exists?
    if run_ids:
        has_counter = any((r.end_counter or 0) > 0 for r in runs)
        has_manual = (
            session.query(models.ManualQualityCheck)
            .filter(models.ManualQualityCheck.mo_id.in_(run_ids))
            .first()
            is not None
        )
        has_measurements = (
            session.query(models.QualityMeasurement)
            .filter(models.QualityMeasurement.run_id.in_(run_ids))
            .first()
            is not None
        )
        if has_counter or has_manual or has_measurements:
            raise MoRecallError(409, "Production data already exists for this MO. Cannot recall.")

    # 3. Archive the unstarted MO (additive only - never delete).
    po = _resolve_po(session, mo_ref, mo_id)
    if po is not None:
        po.is_archived = True
        po.is_hidden = True
        po.odoo_state = "recalled"
        po.sync_mode = "link_only"
        if mo_id:
            po.odoo_mo_id = int(mo_id)
    session.commit()

    return {
        "mo_ref": mo_ref,
        "mo_id": mo_id,
        "recalled": True,
        "po_id": po.id if po is not None else None,
        "message": "MO successfully removed from MES queue.",
    }
