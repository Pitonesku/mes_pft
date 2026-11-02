"""Quarantine ledger + NCR lifecycle (pure domain logic, no HTTP concerns).

Owns the two invariants of the quality-management module:

* The quarantine balance of one order is
  ``SUM(production_reports.quarantine_boxes) - SUM(non-voided resolutions.boxes)``
  and may never go negative: every resolution is validated against the remaining
  balance atomically, so a box can be scrapped or released at most once.
* Resolutions are never deleted - only voided. A RELEASE that already synced to
  Odoo (stock was added) can never be voided: recovery requires a compensating
  resolution or a manual Odoo reversal.

Document numbers embed the MO: ``SCR-{MO}-{seq:04d}``, ``REL-{MO}-{seq:04d}``,
``NCR-{MO}-{seq:04d}`` with a per-order sequence protected by
``UNIQUE (po_id, doc_seq)``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app import models

KIND_SCRAP = "scrap"
KIND_RELEASE = "release"
KINDS = (KIND_SCRAP, KIND_RELEASE)

NCR_OPEN = "OPEN"
NCR_IN_PROGRESS = "IN_PROGRESS"
NCR_CLOSED = "CLOSED"
NCR_STATUSES = (NCR_OPEN, NCR_IN_PROGRESS, NCR_CLOSED)
NCR_SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")

SYNC_LOCAL = "local"
SYNC_PENDING = "pending"
SYNC_SYNCED = "synced"
SYNC_ERROR = "error"
SYNC_SHADOW = "shadow"

# Sync states after which the stock already moved in Odoo (release cannot be voided).
SYNC_IRREVERSIBLE = {SYNC_SYNCED, "sent"}


class QualityError(Exception):
    """Business-rule violation; ``status`` maps 1:1 onto an HTTP status code."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def safe_mo(value: Optional[str]) -> str:
    """Sanitize a MO number for use inside a document number."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "MO")).strip("-") or "MO"


def _next_doc_number(db: Session, model, po: models.PurchaseOrder, prefix: str) -> Tuple[str, int]:
    """``{prefix}-{MO}-{seq:04d}`` with a per-order sequence (concurrency-safe)."""
    max_seq = (
        db.query(func.max(model.doc_seq))
        .filter(model.po_id == po.id)
        .scalar()
    ) or 0
    seq = int(max_seq) + 1
    return f"{prefix}-{safe_mo(po.mo_number)}-{seq:04d}", seq


def _allocate_number(db: Session, build: callable, attempts: int = 3) -> None:
    """Flush ``build()`` under a savepoint, re-deriving the doc number on
    ``UNIQUE (po_id, doc_seq)`` collisions (concurrent creates)."""
    for _ in range(attempts):
        try:
            with db.begin_nested():
                build()
                db.flush()
            return
        except IntegrityError:
            pass
    raise QualityError(409, "Could not allocate a unique document number - retry")


# --------------------------------------------------------------------------- #
# Quarantine balance + resolutions
# --------------------------------------------------------------------------- #

def _report_filter():
    return (
        models.ProductionReport.status != "obsolete",
        (models.ProductionReport.is_deleted.is_(False))
        | (models.ProductionReport.is_deleted.is_(None)),
    )


def quarantine_balance(db: Session, po: models.PurchaseOrder) -> Dict[str, Any]:
    """Total quarantine boxes, resolved boxes and the remaining balance."""
    total = (
        db.query(func.coalesce(func.sum(models.ProductionReport.quarantine_boxes), 0))
        .filter(models.ProductionReport.mo_number == po.mo_number, *_report_filter())
        .scalar()
    ) or 0
    rows = (
        db.query(models.QuarantineResolution)
        .filter(
            models.QuarantineResolution.po_id == po.id,
            models.QuarantineResolution.voided_at.is_(None),
        )
        .all()
    )
    scrap_boxes = sum(r.boxes for r in rows if r.kind == KIND_SCRAP)
    released_boxes = sum(r.boxes for r in rows if r.kind == KIND_RELEASE)
    scrap_kg = round(
        sum(float(r.dry_weight_kg or 0) for r in rows if r.kind == KIND_SCRAP), 3
    )
    resolved = scrap_boxes + released_boxes
    return {
        "total_quarantine_boxes": int(total),
        "resolved_boxes": resolved,
        "scrap_boxes": scrap_boxes,
        "released_boxes": released_boxes,
        "scrap_kg": scrap_kg,
        "remaining_boxes": max(0, int(total) - resolved),
    }


def resolutions(db: Session, po_id: int, include_voided: bool = False) -> List[models.QuarantineResolution]:
    q = db.query(models.QuarantineResolution).filter(
        models.QuarantineResolution.po_id == po_id
    )
    if not include_voided:
        q = q.filter(models.QuarantineResolution.voided_at.is_(None))
    return q.order_by(models.QuarantineResolution.id).all()


def create_resolution(
    db: Session,
    po: models.PurchaseOrder,
    kind: str,
    boxes: int,
    user: models.User,
    dry_weight_kg: Optional[float] = None,
    reason_code: Optional[str] = None,
    notes: Optional[str] = None,
    ncr_id: Optional[int] = None,
) -> models.QuarantineResolution:
    """Validate the balance and create a SCRAP / RELEASE resolution."""
    if kind not in KINDS:
        raise QualityError(422, f"kind must be one of {list(KINDS)}")
    try:
        boxes = int(boxes or 0)
    except (TypeError, ValueError):
        raise QualityError(422, "boxes must be a positive integer") from None
    if boxes <= 0:
        raise QualityError(422, "boxes must be a positive integer")
    if po.completion_status == "cancelled":
        raise QualityError(409, f"Order {po.mo_number} is cancelled; quarantine cannot be resolved")
    if kind == KIND_SCRAP:
        try:
            weight = float(dry_weight_kg or 0)
        except (TypeError, ValueError):
            raise QualityError(422, "dry_weight_kg must be a number") from None
        if weight < 0:
            raise QualityError(422, "dry_weight_kg must be >= 0")
    else:
        weight = None

    balance = quarantine_balance(db, po)
    if boxes > balance["remaining_boxes"]:
        raise QualityError(
            422,
            f"Cannot resolve {boxes} boxes: only {balance['remaining_boxes']} "
            f"remain in quarantine for {po.mo_number}",
        )

    prefix = "SCR" if kind == KIND_SCRAP else "REL"
    resolution = models.QuarantineResolution(
        doc_number=None,
        po_id=po.id,
        mo_ref=po.mo_number,
        doc_seq=0,
        kind=kind,
        boxes=boxes,
        dry_weight_kg=weight,
        reason_code=reason_code,
        notes=notes,
        ncr_id=ncr_id,
        created_by=user.id,
        created_at=utcnow(),
        odoo_sync_status=SYNC_LOCAL,
    )
    db.add(resolution)

    def build() -> None:
        number, seq = _next_doc_number(db, models.QuarantineResolution, po, prefix)
        resolution.doc_number = number
        resolution.doc_seq = seq

    _allocate_number(db, build)
    return resolution


def void_resolution(
    db: Session,
    resolution: models.QuarantineResolution,
    user: models.User,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Soft-void. A synced RELEASE cannot be voided (stock already moved in Odoo)."""
    if resolution.voided_at is not None:
        raise QualityError(409, "Resolution is already voided")
    if resolution.kind == KIND_RELEASE and resolution.odoo_sync_status in SYNC_IRREVERSIBLE:
        raise QualityError(
            409,
            "Cannot void a release already synced to Odoo - the stock was added. "
            "Create a compensating resolution or reverse the move in Odoo.",
        )
    resolution.voided_at = utcnow()
    resolution.voided_by = user.id
    resolution.void_reason = reason
    po = db.get(models.PurchaseOrder, resolution.po_id)
    balance = quarantine_balance(db, po) if po is not None else {}
    return {"id": resolution.id, "doc_number": resolution.doc_number,
            "voided": True, "balance": balance}


# --------------------------------------------------------------------------- #
# NCR lifecycle
# --------------------------------------------------------------------------- #

def create_ncr(
    db: Session,
    po: models.PurchaseOrder,
    user: models.User,
    description: str,
    corrective_action: Optional[str] = None,
    severity: str = "MINOR",
    machine_id: Optional[int] = None,
    run_id: Optional[int] = None,
) -> models.NonConformityReport:
    if not description or not str(description).strip():
        raise QualityError(422, "description is required")
    if severity not in NCR_SEVERITIES:
        raise QualityError(422, f"severity must be one of {list(NCR_SEVERITIES)}")

    ncr = models.NonConformityReport(
        ncr_number=None,
        po_id=po.id,
        mo_ref=po.mo_number,
        doc_seq=0,
        run_id=run_id,
        machine_id=machine_id,
        description=str(description).strip(),
        corrective_action=corrective_action,
        severity=severity,
        status=NCR_OPEN,
        created_by=user.id,
        created_at=utcnow(),
    )
    db.add(ncr)

    def build() -> None:
        number, seq = _next_doc_number(db, models.NonConformityReport, po, "NCR")
        ncr.ncr_number = number
        ncr.doc_seq = seq

    _allocate_number(db, build)
    db.add(models.NcrStatusLog(
        ncr_id=ncr.id,
        from_status=None,
        to_status=NCR_OPEN,
        user_id=user.id,
        username=user.username,
        remarks=None,
        created_at=utcnow(),
    ))
    return ncr


def set_ncr_status(
    db: Session,
    ncr: models.NonConformityReport,
    to_status: str,
    user: models.User,
    remarks: Optional[str] = None,
) -> models.NonConformityReport:
    """Transition the NCR lifecycle, logging every change in ``ncr_status_logs``."""
    if to_status not in NCR_STATUSES:
        raise QualityError(422, f"status must be one of {list(NCR_STATUSES)}")
    if ncr.status == to_status:
        return ncr
    if ncr.status == NCR_CLOSED and to_status != NCR_IN_PROGRESS:
        raise QualityError(422, "A closed NCR can only be reopened to IN_PROGRESS")
    if ncr.status != NCR_CLOSED and to_status == NCR_CLOSED and not remarks:
        raise QualityError(422, "closing_remarks are required when closing an NCR")

    from_status = ncr.status
    ncr.status = to_status
    if to_status == NCR_CLOSED:
        ncr.closed_by = user.id
        ncr.closed_at = utcnow()
        ncr.closing_remarks = remarks
    elif from_status == NCR_CLOSED:
        ncr.closed_by = None
        ncr.closed_at = None
    db.add(models.NcrStatusLog(
        ncr_id=ncr.id,
        from_status=from_status,
        to_status=to_status,
        user_id=user.id,
        username=user.username,
        remarks=remarks,
        created_at=utcnow(),
    ))
    return ncr


def ncr_history(db: Session, ncr_id: int) -> List[models.NcrStatusLog]:
    return (
        db.query(models.NcrStatusLog)
        .filter(models.NcrStatusLog.ncr_id == ncr_id)
        .order_by(models.NcrStatusLog.id)
        .all()
    )


# --------------------------------------------------------------------------- #
# Serialization (shared by the v2 routes and tests)
# --------------------------------------------------------------------------- #

def ncr_dict(ncr: models.NonConformityReport) -> Dict[str, Any]:
    session = object_session(ncr)
    machine_name = None
    if session is not None and ncr.machine_id is not None:
        machine = session.get(models.Machine, ncr.machine_id)
        machine_name = machine.name if machine is not None else None
    return {
        "id": ncr.id,
        "ncr_number": ncr.ncr_number,
        "po_id": ncr.po_id,
        "mo_ref": ncr.mo_ref,
        "machine_id": ncr.machine_id,
        "machine_name": machine_name,
        "run_id": ncr.run_id,
        "description": ncr.description,
        "corrective_action": ncr.corrective_action,
        "severity": ncr.severity,
        "status": ncr.status,
        "created_by": ncr.created_by,
        "created_at": ncr.created_at.isoformat() if ncr.created_at else None,
        "closed_by": ncr.closed_by,
        "closed_at": ncr.closed_at.isoformat() if ncr.closed_at else None,
        "closing_remarks": ncr.closing_remarks,
    }


def resolution_dict(r: models.QuarantineResolution) -> Dict[str, Any]:
    return {
        "id": r.id,
        "doc_number": r.doc_number,
        "po_id": r.po_id,
        "mo_ref": r.mo_ref,
        "kind": r.kind,
        "boxes": r.boxes,
        "dry_weight_kg": float(r.dry_weight_kg) if r.dry_weight_kg is not None else None,
        "reason_code": r.reason_code,
        "notes": r.notes,
        "ncr_id": r.ncr_id,
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "odoo_sync_status": r.odoo_sync_status,
        "odoo_model": r.odoo_model,
        "odoo_id": r.odoo_id,
        "voided_at": r.voided_at.isoformat() if r.voided_at else None,
        "voided_by": r.voided_by,
        "void_reason": r.void_reason,
    }


def order_quarantine_summary(db: Session, po: models.PurchaseOrder) -> Dict[str, Any]:
    """Full quarantine payload for GET /orders/{id}/quarantine."""
    return {
        "po_id": po.id,
        "po_number": po.mo_number,
        **quarantine_balance(db, po),
        "resolutions": [resolution_dict(r) for r in resolutions(db, po.id)],
    }
