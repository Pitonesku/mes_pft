"""Unified v2 API routes (docs/api.md).

Shifts (the central aggregate), rod-level measurements, quality/certificate stats
and the Odoo outbox. Pure HTTP layer: the actual statistics live in
``app/quality_stats`` / ``app/services/aggregation``, shift resolution in
``app/services/shift_resolver``.
"""

from __future__ import annotations

import csv as _csv
import hashlib
import hmac
import io
import os
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app import schemas
from app.config import get_plant_timezone, local_to_utc
from app.auth import get_current_user, get_ingest_identity
from app.database import get_db
from app.quality_stats import (
    STATUS_FAIL,
    STATUS_NO_DATA,
    STATUS_PASS,
    STATUS_WARN,
    _is_rejected,
    _num,
    compute_run_stats,
    certificate_rows,
    manual_rods,
    merge_manual_parameters,
)
from app.services import aggregation, manual_check_rules, run_corrections, shift_lifecycle, shift_resolver
from app.services.lot_number import lot_number
from app.services.shift_lifecycle import LifecycleError
from app.services.odoo import outbound as odoo_outbound
from app.services.parsers import profiles

router = APIRouter(prefix="/v2", tags=["v2"])

_MEASUREMENT_COLS = (
    "sample_id", "shift_id", "run_id", "machine_id", "measured_at",
    "rod_no", "pd", "weight", "diameter", "ovality", "roundness", "shape", "hardness",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} {obj_id} not found")
    return obj


def _role_name(user: models.User) -> str:
    role = getattr(user, "role", None)
    return (role.role_name or "").strip().lower() if role is not None else ""


def _is_admin(user: models.User) -> bool:
    return _role_name(user) in ("admin", "superadmin") or user.username == "superadmin"


def _is_supervisor(user: models.User) -> bool:
    """Supervisor = manager or admin role, or an explicit ``can_edit_report`` grant."""
    role = getattr(user, "role", None)
    return (
        _is_admin(user)
        or _role_name(user) == "manager"
        or bool(getattr(user, "can_edit_report", False))
        or bool(role is not None and role.can_edit_report)
    )


def _require_supervisor(user: models.User) -> None:
    if not _is_supervisor(user):
        raise HTTPException(status_code=403, detail="Supervisor (manager/admin) only")


def _lifecycle(fn, *args, **kwargs):
    """Run a lifecycle action, mapping business-rule errors onto HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except LifecycleError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    except IntegrityError as exc:  # concurrent start on the same machine
        raise HTTPException(
            status_code=409,
            detail="This machine already has an open run - refresh and retry, or use takeover.",
        )


def _shift_dict(s: models.ShiftSession) -> Dict[str, Any]:
    return {
        "id": s.id, "machine_id": s.machine_id, "operator_id": s.operator_id,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "status": s.status, "plant_tz": s.plant_tz, "source": s.source,
        "client_shift_id": s.client_shift_id,
        "closed_at": s.closed_at.isoformat() if s.closed_at else None,
        "closed_by": s.closed_by, "legacy_report_key": s.legacy_report_key,
        "shift_name": s.shift_name,
        "scheduled_end_at": s.scheduled_end_at.isoformat() if s.scheduled_end_at else None,
    }


def _run_dict(r: models.ProductionRun) -> Dict[str, Any]:
    return {
        "id": r.id, "shift_id": r.shift_id, "seq": r.seq, "po_id": r.po_id,
        "machine_id": r.machine_id,
        "mo_ref": r.mo_ref,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "status": r.status,
        "end_counter": _num(r.end_counter),
    }


_MEASURE_PARAM_KEYS = ("pd", "weight", "diameter", "ovality", "roundness", "shape", "hardness", "length")


BUDAPEST = get_plant_timezone()


def _bud(dt: datetime) -> datetime:
    return dt.astimezone(BUDAPEST)


def _bud_iso(dt: datetime) -> str:
    return _bud(dt).isoformat()


def _bud_x_ms(dt: datetime) -> int:
    bud = dt.astimezone(BUDAPEST).replace(tzinfo=None)
    return int(bud.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _series_payload(specs: Dict, rods, max_points: int = 3000) -> Dict[str, Any]:
    pts = rods[-max_points:] if len(rods) > max_points else rods
    points = []
    for r in pts:
        if r.measured_at is None:
            continue
        synthetic = r.measured_at + timedelta(seconds=(r.rod_no - 1) * 4)
        points.append({
            "x": _bud_x_ms(synthetic),
            "synthetic_timestamp": _bud_iso(synthetic),
            "rod_no": r.rod_no,
            "pd": _num(r.pd),
            "diameter": _num(r.diameter),
            "weight": _num(r.weight),
            "rejected": _is_rejected({k: getattr(r, k) for k in _MEASURE_PARAM_KEYS}, specs) if specs else False,
        })
    params = {}
    for key in ("pd", "diameter", "weight"):
        spec = specs.get(key)
        params[key] = {
            "target": _num(spec.nominal) if spec else None,
            "usl": _num(spec.upper) if spec else None,
            "lsl": _num(spec.lower) if spec else None,
            "unit": (spec.report_unit or "") if spec else "",
        }
    return {"params": params, "points": points}


def _rod_dict(m: models.QualityMeasurement, specs: Optional[Dict] = None) -> Dict[str, Any]:
    out = {c: getattr(m, c) for c in _MEASUREMENT_COLS}
    if out.get("measured_at"):
        out["measured_at"] = _bud_iso(m.measured_at)
        synthetic = m.measured_at + timedelta(seconds=(m.rod_no - 1) * 4)
        out["synthetic_timestamp"] = _bud_iso(synthetic)
        out["x"] = _bud_x_ms(synthetic)
    else:
        out["synthetic_timestamp"] = None
        out["x"] = None
    out["pressure_drop"] = out.get("pd")
    rejected = False
    if specs:
        rejected = _is_rejected({k: getattr(m, k) for k in _MEASURE_PARAM_KEYS}, specs)
    out["rejected"] = rejected
    out["is_outlier"] = rejected
    return out


def _overall_verdict(statuses: List[Optional[str]]) -> str:
    if STATUS_FAIL in statuses:
        return STATUS_FAIL
    if STATUS_WARN in statuses:
        return STATUS_WARN
    if STATUS_PASS in statuses:
        return STATUS_PASS
    return STATUS_NO_DATA


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------

class ShiftOpen(BaseModel):
    machine_id: int
    operator_id: Optional[int] = None
    started_at: Optional[datetime] = None
    plant_tz: str = "Europe/Budapest"
    source: str = "tablet"
    client_shift_id: Optional[str] = None
    mo_ref: Optional[str] = None      # Manufacturing Order / PO number to activate
    po_id: Optional[int] = None       # explicit purchase order id (alternative to mo_ref)
    shift_name: Optional[str] = None           # shift template label ("Shift 1")
    scheduled_end_at: Optional[datetime] = None  # for the auto-close sweep
    takeover: bool = False             # AUTO_CLOSE any active shift on the machine first


class ShiftClose(BaseModel):
    ended_at: Optional[datetime] = None
    manual_quality: Optional[Dict[str, Dict[str, Optional[float]]]] = None
    material_logs: List[Dict[str, Any]] = []
    scrap_logs: List[Dict[str, Any]] = []


class SwitchMoPayload(BaseModel):
    po_id: Optional[int] = None
    mo_ref: Optional[str] = None
    end_counter: Optional[float] = None  # final machine counter of the previous MO


class ChangeMachinePayload(BaseModel):
    machine_id: int
    end_counter: Optional[float] = None  # final counter on the machine being left
    po_id: Optional[int] = None          # optional MO on the new machine (default: same MO)
    mo_ref: Optional[str] = None


class ReassignRunPayload(BaseModel):
    po_id: Optional[int] = None
    mo_ref: Optional[str] = None
    machine_id: Optional[int] = None
    reason: str


@router.get("/shifts")
def list_shifts(
    machine_id: Optional[int] = None,
    status: Optional[str] = None,
    started_after: Optional[datetime] = None,
    started_before: Optional[datetime] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.ShiftSession)
    if machine_id is not None:
        q = q.filter(models.ShiftSession.machine_id == machine_id)
    if status == "active":
        q = q.filter(models.ShiftSession.ended_at.is_(None))
    elif status:
        q = q.filter(models.ShiftSession.status == status)
    if started_after:
        q = q.filter(models.ShiftSession.started_at >= started_after)
    if started_before:
        q = q.filter(models.ShiftSession.started_at <= started_before)
    shifts = q.order_by(models.ShiftSession.started_at.desc()).limit(500).all()

    # Enrich with human-readable context (no per-shift round trips).
    machine_ids = {s.machine_id for s in shifts}
    user_ids = {s.operator_id for s in shifts if s.operator_id}
    machine_map = {m.id: m.name for m in db.query(models.Machine).filter(models.Machine.id.in_(machine_ids)).all()} if machine_ids else {}
    user_map = {u.id: u.username for u in db.query(models.User).filter(models.User.id.in_(user_ids)).all()} if user_ids else {}
    shift_ids = [s.id for s in shifts]
    mo_map: Dict[int, str] = {}
    if shift_ids:
        rows = (
            db.query(models.ProductionRun.shift_id, models.ProductionRun.mo_ref)
            .filter(models.ProductionRun.shift_id.in_(shift_ids))
            .order_by(models.ProductionRun.shift_id, models.ProductionRun.seq.desc())
            .all()
        )
        for sid, mo in rows:
            if sid not in mo_map:
                mo_map[sid] = mo

    out = []
    for s in shifts:
        d = _shift_dict(s)
        d["machine_name"] = machine_map.get(s.machine_id)
        d["operator_name"] = user_map.get(s.operator_id)
        d["mo_ref"] = mo_map.get(s.id)
        out.append(d)
    return out


def _run_payload(db: Session, run: Optional[models.ProductionRun]) -> Dict[str, Any]:
    """Run + frozen specs in the shape the tablet expects after open / resume / switch."""
    if run is None:
        return {"run": None, "specs": {}}
    return {
        "run": {**_run_dict(run), "spec_snapshot": run.spec_snapshot},
        "specs": _spec_limits_payload(aggregation.load_run_specs(db, run)),
    }


def _find_resumable_shift(db: Session, machine_id: int, shift_name: str) -> Optional[models.ShiftSession]:
    """Return an AUTO_CLOSED shift for this machine/shift still within its window."""
    now = _utcnow()
    candidates = (
        db.query(models.ShiftSession)
        .filter(
            models.ShiftSession.machine_id == machine_id,
            models.ShiftSession.shift_name == shift_name,
            models.ShiftSession.status == "AUTO_CLOSED",
        )
        .order_by(models.ShiftSession.started_at.desc())
        .limit(10)
        .all()
    )
    for s in candidates:
        if s.scheduled_end_at is not None and now < s.scheduled_end_at:
            return s
    return None


@router.post("/shifts")
def open_shift(
    payload: ShiftOpen,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _get_or_404(db, models.Machine, payload.machine_id)
    existing = (
        db.query(models.ShiftSession)
        .filter(
            models.ShiftSession.machine_id == payload.machine_id,
            models.ShiftSession.ended_at.is_(None),
        )
        .first()
    )
    if existing and not payload.takeover:
        raise HTTPException(status_code=409, detail=f"Machine already has an open shift (id={existing.id})")
    if existing and payload.takeover:
        # Do NOT void: free the previous shift as AUTO_CLOSED so its data survives,
        # and close its open runs so the machine is really free (one open run per
        # machine is DB-enforced). Flush before inserting the replacement shift.
        now = _utcnow()
        existing.status = "AUTO_CLOSED"
        existing.ended_at = existing.ended_at or now
        existing.closed_at = existing.closed_at or now
        shift_lifecycle.close_shift_runs(db, existing, existing.ended_at)
        db.flush()
    scheduled_end = payload.scheduled_end_at
    if scheduled_end is not None and scheduled_end.tzinfo is None:
        try:
            scheduled_end = scheduled_end.replace(tzinfo=ZoneInfo(payload.plant_tz))
        except Exception:
            pass

    # Reopen: resume an AUTO_CLOSED shift for the same machine + shift template if
    # still within its scheduled window (avoids duplicate shift sessions).
    if payload.shift_name:
        resumable = _find_resumable_shift(db, payload.machine_id, payload.shift_name)
        if resumable is not None:
            resumable.ended_at = None
            resumable.status = "IN_PROGRESS"
            resumable.closed_at = None
            resumable.closed_by = None
            if scheduled_end is not None:
                resumable.scheduled_end_at = scheduled_end
            db.flush()
            po = shift_lifecycle.resolve_po(db, payload.po_id, payload.mo_ref)
            run = _lifecycle(shift_lifecycle.resume_run, db, resumable, po)
            db.commit()
            db.refresh(resumable)
            return {**_shift_dict(resumable), **_run_payload(db, run)}

    shift = models.ShiftSession(
        machine_id=payload.machine_id,
        operator_id=payload.operator_id or current_user.id,
        started_at=payload.started_at or _utcnow(),
        status="IN_PROGRESS",
        plant_tz=payload.plant_tz,
        source=payload.source,
        client_shift_id=payload.client_shift_id,
        shift_name=payload.shift_name,
        scheduled_end_at=scheduled_end,
    )
    db.add(shift)
    db.flush()

    # Every shift starts with a run so the machine is always recorded (the MO may be
    # chosen later via switch-mo).
    po = shift_lifecycle.resolve_po(db, payload.po_id, payload.mo_ref)
    try:
        run = shift_lifecycle.start_first_run(db, shift, po)
        db.commit()
    except LifecycleError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This machine already has an open run - use takeover.")
    db.refresh(shift)
    return {**_shift_dict(shift), **_run_payload(db, run)}


@router.get("/shifts/{shift_id}")
def get_shift(shift_id: int, db: Session = Depends(get_db)):
    shift = _get_or_404(db, models.ShiftSession, shift_id)
    runs = (
        db.query(models.ProductionRun)
        .filter(models.ProductionRun.shift_id == shift_id)
        .order_by(models.ProductionRun.seq)
        .all()
    )
    summary = (
        db.query(models.ShiftSummary)
        .filter(models.ShiftSummary.shift_id == shift_id)
        .order_by(models.ShiftSummary.version.desc())
        .first()
    )
    return {
        **_shift_dict(shift),
        "runs": [_run_dict(r) for r in runs],
        "summary": summary.payload if summary else None,
    }


@router.get("/shifts/{shift_id}/summary")
def get_shift_summary(shift_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, models.ShiftSession, shift_id)
    summary = (
        db.query(models.ShiftSummary)
        .filter(models.ShiftSummary.shift_id == shift_id)
        .order_by(models.ShiftSummary.version.desc())
        .first()
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="No summary yet (shift not closed)")
    return summary.payload

@router.post("/shifts/{shift_id}/close")
def close_shift(
    shift_id: int,
    payload: ShiftClose,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None),
):
    shift = _get_or_404(db, models.ShiftSession, shift_id)

    # Idempotent: already finalized -> return the stored summary.
    if shift.status == "CLOSED":
        summary = (
            db.query(models.ShiftSummary)
            .filter(models.ShiftSummary.shift_id == shift_id)
            .order_by(models.ShiftSummary.version.desc())
            .first()
        )
        if summary:
            return summary.payload
        return _shift_dict(shift)

    # Finalize IN_PROGRESS or AUTO_CLOSED -> CLOSED (late submission allowed).
    requested_end = payload.ended_at
    if requested_end is not None:
        if requested_end.tzinfo is None:
            requested_end = requested_end.replace(tzinfo=timezone.utc)
        if requested_end < shift.started_at:
            raise HTTPException(status_code=422, detail="ended_at is before the shift start")
        if requested_end > _utcnow() + timedelta(minutes=10):
            raise HTTPException(status_code=422, detail="ended_at is in the future")
    if shift.ended_at is None:
        shift.ended_at = requested_end or _utcnow()
    elif requested_end is not None:
        shift.ended_at = requested_end
    shift.status = "CLOSED"
    shift.closed_at = _utcnow()
    shift.closed_by = current_user.id
    # A closed shift must not leave phantom open runs behind.
    shift_lifecycle.close_shift_runs(db, shift, shift.ended_at)

    for m in payload.material_logs:
        db.add(models.MaterialLog(
            shift_id=shift.id,
            run_id=m.get("run_id"),
            material_id=m.get("material_id"),
            category=m.get("category", "UNSPECIFIED"),
            batch_no=m.get("batch_no"),
            qty_kg=m.get("qty_kg", 0),
            source=m.get("source", "manual"),
        ))
    for s in payload.scrap_logs:
        db.add(models.ScrapLog(
            shift_id=shift.id,
            run_id=s.get("run_id"),
            reason_code=s.get("reason_code", "UNSPECIFIED"),
            qty_kg=s.get("qty_kg", 0),
            recorded_at=shift.ended_at,
        ))

    summary_payload = _build_shift_summary(db, shift, payload.manual_quality, idempotency_key)
    prev_version = (
        db.query(func.max(models.ShiftSummary.version))
        .filter(models.ShiftSummary.shift_id == shift.id)
        .scalar()
    ) or 0
    version = prev_version + 1
    db.add(models.ShiftSummary(
        shift_id=shift.id,
        version=version,
        payload=summary_payload,
        input_fingerprint=aggregation.fingerprint(summary_payload),
        is_stale=False,
    ))
    odoo_outbound.enqueue_shift_summary(db, shift.id, version, summary_payload)
    db.commit()
    return summary_payload


@router.post("/shifts/{shift_id}/switch-mo")
def switch_mo(
    shift_id: int,
    payload: SwitchMoPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Switch the active Manufacturing Order within an open shift.

    Closes the current open ProductionRun (stamped with ``end_counter``) and opens a
    new one, starting now, for the selected PO/MO on the same machine. Choosing the
    MO that is already active is a no-op. Audited in ``run_change_log``.
    """
    shift = _get_or_404(db, models.ShiftSession, shift_id)
    po = shift_lifecycle.resolve_po(db, payload.po_id, payload.mo_ref)
    if po is None:
        raise HTTPException(status_code=404, detail="No matching purchase order found")
    try:
        run, changed = shift_lifecycle.switch_mo(
            db, shift, current_user.id, po, end_counter=payload.end_counter
        )
        db.commit()
    except LifecycleError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Machine already has an open run - refresh and retry.")
    db.refresh(run)
    return {**_run_dict(run), "spec_snapshot": run.spec_snapshot,
            "specs": _spec_limits_payload(aggregation.load_run_specs(db, run)), "changed": changed}


@router.post("/shifts/{shift_id}/change-machine")
def change_machine(
    shift_id: int,
    payload: ChangeMachinePayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Move the operator's shift to another machine (same MO unless one is given).

    The current run is closed (with the final counter of the machine being left) and
    a new run starts on the new machine. The shift stays open, so rods, QC checks and
    reports follow the run - no need to close the shift and open another one."""
    shift = _get_or_404(db, models.ShiftSession, shift_id)
    po = shift_lifecycle.resolve_po(db, payload.po_id, payload.mo_ref)
    try:
        run = shift_lifecycle.change_machine(
            db, shift, current_user.id, payload.machine_id,
            end_counter=payload.end_counter, po=po,
        )
        db.commit()
    except LifecycleError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Machine already has an open run - refresh and retry.")
    db.refresh(shift)
    db.refresh(run)
    return {**_shift_dict(shift), **_run_payload(db, run)}


@router.post("/runs/{run_id}/reassign")
def reassign_run(
    run_id: int,
    payload: ReassignRunPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Supervisor correction of a CLOSED run's MO and / or machine.

    Cascades to the run's QC checks and linked report(s), marks the latest shift
    summary stale and writes an audit row. A run already synced to Odoo can only be
    corrected by an admin."""
    _require_supervisor(current_user)
    run = _get_or_404(db, models.ProductionRun, run_id)
    po = shift_lifecycle.resolve_po(db, payload.po_id, payload.mo_ref)
    if (payload.po_id is not None or payload.mo_ref) and po is None:
        raise HTTPException(status_code=404, detail="No matching purchase order found")
    try:
        result = run_corrections.reassign_run(
            db, run, current_user, po=po, machine_id=payload.machine_id,
            reason=payload.reason, allow_synced=_is_admin(current_user),
        )
        db.commit()
    except LifecycleError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Machine already has an open run - refresh and retry.")
    db.refresh(run)
    return {**result, "run": _run_dict(run)}


@router.get("/runs/{run_id}/changes")
def run_changes(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _get_or_404(db, models.ProductionRun, run_id)
    rows = (
        db.query(models.RunChangeLog)
        .filter(models.RunChangeLog.run_id == run_id)
        .order_by(models.RunChangeLog.id)
        .all()
    )
    return [
        {"id": c.id, "run_id": c.run_id, "shift_id": c.shift_id, "user_id": c.user_id,
         "action": c.action, "old": c.old_values, "new": c.new_values, "reason": c.reason,
         "created_at": c.created_at.isoformat() if c.created_at else None}
        for c in rows
    ]


@router.post("/shifts/{shift_id}/stop")
def stop_shift(
    shift_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Stop an active shift WITHOUT finalizing: mark AUTO_CLOSED, keep all data.

    No shift summary or Odoo sync is produced; the shift can be reopened later or
    finalized via a retroactive report submission.
    """
    shift = _get_or_404(db, models.ShiftSession, shift_id)
    if shift.ended_at is not None:
        raise HTTPException(status_code=409, detail="Shift is not active")
    now = _utcnow()
    shift.status = "AUTO_CLOSED"
    shift.ended_at = now
    shift.closed_at = now
    shift.closed_by = current_user.id
    shift_lifecycle.close_shift_runs(db, shift, now)
    db.commit()
    db.refresh(shift)
    return _shift_dict(shift)


@router.post("/shifts/{shift_id}/discard")
def discard_shift(
    shift_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Soft-delete an AUTO_CLOSED/CLOSED shift that has no production data.

    Empty test sessions can be removed from the pending list; a shift that already
    holds rods, reports, QC checks or material/scrap is refused so no real data can
    ever be discarded. Supervisor (manager/admin) only."""
    _require_supervisor(current_user)
    shift = _get_or_404(db, models.ShiftSession, shift_id)
    if shift.status == "DISCARDED":
        return _shift_dict(shift)
    if shift.ended_at is None or shift.status == "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Only an auto-closed / closed shift can be discarded")

    run_ids = [r[0] for r in db.query(models.ProductionRun.id).filter(models.ProductionRun.shift_id == shift.id).all()]

    rods_q = db.query(models.QualityMeasurement).filter(models.QualityMeasurement.shift_id == shift.id)
    reports_q = db.query(models.ProductionReport).filter(models.ProductionReport.shift_id == shift.id)
    if run_ids:
        rods_q = rods_q.filter(
            (models.QualityMeasurement.shift_id == shift.id) | models.QualityMeasurement.run_id.in_(run_ids)
        )
        reports_q = reports_q.filter(
            (models.ProductionReport.shift_id == shift.id) | models.ProductionReport.run_id.in_(run_ids)
        )

    checks = {
        "rods": rods_q.count(),
        "samples": db.query(models.QualitySample).filter(models.QualitySample.shift_id == shift.id).count(),
        "reports": reports_q.count(),
        "qc_checks": db.query(models.ManualQualityCheck).filter(models.ManualQualityCheck.shift_id == shift.id).count(),
        "material": db.query(models.MaterialLog).filter(models.MaterialLog.shift_id == shift.id).count(),
        "scrap": db.query(models.ScrapLog).filter(models.ScrapLog.shift_id == shift.id).count(),
        "summary": db.query(models.ShiftSummary).filter(models.ShiftSummary.shift_id == shift.id).count(),
    }
    blockers = {k: v for k, v in checks.items() if v}
    if blockers:
        raise HTTPException(status_code=409, detail=f"Shift has production data and cannot be discarded: {blockers}")

    shift.status = "DISCARDED"
    shift.closed_at = shift.closed_at or _utcnow()
    shift.closed_by = shift.closed_by or current_user.id
    db.commit()
    db.refresh(shift)
    return _shift_dict(shift)


def _build_shift_summary(
    db: Session,
    shift: models.ShiftSession,
    manual_quality: Optional[Dict[str, Dict[str, Optional[float]]]],
    idempotency_key: Optional[str],
) -> Dict[str, Any]:
    runs = (
        db.query(models.ProductionRun)
        .filter(models.ProductionRun.shift_id == shift.id)
        .order_by(models.ProductionRun.seq)
        .all()
    )
    run_summaries = []
    for run in runs:
        s = aggregation.compute_run_summary(db, run, manual=manual_quality)
        s["seq"] = run.seq
        manual_rows = s["manual_checks"]  # individual rows (from compute_run_summary)
        s["manual_checks"] = _manual_checks_summary(db, run.id)
        s["manual_check_rows"] = manual_rows
        run_summaries.append(s)
    verdict = _overall_verdict([r["status"] for r in run_summaries])
    return {
        "schema_version": "1.2",
        "idempotency_key": idempotency_key or f"mes:shift:{shift.id}:v1",
        "shift": {
            "machine_id": shift.machine_id,
            "started_at": shift.started_at.isoformat() if shift.started_at else None,
            "ended_at": shift.ended_at.isoformat() if shift.ended_at else None,
            "operator_id": shift.operator_id,
            "plant_tz": shift.plant_tz,
            "verdict": verdict,
        },
        "runs": run_summaries,
    }


# ---------------------------------------------------------------------------
# Measurements (rod-level retrieval)
# ---------------------------------------------------------------------------

def _rods_response(rods: List[models.QualityMeasurement], fmt: str, specs: Optional[Dict] = None) -> Any:
    rows = [_rod_dict(r, specs) for r in rods]
    if fmt == "csv":
        cols = list(_MEASUREMENT_COLS) + ["rejected", "is_outlier", "pressure_drop", "synthetic_timestamp", "x"]
        buf = io.StringIO()
        writer = _csv.DictWriter(buf, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=measurements.csv"},
        )
    return rows


def _load_shift_specs(db: Session, shift_id: int) -> Dict:
    runs = (
        db.query(models.ProductionRun)
        .filter(models.ProductionRun.shift_id == shift_id)
        .all()
    )
    merged: Dict = {}
    for run in runs:
        for key, spec in aggregation.load_run_specs(db, run).items():
            merged.setdefault(key, spec)
    return merged


def _shift_po(db: Session, shift) -> Optional[models.PurchaseOrder]:
    run = (
        db.query(models.ProductionRun)
        .filter(models.ProductionRun.shift_id == shift.id, models.ProductionRun.po_id.isnot(None))
        .order_by(models.ProductionRun.seq.desc())
        .first()
    )
    return db.get(models.PurchaseOrder, run.po_id) if run is not None else None


def _shift_interval(shift) -> Optional[str]:
    if shift.started_at is None:
        return None
    start = _bud(shift.started_at)
    if shift.ended_at is not None:
        end = _bud(shift.ended_at)
        return f"{start.strftime('%d.%m.%Y %H:%M')} – {end.strftime('%H:%M')}"
    return f"{start.strftime('%d.%m.%Y %H:%M')} – open"


def _shift_quality_report_data(db: Session, shift) -> Dict[str, Any]:
    """Everything the printable Shift Quality Report needs (header + tables + series)."""
    summary = _shift_quality_summary(db, shift.id)

    po = _shift_po(db, shift)
    machine = db.get(models.Machine, shift.machine_id) if shift.machine_id else None
    machine_name = machine.name if machine else None
    if not machine_name:
        rep = (
            db.query(models.ProductionReport)
            .filter(models.ProductionReport.shift_id == shift.id)
            .order_by(models.ProductionReport.id.desc())
            .first()
        )
        machine_name = rep.machine_name if rep else None
    operator = db.get(models.User, shift.operator_id) if shift.operator_id else None
    lot_no = lot_number(shift.started_at, machine_name)

    checks = (
        db.query(models.ManualQualityCheck)
        .filter(
            models.ManualQualityCheck.shift_id == shift.id,
            models.ManualQualityCheck.voided_at.is_(None),
        )
        .order_by(models.ManualQualityCheck.measured_at, models.ManualQualityCheck.id)
        .all()
    )
    users = {u.id: u.username for u in db.query(models.User).all()}
    manual_checks = [
        {
            "time": _bud(c.measured_at or c.created_at).strftime("%H:%M") if (c.measured_at or c.created_at) else None,
            "operator": users.get(c.operator_id),
            "length_mm": _num(c.length_mm),
            "weight_g": _num(c.sample_weight),
            "hardness": _num(c.hardness),
            "glue_seam": c.glue_seam_ok,
            "cut_quality": c.cut_quality_ok,
            "visual": c.visual_appearance_ok,
            "notes": c.notes,
        }
        for c in checks
    ]

    # Rod-level series for the trend charts (diameter / PD over the shift).
    rods = (
        db.query(models.QualityMeasurement)
        .filter(models.QualityMeasurement.shift_id == shift.id)
        .order_by(models.QualityMeasurement.measured_at, models.QualityMeasurement.id)
        .all()
    )
    series = {
        "diameter": [v for v in (_num(r.diameter) for r in rods) if v is not None],
        "pd": [v for v in (_num(r.pd) for r in rods) if v is not None],
    }

    header = {
        "po_number": po.po_number if po else None,
        "lot_number": lot_no,
        "spec_string": _po_spec_string(po),
        "machine": machine_name,
        "date": _bud(shift.started_at).date().isoformat() if shift.started_at else None,
        "interval": _shift_interval(shift),
        "operator": operator.username if operator else None,
    }
    return {
        "header": header,
        "certificate": summary.get("certificate", []),
        "manual_checks": manual_checks,
        "series": series,
        "remarks": summary.get("remarks"),
    }


def _shift_quality_summary(db: Session, shift_id: int, run_id: Optional[int] = None) -> Dict[str, Any]:
    """Aggregate quality stats for ALL rods in a shift (shift-level).

    Rods are only reliably linked to shifts (the station data has no PO/MO ref),
    so the internal quality summary is shift-level rather than run-level.
    """
    specs = _load_shift_specs(db, shift_id)
    rods = (
        db.query(models.QualityMeasurement)
        .filter(models.QualityMeasurement.shift_id == shift_id)
        .all()
    )
    rod_dicts = [
        {
            "pd": r.pd, "weight": r.weight, "diameter": r.diameter,
            "ovality": r.ovality, "roundness": r.roundness,
            "shape": r.shape, "hardness": r.hardness,
        }
        for r in rods
    ]
    stats = compute_run_stats(rod_dicts, specs)
    auto_rows = certificate_rows(stats, specs)
    checks_query = db.query(models.ManualQualityCheck).filter(
        models.ManualQualityCheck.voided_at.is_(None)
    )
    if run_id is not None:
        # A single-report modal is scoped to its production run; a shift-level
        # view spans every run of the shift.
        checks_query = checks_query.filter(models.ManualQualityCheck.mo_id == run_id)
    else:
        checks_query = checks_query.filter(models.ManualQualityCheck.shift_id == shift_id)
    checks = checks_query.order_by(models.ManualQualityCheck.id).all()
    check_dicts = aggregation.manual_check_dicts(checks)
    merge_manual_parameters(stats["parameters"], manual_rods(check_dicts), specs)
    return {
        "status": stats["status"],
        "rods_total": stats["rods_total"],
        "rods_rejected": stats["rods_rejected"],
        "rods_used": stats["rods_used"],
        "parameters": stats["parameters"],
        "automatic": auto_rows,
        "certificate": certificate_rows(stats, specs),
        "remarks": aggregation.manual_remarks(check_dicts),
        "manual_measurements": aggregation.manual_measurements(stats["parameters"], check_dicts),
        "manual_checks": aggregation.manual_table_rows(check_dicts),
    }


@router.get("/shifts/{shift_id}/measurements")
def shift_measurements(
    shift_id: int,
    fmt: str = Query(default="json"),
    db: Session = Depends(get_db),
):
    _get_or_404(db, models.ShiftSession, shift_id)
    specs = _load_shift_specs(db, shift_id)
    rods = (
        db.query(models.QualityMeasurement)
        .filter(models.QualityMeasurement.shift_id == shift_id)
        .order_by(models.QualityMeasurement.measured_at, models.QualityMeasurement.sample_id, models.QualityMeasurement.rod_no)
        .all()
    )
    if fmt == "csv":
        return _rods_response(rods, fmt, specs)
    return {
        "shift_id": shift_id,
        "specs": _spec_limits_payload(specs),
        "rods": [_rod_dict(r, specs) for r in rods],
    }


@router.get("/runs/{run_id}/measurements")
def run_measurements(
    run_id: int,
    fmt: str = Query(default="json"),
    db: Session = Depends(get_db),
):
    run = _get_or_404(db, models.ProductionRun, run_id)
    specs = aggregation.load_run_specs(db, run)
    rods = (
        db.query(models.QualityMeasurement)
        .filter(models.QualityMeasurement.run_id == run_id)
        .order_by(models.QualityMeasurement.measured_at, models.QualityMeasurement.sample_id, models.QualityMeasurement.rod_no)
        .all()
    )
    return _rods_response(rods, fmt, specs)


# ---------------------------------------------------------------------------
# Quality summary / certificate
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/quality")
def run_quality(run_id: int, db: Session = Depends(get_db)):
    run = _get_or_404(db, models.ProductionRun, run_id)
    return aggregation.compute_run_summary(db, run)


@router.get("/shifts/{shift_id}/quality")
def shift_quality(shift_id: int, db: Session = Depends(get_db)):
    shift = _get_or_404(db, models.ShiftSession, shift_id)
    runs = (
        db.query(models.ProductionRun)
        .filter(models.ProductionRun.shift_id == shift_id)
        .order_by(models.ProductionRun.seq)
        .all()
    )
    run_summaries = []
    for run in runs:
        s = aggregation.compute_run_summary(db, run)
        s["seq"] = run.seq
        run_summaries.append(s)
    return {
        "shift_id": shift_id,
        "status": _overall_verdict([r["status"] for r in run_summaries]),
        "runs": run_summaries,
    }


@router.get("/reports/{report_id}/quality")
def report_quality(report_id: int, db: Session = Depends(get_db)):
    """Internal (shift-level) quality summary for one legacy production report.

    Resolves report -> shift via legacy_report_key and returns pre-computed stats
    over ALL rods in that shift (the station data has no PO/MO reference, so rods
    cannot be attributed to a specific run reliably).
    """
    report = _get_or_404(db, models.ProductionReport, report_id)
    legacy_key = f"{report.machine_name}|{report.report_date}|{report.shift_name}"
    shift = (
        db.query(models.ShiftSession)
        .filter(models.ShiftSession.legacy_report_key == legacy_key)
        .first()
    )
    if shift is None:
        return {
            "report_id": report_id, "shift_id": None,
            "samples_count": 0, "status": "NO_DATA",
            "parameters": {}, "certificate": [], "series": None,
        }
    samples_count = (
        db.query(models.QualitySample)
        .filter(models.QualitySample.shift_id == shift.id)
        .count()
    )
    summary = _shift_quality_summary(db, shift.id)
    specs = _load_shift_specs(db, shift.id)
    rods = (
        db.query(models.QualityMeasurement)
        .filter(models.QualityMeasurement.shift_id == shift.id)
        .order_by(
            models.QualityMeasurement.measured_at,
            models.QualityMeasurement.sample_id,
            models.QualityMeasurement.rod_no,
        )
        .all()
    )
    series = _series_payload(specs, rods)
    return {
        **summary,
        "report_id": report_id,
        "shift_id": shift.id,
        "samples_count": samples_count,
        "series": series,
    }


# ---------------------------------------------------------------------------
# Ingest + relink
# ---------------------------------------------------------------------------

@router.post("/quality/ingest")
async def ingest_quality(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_ingest_identity),
):
    """Ingest one station file (multipart) through the same parse -> resolve -> insert pipeline."""
    data = await file.read()

    try:
        sample, profile = profiles.parse_file_with_profile(
            db, data, "quantum_neo", os.getenv("STATION_MO_FIELD", "batch_description")
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"parse failed: {exc}")

    sha256 = hashlib.sha256(data).hexdigest()
    if db.query(models.IngestionFile).filter(models.IngestionFile.sha256 == sha256).first():
        return {"status": "duplicate", "sha256": sha256, "filename": file.filename}

    machine_id = shift_resolver.resolve_machine(db, "quantum_neo", "maker", sample.maker)
    produced_at = local_to_utc(sample.produced_on) or _utcnow()

    kind, is_non_production = shift_resolver.classify_sample(sample.maker)
    shift_id, link_status = (None, shift_resolver.LINK_NON_PRODUCTION) if is_non_production else shift_resolver.resolve_shift(db, machine_id, produced_at)
    run_id: Optional[int] = None
    if shift_id is not None:
        run_id, run_status = shift_resolver.resolve_run(
            db, shift_id, produced_at, sample.mo_ref, machine_id=machine_id
        )
        if run_status == shift_resolver.LINK_MO_MISMATCH:
            link_status = shift_resolver.LINK_MO_MISMATCH

    db_sample = models.QualitySample(
        shift_id=shift_id, run_id=run_id, machine_id=machine_id,
        link_status=link_status, link_source="auto", kind=kind,
        source_instrument_id=sample.instrument_id,
        source_maker=sample.maker, source_team=sample.team,
        sample_id=sample.sample_id, mo_ref=sample.mo_ref,
        brand=sample.brand, operator=sample.operator,
        comments=sample.reserve_1,
        produced_at=produced_at,
        batch_started_at=local_to_utc(sample.batch_start),
        batch_ended_at=local_to_utc(sample.batch_end),
        rods_declared=sample.rods_count,
        file_sha256=sha256,
        custom_metrics=profiles.compute_custom_metrics(sample, profile),
    )
    db.add(db_sample)
    db.flush()
    for rod in sample.rods:
        db.add(models.QualityMeasurement(
            sample_id=db_sample.id, shift_id=shift_id, run_id=run_id, machine_id=machine_id,
            measured_at=produced_at, rod_no=rod.rod_no, pd=rod.pd, weight=rod.weight,
            diameter=rod.diameter, ovality=rod.ovality, roundness=rod.roundness,
            shape=rod.shape, hardness=rod.hardness, length=rod.length,
        ))
    db.add(models.IngestionFile(
        sha256=sha256, filename=file.filename, status="processed",
        sample_id=db_sample.id, processed_at=_utcnow(),
    ))
    db.commit()
    return {"status": "processed", "sample_id": db_sample.id, "shift_id": shift_id, "rods": len(sample.rods)}


@router.post("/quality/relink")
def relink_unlinked(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """(admin) Re-run shift/run resolution over samples that are still unlinked."""
    samples = (
        db.query(models.QualitySample)
        .filter(models.QualitySample.shift_id.is_(None))
        .all()
    )
    relinked = 0
    for s in samples:
        if s.machine_id is None or s.produced_at is None:
            continue
        shift_id, link_status = shift_resolver.resolve_shift(db, s.machine_id, s.produced_at)
        if shift_id is not None:
            s.shift_id = shift_id
            s.link_status = link_status
            run_id, run_status = shift_resolver.resolve_run(
                db, shift_id, s.produced_at, s.mo_ref, machine_id=s.machine_id
            )
            if run_status == shift_resolver.LINK_MO_MISMATCH:
                s.link_status = shift_resolver.LINK_MO_MISMATCH
            s.run_id = run_id
            db.query(models.QualityMeasurement).filter(
                models.QualityMeasurement.sample_id == s.id
            ).update({"shift_id": shift_id, "run_id": run_id}, synchronize_session=False)
            relinked += 1
    db.commit()
    return {"total_unlinked": len(samples), "relinked": relinked}


# ---------------------------------------------------------------------------
# Certificate PDF
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/certificate.pdf")
def run_certificate_pdf(run_id: int, db: Session = Depends(get_db)):
    run = _get_or_404(db, models.ProductionRun, run_id)
    summary = aggregation.compute_run_summary(db, run)
    pdf_bytes = _render_certificate_table(
        f"Quality Certificate - Run {run.id}",
        f"MO reference: {run.mo_ref or '(none)'} · Automatic tests done for PD, length, weight "
        f"(parameters taken from auto measurement station) · "
        f"Rods tested: {summary.get('rods_total')} · Rods rejected: {summary.get('rods_rejected')}",
        summary,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=certificate_run_{run_id}.pdf"},
    )


@router.get("/shifts/{shift_id}/certificate.pdf")
def shift_certificate_pdf(shift_id: int, db: Session = Depends(get_db)):
    shift = _get_or_404(db, models.ShiftSession, shift_id)
    from app.pdf_generator import render_shift_quality_pdf

    data = _shift_quality_report_data(db, shift)
    pdf_bytes = render_shift_quality_pdf(data)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=quality_shift_{shift_id}.pdf"},
    )


@router.get("/pos/{po_id}/certificate.pdf")
def po_certificate_pdf(po_id: int, db: Session = Depends(get_db)):
    """Consolidated Quality Certificate for a WHOLE order (all shifts / backorders).

    Statistics are recomputed over every tested rod of the order; a second table lists
    the per-shift results.
    """
    po = _get_or_404(db, models.PurchaseOrder, po_id)
    summary = aggregation.compute_order_summary(db, po.id)
    if not summary["rods_total"]:
        raise HTTPException(status_code=404, detail="No measurements linked to this order yet")
    subtitle = (
        f"Order: {po.po_number} | Status: {summary.get('status')} | "
        f"Tested: {summary['rods_total']} | Rejected: {summary['rods_rejected']} | "
        f"Period: {(summary.get('first_measured_at') or '')[:10]} - "
        f"{(summary.get('last_measured_at') or '')[:10]}"
    )
    pdf_bytes = _render_certificate_table(
        f"Order Quality Certificate - {po.po_number}", subtitle, summary,
        extra_rows=summary.get("runs") or [],
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=order_certificate_{po.po_number}.pdf"},
    )


def _render_certificate_table(
    title: str, subtitle: str, summary: Dict[str, Any], extra_rows: Optional[List[Dict[str, Any]]] = None
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph(title, styles["Title"]))
    story.append(Paragraph(subtitle, styles["Normal"]))
    remarks = (summary.get("remarks") or "").strip()
    if remarks:
        story.append(Paragraph(f"Notes: {remarks}", styles["Normal"]))
        story.append(Spacer(1, 4 * mm))
    story.append(Spacer(1, 8 * mm))

    from app.quality_stats import CERTIFICATE_PARAMS
    cert_by_param = {str(row.get("parameter")): row for row in summary.get("certificate", [])}
    header = ["Parameter", "Unit", "Nominal", "Lower", "Upper", "Mean", "SD", "n"]
    rows = [header]
    for param, label, unit in CERTIFICATE_PARAMS:
        row = cert_by_param.get(param) or {}
        rows.append([
            label, unit,
            _fmt(row.get("nominal")), _fmt(row.get("lower")), _fmt(row.get("upper")),
            _fmt(row.get("mean")), _fmt(row.get("sd")),
            str(row.get("n", "")),
        ])
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(table)

    manual_checks = summary.get("manual_checks") or []
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("Manual measurements", styles["Heading3"]))
    mh = ["Run #", "Weight (mg)", "Length (mm)", "Hardness (%)",
          "Glue Seam (Glucim)", "Cut Quality", "Visual Cleanness", "Notes"]
    mrows = [mh]
    if not manual_checks:
        mrows.append(["", "No manual measurements recorded", "", "", "", "", "", ""])
    else:
        for c in manual_checks:
            mrows.append([
                str(c.get("seq") or ""),
                _fmt(c.get("weight_mg")),
                _fmt(c.get("length_mm")),
                _fmt(c.get("hardness")),
                _ok(c.get("glue_seam_ok")),
                _ok(c.get("cut_quality_ok")),
                _ok(c.get("visual_appearance_ok")),
                str(c.get("notes") or ""),
            ])
    mtable = Table(mrows, repeatRows=1)
    mtable.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(mtable)

    if extra_rows:
        story.append(Spacer(1, 8 * mm))
        story.append(Paragraph("Results per shift / backorder", styles["Heading3"]))
        det = [["Date", "Machine", "Rods tested", "Rejected", "Mean PD", "SD PD",
                "Mean Dia", "SD Dia", "Status"]]
        for r in extra_rows:
            p = r.get("parameters") or {}
            pd, dia = p.get("pd") or {}, p.get("diameter") or {}
            det.append([
                (r.get("started_at") or "")[:10], str(r.get("machine") or ""),
                str(r.get("rods_total", "")), str(r.get("rods_rejected", "")),
                _fmt(_round(pd.get("mean"), 1)), _fmt(_round(pd.get("sd_samp"), 2)),
                _fmt(_round(dia.get("mean"), 3)), _fmt(_round(dia.get("sd_samp"), 4)),
                str(r.get("status", "")),
            ])
        dtable = Table(det, repeatRows=1)
        dtable.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ]))
        story.append(dtable)
    doc.build(story)
    return buf.getvalue()


def _round(value: Any, digits: int) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _fmt(value: Any) -> str:
    return "" if value is None else f"{value}"


def _ok(value: Any) -> str:
    if value is None:
        return "-"
    return "OK" if value else "FAIL"


# ---------------------------------------------------------------------------
# Odoo outbox (admin)
# ---------------------------------------------------------------------------

@router.get("/odoo-outbox")
def list_outbox(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    q = db.query(models.OdooOutbox)
    if status:
        q = q.filter(models.OdooOutbox.status == status)
    return [
        {
            "id": o.id, "aggregate_type": o.aggregate_type, "aggregate_id": o.aggregate_id,
            "idempotency_key": o.idempotency_key, "status": o.status,
            "attempts": o.attempts, "next_attempt_at": o.next_attempt_at,
            "odoo_model": o.odoo_model, "odoo_id": o.odoo_id, "last_error": o.last_error,
        }
        for o in q.order_by(models.OdooOutbox.id.desc()).limit(200).all()
    ]


@router.post("/odoo-outbox/{outbox_id}/retry")
def retry_outbox(
    outbox_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    o = _get_or_404(db, models.OdooOutbox, outbox_id)
    o.status = "pending"
    o.attempts = (o.attempts or 0) + 1
    o.next_attempt_at = _utcnow()
    o.last_error = None
    db.commit()
    return {"id": o.id, "status": o.status, "attempts": o.attempts}


@router.post("/odoo/sync-inbound")
def sync_odoo_inbound(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Fetch open MOs from Odoo and link local runs/POs (admin only)."""
    if current_user.username != "superadmin":
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.odoo import inbound as odoo_inbound
    from app.services.odoo.client import OdooClient, OdooConfig

    cfg = OdooConfig.from_env()
    if not (cfg.enabled and cfg.valid()):
        raise HTTPException(status_code=400, detail="Odoo is not configured")
    client = OdooClient(cfg)
    client.connect()
    return odoo_inbound.sync_open_mos(db, client)


@router.post("/odoo/sync-orders")
def sync_odoo_orders(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Pull root MOs from Odoo by scope and link them to local orders (admin only)."""
    if current_user.username != "superadmin":
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.odoo import inbound as odoo_inbound
    from app.services.odoo.client import OdooClient, OdooConfig

    cfg = OdooConfig.from_env()
    if not (cfg.enabled and cfg.valid()):
        raise HTTPException(status_code=400, detail="Odoo is not configured")
    client = OdooClient(cfg)
    client.connect()
    return odoo_inbound.sync_orders(
        db,
        client,
        scope=str(payload.get("scope", "active")),
        date_from=payload.get("date_from"),
        date_to=payload.get("date_to"),
    )


@router.post("/odoo/link-order")
def link_odoo_order(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Manually link an Odoo MO chain to a local order (or create new)."""
    _require_superadmin(current_user)
    from app.services.odoo import inbound as odoo_inbound
    from app.services.odoo.client import OdooError

    client = _odoo_client_checked()
    odoo_mo_id = int(payload.get("odoo_mo_id") or 0)
    local_mo_id = payload.get("local_mo_id")
    if local_mo_id is not None:
        local_mo_id = int(local_mo_id)
    try:
        return odoo_inbound.link_order(db, client, odoo_mo_id, local_mo_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except OdooError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Odoo unreachable: {exc}")


@router.post("/orders/{order_id}/ignore-odoo")
def ignore_odoo_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Mark an unlinked order as not-for-Odoo (test/junk entries).

    Nothing is deleted (invariant #2); the order leaves the unlinked review list
    and keeps ``sync_mode=link_only`` so it can never post to Odoo.
    """
    _require_superadmin(current_user)
    po = _get_or_404(db, models.PurchaseOrder, order_id)
    if po.odoo_mo_id is not None:
        raise HTTPException(status_code=409, detail="Order is linked to an Odoo MO; unlink it first")
    po.odoo_state = "ignored"
    po.sync_mode = "link_only"
    db.commit()
    return {"id": po.id, "po_number": po.po_number, "odoo_state": po.odoo_state}


@router.post("/odoo/reconcile")
def odoo_reconcile(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Re-read the Odoo MO chain of every linked, unfinished order (admin only)."""
    _require_superadmin(current_user)
    from app.services.odoo import reconcile as odoo_reconcile_svc
    from app.services.odoo.client import OdooClient, OdooConfig

    cfg = OdooConfig.from_env()
    if not (cfg.enabled and cfg.valid()):
        raise HTTPException(status_code=400, detail="Odoo is not configured")
    client = OdooClient(cfg)
    client.connect()
    return odoo_reconcile_svc.reconcile_all(db, client)


@router.get("/odoo/unlinked-orders")
def odoo_unlinked_orders(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Propose Odoo MOs for orders without a link (read-only, one-time cleanup).

    Confirm each proposal with ``POST /odoo/link-order``; nothing is written here.
    An unreachable Odoo yields a 502 with a structured body, never a bare 500.
    """
    _require_superadmin(current_user)
    from app.services.odoo import reconcile as odoo_reconcile_svc
    from app.services.odoo.client import OdooError

    client = _odoo_client_checked()
    try:
        result = odoo_reconcile_svc.suggest_unlinked_orders(db, client)
    except OdooError as exc:
        raise HTTPException(status_code=502, detail={
            "ok": False, "error": str(exc), "orders": 0, "matched": [], "unmatched": [],
        })
    result["ok"] = True
    return result


@router.post("/odoo/dispatch")
def dispatch_odoo_now(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Dispatch pending outbox items to Odoo now (admin only).

    Respects the runtime shadow-mode setting (same value the worker uses).
    """
    _require_superadmin(current_user)
    from app.database import SessionLocal

    cfg = odoo_outbound.OdooConfig.from_env()
    if not (cfg.enabled and cfg.valid()):
        raise HTTPException(status_code=400, detail="Odoo is not configured")
    shadow = odoo_outbound.shadow_enabled(db)
    return {
        "dispatched": odoo_outbound.dispatch_pending(SessionLocal, cfg, shadow=shadow),
        "shadow": shadow,
    }


def _require_superadmin(user: models.User) -> None:
    if user.username != "superadmin":
        raise HTTPException(status_code=403, detail="Admin only")


def _odoo_client_checked():
    """Return a connected OdooClient, or raise a friendly HTTP error."""
    from app.services.odoo.client import OdooClient, OdooConfig, OdooError

    cfg = OdooConfig.from_env()
    if not (cfg.enabled and cfg.valid()):
        raise HTTPException(status_code=400, detail="Odoo is not configured (check .env)")
    client = OdooClient(cfg)
    try:
        client.connect()
    except OdooError as exc:
        raise HTTPException(status_code=502, detail=f"Odoo unreachable: {exc}")
    return client


@router.get("/odoo/status")
def odoo_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """One source of truth for the UI: config, shadow mode and Odoo reachability."""
    _require_superadmin(current_user)
    from app.services.odoo.client import OdooClient, OdooConfig

    cfg = OdooConfig.from_env()
    configured = bool(cfg.enabled and cfg.valid())
    shadow = odoo_outbound.shadow_enabled(db)
    reachable = False
    error = None
    if configured:
        client = OdooClient(cfg)
        try:
            client.connect()
            reachable = True
        except Exception as exc:  # noqa: BLE001 - status must never 500
            error = str(exc)
    counts = {
        status: db.query(models.OdooOutbox).filter(models.OdooOutbox.status == status).count()
        for status in ("pending", "shadowed", "sent", "failed")
    }
    return {
        "configured": configured,
        "shadow": shadow,
        "odoo_reachable": reachable,
        "connect_error": error,
        "outbox": counts,
    }


@router.put("/odoo/shadow-mode")
def set_odoo_shadow_mode(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Turn shadow mode on/off at runtime; the dispatcher reads this each loop."""
    _require_superadmin(current_user)
    enabled = bool(payload.get("enabled", True))
    odoo_outbound.set_shadow_enabled(db, enabled)
    return {"shadow": enabled}


@router.get("/odoo/mos")
def odoo_mos(
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Odoo MO chains for the manual link picker (search by MO name/Source/PO no.)."""
    _require_superadmin(current_user)
    from app.services.odoo import reconcile as odoo_reconcile_svc

    client = _odoo_client_checked()
    chains = odoo_reconcile_svc._chain_rows(client)
    # Exact Source / MO-number matches are ranked first and the limit is applied
    # after ranking, so an exact hit is never cut off by the page size.
    ranked = odoo_reconcile_svc.rank_chains(chains, q, limit)
    return [
        {
            "root_id": chain["root_id"],
            "root_name": chain["root_name"],
            "state": chain["state"],
            "mo_count": chain["mo_count"],
            "start": chain["start"].isoformat() if chain["start"] else None,
            "total_rods": round(chain["total_rods"]),
        }
        for chain in ranked
    ]


@router.get("/odoo/products")
def odoo_products(
    category: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Manual material-mapping picker feed: Odoo products with UoM info."""
    _require_superadmin(current_user)
    from app.services.odoo import mapping as odoo_mapping

    client = _odoo_client_checked()
    return odoo_mapping.list_products(client, category=category, q=q, limit=limit)


@router.get("/odoo/material-mapping")
def odoo_material_mapping(
    suggest: bool = Query(False, description="Also query Odoo for name-match suggestions"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Local materials with their Odoo link state (admin only).

    The 17 local materials are ALWAYS listed, even when Odoo is offline or
    suggestions fail; in that case ``suggest_error`` explains why.
    """
    _require_superadmin(current_user)
    from app.services.odoo import mapping as odoo_mapping

    products = None
    suggest_error = None
    if suggest:
        try:
            client = _odoo_client_checked()
            products = odoo_mapping.fetch_candidate_products(client)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - never hide the material list
            suggest_error = str(exc)
    overview = odoo_mapping.build_mapping_overview(db, products)
    overview["suggest_error"] = suggest_error
    return overview


@router.post("/odoo/material-mapping")
def odoo_confirm_material_mapping(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Explicitly confirm (or remove with force) one material -> Odoo product link."""
    _require_superadmin(current_user)
    from app.services.odoo import mapping as odoo_mapping

    try:
        return odoo_mapping.confirm_mapping(
            db,
            int(payload.get("material_id") or 0),
            payload.get("odoo_product_id"),
            payload.get("odoo_uom_id"),
            force=bool(payload.get("force", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/odoo/orders-sync")
def list_odoo_orders_sync(
    suggest: bool = Query(False, description="Also propose Odoo MO chains for unlinked orders"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Orders with their Odoo link state, sync mode and MO state (admin only).

    Lightweight view for the Odoo Sync screen; the full order list stays on the
    legacy ``/purchase-orders`` endpoint.

    Without ``suggest`` the response is the plain list (backwards compatible). With
    ``suggest=true`` it is ``{"orders": [...], "suggest_error": str | None}``; every
    unlinked order carries ``suggestions`` (read-only matcher candidates), and the
    order list is ALWAYS returned even when Odoo is unreachable.
    """
    _require_superadmin(current_user)
    rows = db.query(models.PurchaseOrder).order_by(models.PurchaseOrder.id.desc()).all()
    payload = [
        {
            "id": o.id,
            "po_number": o.po_number,
            "odoo_mo_id": o.odoo_mo_id,
            "odoo_mo_name": o.odoo_mo_name,
            "odoo_current_mo_id": o.odoo_current_mo_id,
            "sync_mode": o.sync_mode,
            "odoo_state": o.odoo_state,
            "odoo_qty_drift": float(o.odoo_qty_drift) if o.odoo_qty_drift is not None else None,
            "target_qty": o.target_qty,
            "source": o.source,
        }
        for o in rows
    ]
    if not suggest:
        return payload

    # Suggestions are read-only and must never hide the order list (same contract as
    # /odoo/material-mapping): any Odoo/matcher failure is reported in suggest_error.
    from app.services.odoo import reconcile as odoo_reconcile_svc

    suggest_error = None
    try:
        client = _odoo_client_checked()
        review = odoo_reconcile_svc.suggest_unlinked_orders(db, client)["review"]
        payload = odoo_reconcile_svc.attach_suggestions(payload, review)
    except HTTPException as exc:
        suggest_error = str(exc.detail)
    except Exception as exc:  # noqa: BLE001 - never hide the order list
        suggest_error = str(exc)
    if suggest_error is not None:
        payload = [dict(p, suggestions=[]) for p in payload]
    return {"orders": payload, "suggest_error": suggest_error}


@router.put("/orders/{order_id}/sync-mode")
def set_order_sync_mode(
    order_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Set an order's Odoo sync mode: ``full`` (post completion) or ``link_only``."""
    _require_superadmin(current_user)
    mode = str(payload.get("sync_mode", "")).strip().lower()
    if mode not in ("full", "link_only"):
        raise HTTPException(status_code=400, detail="sync_mode must be 'full' or 'link_only'")
    po = _get_or_404(db, models.PurchaseOrder, order_id)
    if mode == "full" and po.odoo_mo_id is None:
        raise HTTPException(status_code=409, detail="Order is not linked to an Odoo MO")
    po.sync_mode = mode
    db.commit()
    return {"id": po.id, "po_number": po.po_number, "sync_mode": po.sync_mode}


@router.post("/orders/{order_id}/close")
def close_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Finalize an order (admin): compute cumulative production + consolidated
    quality, mark it COMPLETED, render the Summary PDF and — for linked orders
    (regardless of sync_mode) — attach it to the Odoo root MO + latest backorder MO
    and write the ``x_final_*`` consolidated quality fields."""
    _require_superadmin(current_user)
    po = _get_or_404(db, models.PurchaseOrder, order_id)
    from app.services import order_finalize
    push_odoo = po.odoo_mo_id is not None
    return order_finalize.finalize_order(
        db, po, actor=current_user.username, push_odoo=push_odoo)


@router.post("/orders/{order_id}/summary-pdf")
def upload_order_summary_pdf(
    order_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Receive the Flutter-generated consolidated Order Summary PDF.

    Stored on the order so ``finalize_order`` attaches THIS document (root MO +
    latest backorder MO) instead of the ReportLab fallback render.
    """
    role = current_user.role
    is_admin = role is not None and role.role_name.lower() in ("admin", "superadmin")
    can_verify = is_admin or (role is not None and role.can_edit_report)
    if not can_verify:
        raise HTTPException(
            status_code=403,
            detail="Only admin/superadmin (or can_edit_report) may upload the order summary.",
        )
    po = _get_or_404(db, models.PurchaseOrder, order_id)
    pdf_base64 = (payload or {}).get("pdf_base64", "")
    filename = (payload or {}).get("filename", "")
    if not pdf_base64:
        raise HTTPException(status_code=400, detail="No PDF data provided")
    try:
        import base64

        base64.b64decode(pdf_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid base64 PDF data") from exc
    po.order_summary_pdf_base64 = pdf_base64
    po.order_summary_pdf_filename = filename or f"Order_Summary_{po.po_number}.pdf"
    db.commit()

    # If the order was already finalized (e.g. the server-side auto-finalize used
    # the ReportLab fallback because no client had uploaded yet), re-push now so
    # the Flutter PDF replaces it on Odoo (attach_file replaces by name+record).
    pushed = None
    if po.completion_status == "completed" and po.odoo_mo_id:
        from app.services import order_finalize as _of

        pushed = _of.push_order_summary(db, po)

    return {
        "status": "stored",
        "order_id": po.id,
        "filename": po.order_summary_pdf_filename,
        "odoo_attached": (pushed or {}).get("odoo_attached", False),
    }


@router.get("/orders/{order_id}/summary.pdf")
def order_summary_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Download the finalized Order Summary PDF (admin).

    Serves the Flutter-generated PDF when the client uploaded one; otherwise the
    ReportLab fallback render.
    """
    _require_superadmin(current_user)
    po = _get_or_404(db, models.PurchaseOrder, order_id)
    from app.services import order_finalize as _of
    if not po.final_quality:
        raise HTTPException(status_code=404, detail="Order not finalized yet")
    pdf = _of.summary_pdf_bytes(db, po)
    if not pdf:
        raise HTTPException(status_code=500, detail="Failed to render summary PDF")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=order_summary_{po.po_number}.pdf"},
    )


@router.get("/orders/by-mo/{mo_number}/summary-pdf")
def order_summary_pdf_by_mo(
    mo_number: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Download the finalized Order Summary PDF by MO number (admin)."""
    _require_superadmin(current_user)
    po = (
        db.query(models.PurchaseOrder)
        .filter(models.PurchaseOrder.po_number == mo_number)
        .order_by(models.PurchaseOrder.id.desc())
        .first()
    )
    if po is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if not po.final_quality:
        raise HTTPException(status_code=404, detail="Order not finalized yet")
    from app.services import order_finalize as _of
    pdf = _of.summary_pdf_bytes(db, po)
    if not pdf:
        raise HTTPException(status_code=500, detail="Failed to render summary PDF")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=order_summary_{po.po_number}.pdf"},
    )


@router.get("/odoo/order-summary-pdf")
def odoo_order_summary_pdf(
    mo_number: str,
    db: Session = Depends(get_db),
    x_odoo_signature: Optional[str] = Header(default=None, alias="X-Odoo-Signature"),
):
    """Odoo -> MES: fetch the finalized order summary PDF by MO number (HMAC-signed)."""
    _verify_odoo_webhook(mo_number, x_odoo_signature)
    po = (
        db.query(models.PurchaseOrder)
        .filter(models.PurchaseOrder.po_number == mo_number)
        .order_by(models.PurchaseOrder.id.desc())
        .first()
    )
    if po is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if not po.final_quality:
        raise HTTPException(status_code=404, detail="Order not finalized yet")
    from app.services import order_finalize as _of
    pdf = _of.summary_pdf_bytes(db, po)
    if not pdf:
        raise HTTPException(status_code=500, detail="Failed to render summary PDF")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=order_summary_{po.po_number}.pdf"},
    )


@router.get("/odoo/shadow-log")
def odoo_shadow_log(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Odoo writes the dispatcher would have made in shadow mode (admin only)."""
    _require_superadmin(current_user)
    rows = (
        db.query(models.OdooShadowLog)
        .order_by(models.OdooShadowLog.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "shadow_mode": odoo_outbound.shadow_enabled(db),
        "items": [
            {
                "id": r.id, "outbox_id": r.outbox_id, "run_id": r.run_id,
                "odoo_mo_id": r.odoo_mo_id, "link_only": r.link_only,
                "actions": r.actions, "note": r.note, "created_at": r.created_at,
            }
            for r in rows
        ],
    }


@router.post("/odoo/shadow/requeue")
def odoo_shadow_requeue(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Re-queue every ``shadowed`` outbox item as ``pending`` (use when going live).

    Refused while shadow mode is still on - the items would just be shadowed again.
    Runs already shadowed are NOT marked synced, so they will be posted for real.
    """
    _require_superadmin(current_user)
    if odoo_outbound.shadow_enabled(db):
        raise HTTPException(status_code=409, detail="Shadow mode is ON - turn it off before re-queueing")
    updated = (
        db.query(models.OdooOutbox)
        .filter(models.OdooOutbox.status == "shadowed")
        .update(
            {"status": "pending", "next_attempt_at": None, "last_error": None},
            synchronize_session=False,
        )
    )
    db.commit()
    return {"requeued": updated}


def _set_int_setting(db: Session, key: str, raw: Any, minimum: int) -> None:
    """Persist an integer ``{"value": n}`` system setting (skip when ``raw`` is None)."""
    if raw is None:
        return
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{key} must be an integer")
    if value < minimum:
        raise HTTPException(status_code=400, detail=f"{key} must be >= {minimum}")
    row = db.get(models.SystemSetting, key)
    if row is None:
        row = models.SystemSetting(key=key, value={})
        db.add(row)
    row.value = {"value": value}


@router.get("/odoo/sync-settings")
def get_odoo_sync_settings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    row = db.get(models.SystemSetting, "odoo_sync_from_date")
    return {
        "odoo_sync_from_date": ((row.value or {}).get("date") if row else None),
        "odoo_verification_wait_minutes": odoo_outbound.verification_wait_minutes(db),
        "odoo_error_retry_minutes": odoo_outbound.error_retry_minutes(db),
        "odoo_max_attempts": odoo_outbound.max_attempts(db),
        "odoo_poll_seconds": odoo_outbound.poll_seconds(db),
        "odoo_reconcile_minutes": odoo_outbound.reconcile_minutes(db),
    }


@router.put("/odoo/sync-settings")
def set_odoo_sync_settings(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Set the cutover date + dispatch timing knobs (all optional)."""
    _require_superadmin(current_user)
    raw = payload.get("odoo_sync_from_date")
    if raw:
        try:
            datetime.fromisoformat(str(raw))
        except ValueError:
            raise HTTPException(status_code=400, detail="odoo_sync_from_date must be an ISO date/time")
    row = db.get(models.SystemSetting, "odoo_sync_from_date")
    if row is None:
        row = models.SystemSetting(key="odoo_sync_from_date", value={})
        db.add(row)
    row.value = {"date": raw or None}

    _set_int_setting(db, odoo_outbound.VERIFY_WAIT_SETTING_KEY,
                     payload.get("odoo_verification_wait_minutes"), minimum=0)
    _set_int_setting(db, odoo_outbound.ERROR_RETRY_SETTING_KEY,
                     payload.get("odoo_error_retry_minutes"), minimum=0)
    _set_int_setting(db, odoo_outbound.MAX_ATTEMPTS_SETTING_KEY,
                     payload.get("odoo_max_attempts"), minimum=1)
    _set_int_setting(db, odoo_outbound.POLL_SECONDS_SETTING_KEY,
                     payload.get("odoo_poll_seconds"), minimum=1)
    _set_int_setting(db, odoo_outbound.RECONCILE_MINUTES_SETTING_KEY,
                     payload.get("odoo_reconcile_minutes"), minimum=0)
    db.commit()
    return {
        "odoo_sync_from_date": raw or None,
        "odoo_verification_wait_minutes": odoo_outbound.verification_wait_minutes(db),
        "odoo_error_retry_minutes": odoo_outbound.error_retry_minutes(db),
        "odoo_max_attempts": odoo_outbound.max_attempts(db),
        "odoo_poll_seconds": odoo_outbound.poll_seconds(db),
        "odoo_reconcile_minutes": odoo_outbound.reconcile_minutes(db),
    }


@router.post("/odoo/mo-event")
async def odoo_mo_event(
    request: Request,
    event: schemas.OdooMoEvent,
    db: Session = Depends(get_db),
    x_odoo_signature: Optional[str] = Header(default=None, alias="X-Odoo-Signature"),
    x_odoo_timestamp: Optional[str] = Header(default=None, alias="X-Odoo-Timestamp"),
):
    """Receive a Manufacturing Order push from Odoo (webhook).

    Called by the Odoo side when an MO is created/confirmed. Idempotent by
    ``mo_id``: creates/updates the customer PO, spec and the filtered BOM
    (direct filter-rod materials only) in MES.
    """
    raw_body = await request.body()
    _verify_odoo_webhook(
        str(event.idempotency_key or event.mo_id),
        x_odoo_signature,
        body=raw_body,
        timestamp=x_odoo_timestamp,
    )
    from starlette.concurrency import run_in_threadpool

    from app.services.odoo import inbound as odoo_inbound
    return await run_in_threadpool(odoo_inbound.handle_mo_event, db, event.model_dump())


@router.post("/odoo/mo-recall")
async def odoo_mo_recall(
    request: Request,
    payload: schemas.OdooMoRecall,
    db: Session = Depends(get_db),
    x_odoo_signature: Optional[str] = Header(default=None, alias="X-Odoo-Signature"),
    x_odoo_timestamp: Optional[str] = Header(default=None, alias="X-Odoo-Timestamp"),
):
    """Recall (cancel/delete) an MO that was pushed to MES but never started.

    Guardrails (see ``services/odoo/recall.py``): returns 409 when the MO is open
    on a machine or has production data; otherwise archives the unstarted order.
    """
    raw_body = await request.body()
    _verify_odoo_webhook(
        str(payload.mo_ref or payload.mo_id or ""),
        x_odoo_signature,
        body=raw_body,
        timestamp=x_odoo_timestamp,
    )
    from starlette.concurrency import run_in_threadpool

    from app.services.odoo import recall as odoo_recall

    try:
        return await run_in_threadpool(odoo_recall.recall_mo, db, payload.model_dump())
    except odoo_recall.MoRecallError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


WEBHOOK_MAX_AGE_SECONDS = 300


def _verify_odoo_webhook(
    message: str,
    signature: Optional[str],
    body: Optional[bytes] = None,
    timestamp: Optional[str] = None,
) -> None:
    """Validate the HMAC-SHA256 ``X-Odoo-Signature`` when a secret is configured.

    Two schemes are accepted:
      * signed body (preferred): ``HMAC(secret, "<timestamp>.<raw body>")`` with an
        ``X-Odoo-Timestamp`` header no older than ``WEBHOOK_MAX_AGE_SECONDS`` -
        protects against tampering and replay.
      * legacy: ``HMAC(secret, idempotency_key)`` when no timestamp is sent, kept
        so an un-upgraded addon keeps working. Disable it with
        ``ODOO_WEBHOOK_REQUIRE_TIMESTAMP=true``.

    When ``ODOO_WEBHOOK_SECRET`` is unset the check is skipped (development) - the
    connector stays inert and the endpoint is open only on the trusted network.
    """
    secret = os.getenv("ODOO_WEBHOOK_SECRET", "").strip()
    if not secret:
        return
    if not signature:
        raise HTTPException(status_code=401, detail="Missing X-Odoo-Signature")

    if timestamp:
        try:
            ts = int(timestamp)
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid X-Odoo-Timestamp")
        if abs(datetime.now(timezone.utc).timestamp() - ts) > WEBHOOK_MAX_AGE_SECONDS:
            raise HTTPException(status_code=401, detail="Stale X-Odoo-Timestamp")
        signed = timestamp.encode("utf-8") + b"." + (body or b"")
    else:
        if os.getenv("ODOO_WEBHOOK_REQUIRE_TIMESTAMP", "").strip().lower() in ("1", "true", "yes", "on"):
            raise HTTPException(status_code=401, detail="Missing X-Odoo-Timestamp")
        signed = message.encode("utf-8")

    expected = "sha256=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid X-Odoo-Signature")


def _spec_limits_payload(specs: Dict) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key, spec in specs.items():
        payload[key] = {
            "target": _num(spec.nominal),
            "usl": _num(spec.upper),
            "lsl": _num(spec.lower),
            "unit": spec.report_unit or "",
        }
    return payload


def _open_run_for_machine(db: Session, machine_id: int) -> Optional[models.ProductionRun]:
    """The run currently producing on ``machine_id`` (runs carry the machine, so this
    stays correct when a shift moves between machines)."""
    return (
        db.query(models.ProductionRun)
        .filter(models.ProductionRun.machine_id == machine_id, models.ProductionRun.ended_at.is_(None))
        .order_by(models.ProductionRun.started_at.desc())
        .first()
    )


def _active_po_id_for_machine(db: Session, machine_id: int) -> Optional[int]:
    open_run = _open_run_for_machine(db, machine_id)
    if open_run is not None:
        return open_run.po_id
    shift = (
        db.query(models.ShiftSession)
        .filter(
            models.ShiftSession.machine_id == machine_id,
            (models.ShiftSession.ended_at.is_(None)) | (models.ShiftSession.status == "OPEN"),
        )
        .order_by(models.ShiftSession.started_at.desc())
        .first()
    )
    if shift is None:
        return None
    run = (
        db.query(models.ProductionRun)
        .filter(
            models.ProductionRun.shift_id == shift.id,
            (models.ProductionRun.ended_at.is_(None)) | (models.ProductionRun.status == "OPEN"),
        )
        .order_by(models.ProductionRun.seq.desc())
        .first()
    )
    return run.po_id if run is not None else None


def _load_machine_specs(db: Session, machine_id: int) -> Dict:
    po_id = _active_po_id_for_machine(db, machine_id)
    if po_id is None:
        recent_run = (
            db.query(models.ProductionRun)
            .join(models.ShiftSession, models.ProductionRun.shift_id == models.ShiftSession.id)
            .filter(
                (models.ProductionRun.machine_id == machine_id)
                | (models.ProductionRun.machine_id.is_(None) & (models.ShiftSession.machine_id == machine_id)),
                models.ProductionRun.po_id.isnot(None),
            )
            .order_by(models.ProductionRun.started_at.desc())
            .first()
        )
        if recent_run is not None:
            po_id = recent_run.po_id

    rows = []
    if po_id is not None:
        rows = db.query(models.QualitySpec).filter(models.QualitySpec.po_id == po_id).all()
    if not rows:
        rows = db.query(models.QualitySpec).filter(models.QualitySpec.machine_id == machine_id).all()
    if not rows:
        rows = db.query(models.QualitySpec).filter(
            models.QualitySpec.machine_id.is_(None), models.QualitySpec.po_id.is_(None)
        ).all()
    return aggregation.build_param_specs(rows)


def _resolve_machine(db: Session, alias: str) -> Optional[models.Machine]:
    machine = db.query(models.Machine).filter(models.Machine.name == alias).first()
    if machine is not None:
        return machine
    row = db.query(models.MachineAlias).filter(models.MachineAlias.alias_value == alias.strip()).first()
    if row is not None:
        return db.get(models.Machine, row.machine_id)
    return None


def _windowed_rods(db: Session, machine_id: int, window_type: str, window_value: int, anchor_dt=None):
    base = db.query(models.QualityMeasurement).filter(models.QualityMeasurement.machine_id == machine_id)
    if anchor_dt is not None:
        base = base.filter(models.QualityMeasurement.measured_at >= anchor_dt)
    asc = (models.QualityMeasurement.measured_at, models.QualityMeasurement.sample_id, models.QualityMeasurement.rod_no)
    if window_type == "hours":
        since = _utcnow() - timedelta(hours=window_value)
        return base.filter(models.QualityMeasurement.measured_at >= since).order_by(*asc).all()
    if window_type == "shift":
        shift = (
            db.query(models.ShiftSession)
            .filter(models.ShiftSession.machine_id == machine_id)
            .order_by(models.ShiftSession.started_at.desc())
            .first()
        )
        if shift is None:
            return []
        return base.filter(models.QualityMeasurement.shift_id == shift.id).order_by(*asc).all()
    last = (
        base.order_by(
            models.QualityMeasurement.measured_at.desc(),
            models.QualityMeasurement.sample_id.desc(),
            models.QualityMeasurement.rod_no.desc(),
        )
        .limit(window_value)
        .all()
    )
    last.reverse()
    return last


def _sd_status(value: Optional[float], green: float, yellow: float) -> str:
    if value is None:
        return "NO_DATA"
    if value < green:
        return "GREEN"
    if value <= yellow:
        return "YELLOW"
    return "RED"


def _load_quality_settings(db: Session) -> models.QualitySettings:
    s = db.query(models.QualitySettings).first()
    if s is None:
        s = models.QualitySettings()
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _sd_thresholds(db: Session):
    s = _load_quality_settings(db)
    return (
        _num(s.pd_sd_warn) or 12.0,
        _num(s.pd_sd_fail) or 15.0,
        _num(s.dia_sd_warn) or 0.013,
        _num(s.dia_sd_fail) or 0.015,
    )


def _active_po_for_machine(db: Session, machine_id: int) -> Optional[str]:
    po_id = _active_po_id_for_machine(db, machine_id)
    if po_id is None:
        return None
    po = db.get(models.PurchaseOrder, po_id)
    return po.po_number if po is not None else None


@router.get("/machines/{machine_alias}/live-quality")
def machine_live_quality(
    machine_alias: str,
    window_type: str = Query(default="rods"),
    window_value: int = Query(default=50),
    anchor: Optional[str] = None,
    db: Session = Depends(get_db),
):
    machine = _resolve_machine(db, machine_alias)
    if machine is None:
        raise HTTPException(status_code=404, detail=f"Machine '{machine_alias}' not found")
    if window_type not in ("rods", "hours", "shift"):
        window_type = "rods"
    if window_value <= 0:
        window_value = 50

    anchor_dt = None
    if anchor == "shift_start":
        shift = (
            db.query(models.ShiftSession)
            .filter(models.ShiftSession.machine_id == machine.id)
            .order_by(models.ShiftSession.started_at.desc())
            .first()
        )
        if shift is not None:
            anchor_dt = shift.started_at
    elif anchor:
        try:
            anchor_dt = datetime.fromisoformat(anchor)
            if anchor_dt.tzinfo is None:
                anchor_dt = anchor_dt.replace(tzinfo=BUDAPEST)
        except ValueError:
            anchor_dt = None

    specs = _load_machine_specs(db, machine.id)
    rods = _windowed_rods(db, machine.id, window_type, window_value, anchor_dt)
    rod_dicts = [{k: getattr(r, k) for k in _MEASURE_PARAM_KEYS} for r in rods]
    stats = compute_run_stats(rod_dicts, specs)
    params = stats.get("parameters", {})
    pd = params.get("pd") or {}
    dia = params.get("diameter") or {}

    mean_pd = pd.get("mean")
    sd_pd = pd.get("sd_samp")
    mean_dia = dia.get("mean")
    sd_dia = dia.get("sd_samp")
    sd_pd_percent = (sd_pd / mean_pd * 100.0) if (sd_pd is not None and mean_pd) else None
    sd_dia_percent = (sd_dia / mean_dia * 100.0) if (sd_dia is not None and mean_dia) else None
    pd_warn, pd_fail, dia_warn, dia_fail = _sd_thresholds(db)

    return {
        "machine": machine.name,
        "machine_id": machine.id,
        "active_po": _active_po_for_machine(db, machine.id),
        "anchor": anchor,
        "window_type": window_type,
        "window_value": window_value,
        "sample_size": stats.get("rods_total", 0),
        "rods_rejected": stats.get("rods_rejected", 0),
        "mean_pd": mean_pd,
        "sd_pd_unit": sd_pd,
        "sd_pd_percent": sd_pd_percent,
        "status_pd": _sd_status(sd_pd, pd_warn, pd_fail),
        "mean_dia": mean_dia,
        "sd_dia_mm": sd_dia,
        "sd_dia_percent": sd_dia_percent,
        "status_dia": _sd_status(sd_dia, dia_warn, dia_fail),
        "series": _series_payload(specs, rods),
    }


_DASHBOARD_IDLE_MINUTES = 10


def _dashboard_machine_payload(
    db: Session,
    machine: models.Machine,
    pd_warn: float,
    pd_fail: float,
    dia_warn: float,
    dia_fail: float,
) -> Dict[str, Any]:
    open_shift = (
        db.query(models.ShiftSession)
        .filter(
            models.ShiftSession.machine_id == machine.id,
            (models.ShiftSession.ended_at.is_(None)) | (models.ShiftSession.status == "OPEN"),
        )
        .order_by(models.ShiftSession.started_at.desc())
        .first()
    )
    operator = None
    if open_shift is not None and open_shift.operator_id is not None:
        user = db.get(models.User, open_shift.operator_id)
        operator = user.username if user is not None else None

    last_measured_at = (
        db.query(func.max(models.QualityMeasurement.measured_at))
        .filter(models.QualityMeasurement.machine_id == machine.id)
        .scalar()
    )

    specs = _load_machine_specs(db, machine.id)
    rods = _windowed_rods(db, machine.id, "rods", 50)
    rod_dicts = [{k: getattr(r, k) for k in _MEASURE_PARAM_KEYS} for r in rods]
    stats = compute_run_stats(rod_dicts, specs)
    params = stats.get("parameters", {})
    pd = params.get("pd") or {}
    dia = params.get("diameter") or {}

    state = "offline"
    if open_shift is not None:
        idle_since = datetime.now(timezone.utc) - timedelta(minutes=_DASHBOARD_IDLE_MINUTES)
        state = "running" if (last_measured_at is not None and last_measured_at >= idle_since) else "idle"

    return {
        "alias": machine.name,
        "machine_id": machine.id,
        "state": state,
        "operator": operator,
        "active_po": _active_po_for_machine(db, machine.id),
        "mean_pd": pd.get("mean"),
        "mean_dia": dia.get("mean"),
        "status_pd": _sd_status(pd.get("sd_samp"), pd_warn, pd_fail),
        "status_dia": _sd_status(dia.get("sd_samp"), dia_warn, dia_fail),
        "shift_started_at": open_shift.started_at.isoformat() if (open_shift is not None and open_shift.started_at is not None) else None,
        "last_measured_at": last_measured_at.isoformat() if last_measured_at else None,
    }


@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    machines = (
        db.query(models.Machine)
        .filter(models.Machine.is_inactive.is_(False))
        .order_by(models.Machine.name)
        .all()
    )
    pd_warn, pd_fail, dia_warn, dia_fail = _sd_thresholds(db)

    # Active POs with machine assignment (from open production runs).
    active_runs = (
        db.query(models.ProductionRun)
        .filter(
            (models.ProductionRun.ended_at.is_(None)) | (models.ProductionRun.status == "OPEN"),
            models.ProductionRun.po_id.isnot(None),
        )
        .all()
    )
    po_machine: Dict[int, str] = {}
    for run in active_runs:
        if run.po_id in po_machine:
            continue
        machine_ref = run.machine_id
        if machine_ref is None:
            shift = db.get(models.ShiftSession, run.shift_id)
            machine_ref = shift.machine_id if shift is not None else None
        m = db.get(models.Machine, machine_ref) if machine_ref is not None else None
        if m is not None:
            po_machine[run.po_id] = m.name

    pos = (
        db.query(models.PurchaseOrder)
        .filter(
            models.PurchaseOrder.is_archived.is_(False),
            models.PurchaseOrder.is_hidden.is_(False),
        )
        .order_by(models.PurchaseOrder.created_at.desc())
        .all()
    )
    orders = [
        {
            "po_number": p.po_number,
            "target_qty": p.target_qty or 0,
            "produced_qty": p.produced_qty or 0,
            "machine": po_machine.get(p.id),
        }
        for p in pos
    ]

    # KPIs over the last 24h.
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    reports = (
        db.query(models.ProductionReport)
        .filter(
            models.ProductionReport.is_deleted.is_(False),
            models.ProductionReport.is_archived.is_(False),
        )
        .filter(
            (models.ProductionReport.sync_at >= since)
            | (models.ProductionReport.submitted_at_utc >= since)
        )
        .all()
    )
    output_today = sum(int(r.produced_rods or 0) for r in reports)
    waste_kg = sum(float(r.waste_kg or 0) for r in reports)
    input_kg = sum(
        float(r.total_acetate or 0)
        + float(r.total_paper or 0)
        + float(r.total_pva or 0)
        + float(r.total_hm or 0)
        + float(r.total_triacetin or 0)
        for r in reports
    )
    scrap_rate = (waste_kg / input_kg * 100.0) if input_kg else None

    active_operators = (
        db.query(func.count(func.distinct(models.ShiftSession.operator_id)))
        .filter(
            models.ShiftSession.operator_id.isnot(None),
            (models.ShiftSession.ended_at.is_(None)) | (models.ShiftSession.status == "OPEN"),
        )
        .scalar()
    )

    compliance_rates: List[float] = []
    for machine in machines:
        specs = _load_machine_specs(db, machine.id)
        rods = _windowed_rods(db, machine.id, "hours", 24)
        if not rods:
            continue
        rod_dicts = [{k: getattr(r, k) for k in _MEASURE_PARAM_KEYS} for r in rods]
        stats = compute_run_stats(rod_dicts, specs)
        rates = [
            float(p["pass_rate"])
            for name, p in stats.get("parameters", {}).items()
            if name in ("pd", "diameter") and p.get("pass_rate") is not None
        ]
        if rates:
            compliance_rates.append(sum(rates) / len(rates))
    compliance = (sum(compliance_rates) / len(compliance_rates) * 100.0) if compliance_rates else None

    # Station ingestion heartbeat.
    last_seen = (
        db.query(func.max(func.coalesce(models.IngestionFile.processed_at, models.IngestionFile.first_seen_at)))
        .scalar()
    )
    processed_count = (
        db.query(func.count(models.IngestionFile.id))
        .filter(models.IngestionFile.status == "processed")
        .scalar()
    )
    error_count = (
        db.query(func.count(models.IngestionFile.id))
        .filter(models.IngestionFile.status == "error")
        .scalar()
    )

    return {
        "generated_at": now.isoformat(),
        "machines": [
            _dashboard_machine_payload(db, m, pd_warn, pd_fail, dia_warn, dia_fail)
            for m in machines
        ],
        "orders": orders,
        "kpis": {
            "output_today": output_today,
            "scrap_rate_pct": round(scrap_rate, 2) if scrap_rate is not None else None,
            "compliance_pct": round(compliance, 2) if compliance is not None else None,
            "active_operators": int(active_operators or 0),
        },
        "ingestion": {
            "last_seen": last_seen.isoformat() if last_seen else None,
            "processed_count": int(processed_count or 0),
            "error_count": int(error_count or 0),
            "total_files": int((processed_count or 0) + (error_count or 0)),
        },
    }


def _time_str(value) -> str:
    return (value or "").strip()[:5]


def _resolve_quality_shift(
    db: Session,
    shift_id: Optional[int] = None,
    report_id: Optional[int] = None,
    machine_name: Optional[str] = None,
    date: Optional[str] = None,
    shift_name: Optional[str] = None,
) -> Optional[models.ShiftSession]:
    if shift_id is not None:
        return db.get(models.ShiftSession, shift_id)
    if report_id is not None:
        report = db.get(models.ProductionReport, report_id)
        if report is not None:
            key = f"{report.machine_name}|{report.report_date}|{report.shift_name}"
            shift = db.query(models.ShiftSession).filter(models.ShiftSession.legacy_report_key == key).first()
            if shift is not None:
                return shift
            machine_name = machine_name or report.machine_name
            date = date or report.report_date
            shift_name = shift_name or report.shift_name
    if not machine_name or not date:
        return None
    machine = db.query(models.Machine).filter(models.Machine.name == machine_name).first()
    if machine is None:
        return None
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    candidates = (
        db.query(models.ShiftSession)
        .filter(models.ShiftSession.machine_id == machine.id)
        .order_by(models.ShiftSession.started_at.desc())
        .limit(200)
        .all()
    )
    day_candidates = [s for s in candidates if s.started_at is not None and s.started_at.date() == day]
    if not day_candidates:
        return None
    if shift_name:
        template = db.query(models.Shift).filter(models.Shift.name == shift_name).first()
        if template is not None:
            want = _time_str(template.start_time)
            for s in day_candidates:
                if s.started_at and s.started_at.strftime("%H:%M") == want:
                    return s
    return day_candidates[0]


def _specs_for_context(db: Session, machine_id: Optional[int], po_id: Optional[int], shift_id: Optional[int]) -> tuple:
    """Resolve spec limits for the current selection.

    Returns ``(specs, specs_missing)``. When a PO is explicitly selected, its own
    specs are the ONLY source of truth: if it has none, ``specs_missing`` is True and
    no other order's limits are borrowed (borrowing was showing the wrong target on
    the chart). When no PO is selected, the shift/machine fallbacks still apply.
    """
    if po_id is not None:
        rows = db.query(models.QualitySpec).filter(models.QualitySpec.po_id == po_id).all()
        return aggregation.build_param_specs(rows), not bool(rows)
    if shift_id is not None:
        specs = _load_shift_specs(db, shift_id)
        if specs:
            return specs, False
    if machine_id is not None:
        specs = _load_machine_specs(db, machine_id)
        if specs:
            return specs, False
    return {}, True


class QualitySettingsPayload(BaseModel):
    diameter_tolerance: Optional[float] = None
    pd_tolerance: Optional[float] = None
    pd_sd_warn: Optional[float] = None
    pd_sd_fail: Optional[float] = None
    dia_sd_warn: Optional[float] = None
    dia_sd_fail: Optional[float] = None


def _settings_payload(s: models.QualitySettings) -> Dict[str, Any]:
    return {
        "diameter_tolerance": _num(s.diameter_tolerance) or 0.03,
        "pd_tolerance": _num(s.pd_tolerance) or 20.0,
        "pd_sd_warn": _num(s.pd_sd_warn) or 12.0,
        "pd_sd_fail": _num(s.pd_sd_fail) or 15.0,
        "dia_sd_warn": _num(s.dia_sd_warn) or 0.013,
        "dia_sd_fail": _num(s.dia_sd_fail) or 0.015,
    }


@router.get("/quality/settings")
def get_quality_settings(db: Session = Depends(get_db)):
    return _settings_payload(_load_quality_settings(db))


@router.put("/quality/settings")
def update_quality_settings(
    payload: QualitySettingsPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    s = _load_quality_settings(db)
    for field in ("diameter_tolerance", "pd_tolerance", "pd_sd_warn", "pd_sd_fail", "dia_sd_warn", "dia_sd_fail"):
        v = getattr(payload, field)
        if v is not None:
            setattr(s, field, v)
    db.commit()
    db.refresh(s)
    return _settings_payload(s)


@router.get("/quality/filters")
def quality_filters(db: Session = Depends(get_db)):
    machines = (
        db.query(models.Machine)
        .filter(models.Machine.is_inactive.is_(False))
        .order_by(models.Machine.name)
        .all()
    )
    pos = (
        db.query(models.PurchaseOrder)
        .filter(models.PurchaseOrder.is_archived.is_(False))
        .order_by(models.PurchaseOrder.created_at.desc())
        .limit(200)
        .all()
    )
    shift_rows = (
        db.query(models.ShiftSession, models.Machine.name)
        .join(models.Machine, models.Machine.id == models.ShiftSession.machine_id)
        .order_by(models.ShiftSession.started_at.desc())
        .limit(300)
        .all()
    )
    shift_ids = [s.id for s, _ in shift_rows]
    po_by_shift: Dict[int, List[int]] = {}
    if shift_ids:
        for sid, po_id in (
            db.query(models.ProductionRun.shift_id, models.ProductionRun.po_id)
            .filter(models.ProductionRun.shift_id.in_(shift_ids), models.ProductionRun.po_id.isnot(None))
            .all()
        ):
            if po_id not in po_by_shift.setdefault(sid, []):
                po_by_shift[sid].append(po_id)

    shifts = []
    for s, mname in shift_rows:
        label = f"{mname} · {_bud(s.started_at).strftime('%Y-%m-%d %H:%M') if s.started_at else '?'}"
        label += ("–" + _bud(s.ended_at).strftime("%H:%M")) if s.ended_at else "–open"
        shifts.append({
            "id": s.id,
            "machine_id": s.machine_id,
            "started_at": _bud_iso(s.started_at) if s.started_at else None,
            "ended_at": _bud_iso(s.ended_at) if s.ended_at else None,
            "label": label,
            "po_ids": sorted(po_by_shift.get(s.id, [])),
        })
    return {
        "machines": [{"id": m.id, "name": m.name} for m in machines],
        "pos": [{"id": p.id, "po_number": p.po_number} for p in pos],
        "shifts": shifts,
    }


def _shift_label(s: models.ShiftSession) -> str:
    label = _bud(s.started_at).strftime("%Y-%m-%d %H:%M") if s.started_at else "?"
    label += ("–" + _bud(s.ended_at).strftime("%H:%M")) if s.ended_at else "–open"
    return label


def _trim_num(value) -> str:
    """Format a numeric spec value without trailing zeros (7.72, 108, 380, 0)."""
    f = _num(value)
    if f is None:
        return ""
    if f == int(f):
        return str(int(f))
    return f"{f:.3f}".rstrip("0").rstrip(".")


def _po_spec_string(po) -> Optional[str]:
    """Build the MO-style specification string, e.g. ``7.72*108PD 380 CU 0``."""
    if po is None:
        return None
    dia = _num(po.diameter)
    length = _num(po.length)
    pd = _num(po.pd)
    parts = []
    if dia is not None and length is not None:
        parts.append(f"{_trim_num(dia)}*{_trim_num(length)}")
    if pd is not None:
        parts.append(f"PD {_trim_num(pd)}")
    if getattr(po, "cu", None) is not None:
        parts.append(f"CU {po.cu}")
    return " ".join(parts) if parts else None


def _quality_header(db: Session, machine, shift, po_id) -> Dict[str, Any]:
    header: Dict[str, Any] = {
        "machine": machine or "All",
        "po_number": None,
        "spec": None,
        "operator": None,
        "shift_label": None,
        "date": None,
    }
    if shift is not None:
        header["shift_label"] = _shift_label(shift)
        if shift.started_at is not None:
            header["date"] = _bud(shift.started_at).date().isoformat()
        if shift.operator_id is not None:
            u = db.get(models.User, shift.operator_id)
            if u is not None:
                header["operator"] = u.username
    po = None
    if po_id is not None:
        po = db.get(models.PurchaseOrder, po_id)
    elif shift is not None:
        run = (
            db.query(models.ProductionRun)
            .filter(models.ProductionRun.shift_id == shift.id, models.ProductionRun.po_id.isnot(None))
            .order_by(models.ProductionRun.seq.desc())
            .first()
        )
        if run is not None:
            po = db.get(models.PurchaseOrder, run.po_id)
    if po is not None:
        header["po_number"] = po.po_number
        header["spec"] = _po_spec_string(po)
    return header


def _quality_report_payload(
    db: Session, header: Dict[str, Any], po_id: Optional[int], shift,
    run_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Certificate-style payload for the printable quality report.

    MO scope (``po_id``) is the average across every shift of the order;
    shift scope is a single shift's station + manual data.
    """
    base = {
        "po_number": header.get("po_number"),
        "spec_string": header.get("spec"),
        "machine": header.get("machine"),
        "date": header.get("date"),
        "shift_label": header.get("shift_label"),
        "operator": header.get("operator"),
    }
    if po_id is not None:
        s = aggregation.compute_order_summary(db, po_id)
        return {
            **base,
            "scope": "mo",
            "certificate": s.get("certificate", []),
            "automatic": s.get("automatic", []),
            "manual_measurements": s.get("manual_measurements"),
            "manual_checks": s.get("manual_checks", []),
            "remarks": s.get("remarks"),
        }
    if shift is not None:
        s = _shift_quality_summary(db, shift.id, run_id=run_id)
        return {
            **base,
            "scope": "shift",
            "certificate": s.get("certificate", []),
            "automatic": s.get("automatic", []),
            "manual_measurements": s.get("manual_measurements"),
            "manual_checks": s.get("manual_checks", []),
            "remarks": s.get("remarks"),
        }
    return None


def _po_window_filters(window, po_id, shift_id, report_id, date, shift_name):
    """'Entire PO' spans every shift: stale shift filters must not narrow (or empty) it."""
    if window == "po" and po_id is not None:
        return None, None, None, None
    return shift_id, report_id, date, shift_name


@router.get("/quality")
def quality_overview(
    machine: Optional[str] = None,
    po_id: Optional[int] = None,
    shift_id: Optional[int] = None,
    report_id: Optional[int] = None,
    date: Optional[str] = None,
    shift_name: Optional[str] = None,
    window: str = Query(default="rods"),
    window_value: int = Query(default=50),
    page: int = Query(default=1),
    page_size: int = Query(default=50),
    fmt: str = Query(default="json"),
    include_raw: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    if window not in ("rods", "shift", "po", "all"):
        window = "rods"
    if window_value <= 0:
        window_value = 50
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 200:
        page_size = 50
    shift_id, report_id, date, shift_name = _po_window_filters(
        window, po_id, shift_id, report_id, date, shift_name
    )

    machine_id = None
    if machine and machine != "all":
        m = _resolve_machine(db, machine)
        if m is None:
            raise HTTPException(status_code=404, detail=f"Machine '{machine}' not found")
        machine_id = m.id

    shift = _resolve_quality_shift(db, shift_id=shift_id, report_id=report_id, machine_name=machine, date=date, shift_name=shift_name)
    if shift is not None:
        shift_id = shift.id
        if machine_id is None:
            # A shift that moved between machines has rods on several of them: only
            # default the machine filter when the shift was on exactly one.
            run_machines = {
                r[0] for r in db.query(models.ProductionRun.machine_id)
                .filter(models.ProductionRun.shift_id == shift.id, models.ProductionRun.machine_id.isnot(None))
                .distinct().all()
            }
            if len(run_machines) <= 1:
                machine_id = next(iter(run_machines), shift.machine_id)

    base = db.query(models.QualityMeasurement)
    if machine_id is not None:
        base = base.filter(models.QualityMeasurement.machine_id == machine_id)
    if shift is not None:
        in_range = (models.QualityMeasurement.machine_id == (machine_id or shift.machine_id)) & (models.QualityMeasurement.measured_at >= shift.started_at)
        if shift.ended_at is not None:
            in_range = in_range & (models.QualityMeasurement.measured_at <= shift.ended_at)
        base = base.filter((models.QualityMeasurement.shift_id == shift.id) | in_range)
    elif shift_id is not None:
        base = base.filter(models.QualityMeasurement.shift_id == shift_id)
    if po_id is not None:
        run_ids = [r[0] for r in db.query(models.ProductionRun.id).filter(models.ProductionRun.po_id == po_id).all()]
        base = base.filter(models.QualityMeasurement.run_id.in_(run_ids))

    asc = (models.QualityMeasurement.measured_at, models.QualityMeasurement.sample_id, models.QualityMeasurement.rod_no)
    if window == "rods":
        last = (
            base.order_by(
                models.QualityMeasurement.measured_at.desc(),
                models.QualityMeasurement.sample_id.desc(),
                models.QualityMeasurement.rod_no.desc(),
            )
            .limit(window_value)
            .all()
        )
        rods = list(reversed(last))
    elif window == "shift":
        if shift is None:
            q = db.query(models.ShiftSession)
            if machine_id is not None:
                q = q.filter(models.ShiftSession.machine_id == machine_id)
            latest = q.order_by(models.ShiftSession.started_at.desc()).first()
            if latest is None:
                rods = []
            else:
                in_range = (models.QualityMeasurement.machine_id == latest.machine_id) & (models.QualityMeasurement.measured_at >= latest.started_at)
                if latest.ended_at is not None:
                    in_range = in_range & (models.QualityMeasurement.measured_at <= latest.ended_at)
                base2 = base.filter((models.QualityMeasurement.shift_id == latest.id) | in_range)
                rods = base2.order_by(*asc).all()
        else:
            rods = base.order_by(*asc).all()
    else:
        rods = base.order_by(*asc).all()

    specs, specs_missing = _specs_for_context(db, machine_id, po_id, shift_id)
    rod_dicts = [{k: getattr(r, k) for k in _MEASURE_PARAM_KEYS} for r in rods]
    stats = compute_run_stats(rod_dicts, specs)
    params = stats.get("parameters", {})
    pd = params.get("pd") or {}
    dia = params.get("diameter") or {}
    mean_pd = pd.get("mean")
    sd_pd = pd.get("sd_samp")
    mean_dia = dia.get("mean")
    sd_dia = dia.get("sd_samp")
    sd_pd_percent = (sd_pd / mean_pd * 100.0) if (sd_pd is not None and mean_pd) else None
    sd_dia_percent = (sd_dia / mean_dia * 100.0) if (sd_dia is not None and mean_dia) else None

    machine_names = {m.id: m.name for m in db.query(models.Machine).all()}
    by_machine: Dict[int, List[models.QualityMeasurement]] = {}
    for r in rods:
        by_machine.setdefault(r.machine_id, []).append(r)

    series = {machine_names.get(mid, f"machine_{mid}"): _series_payload(specs, rows) for mid, rows in by_machine.items()}

    all_run_ids = {r.run_id for r in rods if r.run_id is not None}
    po_by_run = {}
    if all_run_ids:
        po_by_run = dict(
            db.query(models.ProductionRun.id, models.PurchaseOrder.po_number)
            .join(models.PurchaseOrder, models.PurchaseOrder.id == models.ProductionRun.po_id)
            .filter(models.ProductionRun.id.in_(all_run_ids))
            .all()
        )

    def row_of(r):
        return {
            "measured_at": _bud_iso(r.measured_at) if r.measured_at else None,
            "rod_no": r.rod_no,
            "machine_name": machine_names.get(r.machine_id),
            "po_number": po_by_run.get(r.run_id),
            "diameter": _num(r.diameter),
            "pd": _num(r.pd),
            "weight": _num(r.weight),
            "rejected": _is_rejected({k: getattr(r, k) for k in _MEASURE_PARAM_KEYS}, specs) if specs else False,
        }

    if fmt == "csv":
        buf = io.StringIO()
        writer = _csv.DictWriter(buf, fieldnames=["measured_at", "rod_no", "machine_name", "po_number", "diameter", "pd", "weight", "rejected"])
        writer.writeheader()
        for r in rods:
            writer.writerow(row_of(r))
        return Response(content=buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=quality.csv"})

    total = len(rods)
    start = (page - 1) * page_size
    rows_out = [row_of(r) for r in rods[start:start + page_size]]

    pd_warn, pd_fail, dia_warn, dia_fail = _sd_thresholds(db)
    header = _quality_header(db, machine, shift, po_id)
    run_id = None
    if report_id is not None:
        db_report = db.get(models.ProductionReport, report_id)
        if db_report is not None:
            run_id = db_report.run_id
    report = _quality_report_payload(db, header, po_id, shift, run_id=run_id)
    raw_rows = [row_of(r) for r in rods] if include_raw else None

    return {
        "selection": {"machine": machine or "all", "po_id": po_id, "shift_id": shift_id, "window": window, "window_value": window_value},
        "kpis": {
            "sample_size": stats.get("rods_total", 0),
            "rods_rejected": stats.get("rods_rejected", 0),
            "mean_pd": mean_pd,
            "sd_pd": sd_pd,
            "sd_pd_percent": sd_pd_percent,
            "status_pd": _sd_status(sd_pd, pd_warn, pd_fail),
            "mean_dia": mean_dia,
            "sd_dia": sd_dia,
            "sd_dia_percent": sd_dia_percent,
            "status_dia": _sd_status(sd_dia, dia_warn, dia_fail),
        },
        "header": header,
        "thresholds": {"pd_warn": pd_warn, "pd_fail": pd_fail, "dia_warn": dia_warn, "dia_fail": dia_fail},
        "specs": _spec_limits_payload(specs),
        "specs_missing": specs_missing,
        "series": series,
        "active_machines": sorted(series.keys()),
        "measurements": {"total": total, "page": page, "page_size": page_size, "rows": rows_out},
        "raw_rows": raw_rows,
        "report": report,
    }


# ---------------------------------------------------------------------------
# Station profiles (Settings -> Quality Stations)
# ---------------------------------------------------------------------------

_COLUMN_FIELDS = ("rod_no", "pd", "weight", "diameter", "ovality", "roundness", "shape", "hardness", "length")


def _to_index(val) -> Optional[int]:
    if val is None or val == "" or val == "null":
        return None
    return int(val)


def _station_profile_dict(db: Session, p: models.StationProfile) -> Dict[str, Any]:
    key = db.get(models.StationKey, p.station_key_id) if p.station_key_id else None
    column_map = p.column_map or {}
    return {
        "id": p.id,
        "label": p.label or "",
        "source": p.source,
        "match_key": p.match_key,
        "match_value": p.match_value,
        "mo_field": p.mo_field or "batch_description",
        "data_start_row": p.data_start_row,
        "encoding": p.encoding or "utf-8",
        "delivery_mode": p.delivery_mode or "push",
        "watch_path": p.watch_path or "",
        "station_key_id": p.station_key_id,
        "key": {
            "id": key.id,
            "is_active": key.is_active,
            "prefix": (key.key_hash or "")[:8],
            "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        } if key else None,
        "column_map": {f: column_map.get(f) for f in _COLUMN_FIELDS},
        "custom_fields": p.custom_fields or [],
        "valid_from": p.valid_from.isoformat() if p.valid_from else None,
        "valid_to": p.valid_to.isoformat() if p.valid_to else None,
    }


def _apply_station_profile_fields(p: models.StationProfile, payload: Dict[str, Any]) -> None:
    p.label = payload.get("label") or None
    p.match_key = payload.get("match_key") or "instrument_id"
    p.match_value = (payload.get("match_value") or "").strip()
    p.mo_field = payload.get("mo_field") or "batch_description"
    p.data_start_row = _to_index(payload.get("data_start_row"))
    p.encoding = payload.get("encoding") or "utf-8"
    p.delivery_mode = payload.get("delivery_mode") or "push"
    p.watch_path = payload.get("watch_path") or None
    p.metadata_map = None
    cm = payload.get("column_map")
    if isinstance(cm, dict):
        p.column_map = {f: _to_index(cm.get(f)) for f in _COLUMN_FIELDS}
    if "custom_fields" in payload:
        cf = payload.get("custom_fields")
        if isinstance(cf, list):
            cleaned = []
            for item in cf:
                if not isinstance(item, dict):
                    continue
                label = (item.get("label") or "").strip()
                idx = item.get("index")
                if idx is None or idx == "" or idx == "null":
                    idx = None
                else:
                    try:
                        idx = int(idx)
                    except (TypeError, ValueError):
                        idx = None
                if label or idx is not None:
                    cleaned.append({"label": label, "unit": (item.get("unit") or "").strip(), "index": idx})
            p.custom_fields = cleaned or None
        else:
            p.custom_fields = None


def _new_station_key(db: Session, label: str):
    """Create a StationKey row; returns (key, plaintext)."""
    raw = secrets.token_urlsafe(32)
    user = db.query(models.User).filter(models.User.username == "station_ingest").first()
    key = models.StationKey(
        key_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        label=label or "station key",
        user_id=user.id if user else None,
    )
    db.add(key)
    db.flush()
    return key, raw


@router.get("/station-profiles")
def list_station_profiles(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    rows = db.query(models.StationProfile).order_by(models.StationProfile.id).all()
    return [_station_profile_dict(db, p) for p in rows]


@router.post("/station-profiles")
def create_station_profile(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    p = models.StationProfile(source="quantum_neo", delivery_mode="push")
    _apply_station_profile_fields(p, payload)
    plaintext = None
    if bool(payload.get("generate_key")):
        key, plaintext = _new_station_key(db, payload.get("label") or "")
        p.station_key_id = key.id
    db.add(p)
    db.commit()
    out = _station_profile_dict(db, p)
    if plaintext:
        out["plaintext_key"] = plaintext
    return out


@router.put("/station-profiles/{profile_id}")
def update_station_profile(
    profile_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    p = _get_or_404(db, models.StationProfile, profile_id)
    _apply_station_profile_fields(p, payload)
    db.commit()
    return _station_profile_dict(db, p)


@router.delete("/station-profiles/{profile_id}")
def delete_station_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    p = _get_or_404(db, models.StationProfile, profile_id)
    if p.station_key_id:
        key = db.get(models.StationKey, p.station_key_id)
        if key:
            key.is_active = False
    db.delete(p)
    db.commit()
    return {"status": "deleted", "id": profile_id}


@router.post("/station-profiles/{profile_id}/generate-key")
def generate_station_profile_key(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    p = _get_or_404(db, models.StationProfile, profile_id)
    if p.station_key_id:
        old = db.get(models.StationKey, p.station_key_id)
        if old:
            old.is_active = False
    key, plaintext = _new_station_key(db, p.label or f"profile {p.id}")
    p.station_key_id = key.id
    db.commit()
    return {"station_key_id": key.id, "key_prefix": key.key_hash[:8], "plaintext_key": plaintext}


@router.post("/station-profiles/{profile_id}/revoke-key")
def revoke_station_profile_key(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_superadmin(current_user)
    p = _get_or_404(db, models.StationProfile, profile_id)
    if p.station_key_id:
        key = db.get(models.StationKey, p.station_key_id)
        if key:
            key.is_active = False
    p.station_key_id = None
    db.commit()
    return {"status": "revoked", "id": profile_id}


# ---------------------------------------------------------------------------
# Agent bundle download
# ---------------------------------------------------------------------------

_AGENT_EXE_PATH = os.path.join(os.path.dirname(__file__), "static", "agent", "station_push_agent.exe")


def _agent_ini(base_url: str, station_key: str) -> str:
    return (
        "[agent]\n"
        "watch_dir = .\\output\n"
        f"mes_base_url = {base_url}\n"
        f"station_key = {station_key}\n"
        "scan_interval = 30\n"
    )


def _agent_install_bat(station_id: int) -> str:
    task_name = f"MES_Station_Agent_{station_id}"
    return (
        "@echo off\r\n"
        "net session >nul 2>&1\r\n"
        "if %errorlevel% neq 0 (\r\n"
        "    echo Requesting administrator privileges...\r\n"
        "    powershell -Command \"Start-Process -FilePath '%~f0' -Verb RunAs\"\r\n"
        "    exit /b\r\n"
        ")\r\n"
        "set \"AGENT_DIR=%~dp0\"\r\n"
        "set \"EXE=%AGENT_DIR%station_push_agent.exe\"\r\n"
        f"set \"TASK_NAME={task_name}\"\r\n"
        "if not exist \"%AGENT_DIR%output\" mkdir \"%AGENT_DIR%output\"\r\n"
        "powershell -NoProfile -ExecutionPolicy Bypass -Command "
        "\"$a=New-ScheduledTaskAction -Execute '%EXE%' -WorkingDirectory '%AGENT_DIR%'; "
        "$t=New-ScheduledTaskTrigger -AtStartup; "
        "$s=New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 5 "
        "-RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero); "
        "Register-ScheduledTask -TaskName '%TASK_NAME%' -Action $a -Trigger $t -Settings $s "
        "-User SYSTEM -RunLevel Highest -Force | Out-Null; "
        "Start-ScheduledTask -TaskName '%TASK_NAME%'\"\r\n"
        "echo.\r\n"
        "echo Installed and started. Logs: %AGENT_DIR%station_push_agent.log\r\n"
        "pause\r\n"
    )


def _agent_readme_txt(label: str, base_url: str, station_id: int) -> str:
    task_name = f"MES_Station_Agent_{station_id}"
    return (
        "============================================================\r\n"
        "MES Station Push Agent — Automated Setup Guide\r\n"
        f"Station: {label}\r\n"
        "============================================================\r\n"
        "\r\n"
        "QUICK INSTALLATION (2 STEPS):\r\n"
        "1. Extract the contents of this ZIP archive to a permanent folder \r\n"
        "   (Recommended: C:\\MES_Station_Agent\\).\r\n"
        "2. Right-click \"install.bat\" and select \"Run as administrator\".\r\n"
        "   - The script will register the agent into Windows Task Scheduler.\r\n"
        "   - The agent will start silently in the background on system boot.\r\n"
        "   - No console windows will pop up for operators.\r\n"
        "\r\n"
        "CONFIGURATION & PATHS:\r\n"
        "- Output CSV Directory: The agent watches the local folder set in \r\n"
        "  \"station_agent.ini\" under [agent] -> watch_dir. The default is .\\output, \r\n"
        "  which resolves to the \"output\" subfolder next to this agent (e.g. \r\n"
        "  C:\\MES_Station_Agent\\output). Make sure the Quantum Neo measurement \r\n"
        "  station saves its CSV output files to this exact folder.\r\n"
        "- Logs: Stored next to this agent under \"station_push_agent.log\".\r\n"
        "\r\n"
        "TROUBLESHOOTING & UNINSTALLATION:\r\n"
        f"- If files are not uploading, verify network connectivity to the MES server: {base_url}\r\n"
        "- To stop or remove the service, run:\r\n"
        f"  schtasks /delete /tn \"{task_name}\" /f\r\n"
        "============================================================\r\n"
    )


@router.get("/station-profiles/{profile_id}/download-agent")
def download_station_agent(
    profile_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Stream a ready-to-run agent bundle (exe + ini + install.bat + README)."""
    _require_superadmin(current_user)
    p = _get_or_404(db, models.StationProfile, profile_id)

    if not os.path.isfile(_AGENT_EXE_PATH):
        raise HTTPException(
            status_code=503,
            detail="Agent binary not built. Run scripts/build_station_agent.ps1 "
                   "(pip install pyinstaller) to produce station_push_agent.exe.",
        )

    # Fresh key: plaintext is never stored, so each bundle carries a new one.
    if p.station_key_id:
        old = db.get(models.StationKey, p.station_key_id)
        if old:
            old.is_active = False
    key, plaintext = _new_station_key(db, p.label or f"profile {p.id}")
    p.station_key_id = key.id
    db.commit()

    base_url = (os.getenv("MES_PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")
    label = p.label or p.match_value or f"station-{p.id}"
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in label).strip("_") or f"station-{p.id}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(_AGENT_EXE_PATH, arcname="station_push_agent.exe")
        zf.writestr("station_agent.ini", _agent_ini(base_url, plaintext))
        zf.writestr("install.bat", _agent_install_bat(p.id))
        zf.writestr("README.txt", _agent_readme_txt(label, base_url, p.id))
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="station_agent_{safe_name}.zip"'},
    )


# ---------------------------------------------------------------------------
# Manual in-process quality checks (operator QC tab)
# ---------------------------------------------------------------------------

class ManualCheckPayload(BaseModel):
    shift_id: Optional[int] = None          # accepted for old tablets; the server resolves it
    mo_id: Optional[int] = None             # ignored: the server binds the shift's open run
    sample_weight: Optional[float] = None   # grams per ``sample_rods`` rods
    sample_rods: int = 10
    length_mm: Optional[float] = None
    hardness: Optional[float] = None        # percent (manual hardness measurement)
    glue_seam_ok: Optional[bool] = None     # True = OK, False = FAIL, None = not checked
    cut_quality_ok: Optional[bool] = None
    visual_appearance_ok: Optional[bool] = None
    notes: Optional[str] = None
    measured_at: Optional[datetime] = None
    client_check_id: Optional[str] = None   # offline-queue idempotency key


class VoidCheckPayload(BaseModel):
    reason: str


def _manual_check_dict(c: models.ManualQualityCheck) -> Dict[str, Any]:
    return {
        "id": c.id,
        "shift_id": c.shift_id,
        "mo_id": c.mo_id,
        "run_id": c.mo_id,
        "machine_id": c.machine_id,
        "po_id": c.po_id,
        "mo_ref": c.mo_ref,
        "operator_id": c.operator_id,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "measured_at": c.measured_at.isoformat() if c.measured_at else None,
        "sample_weight": _num(c.sample_weight),
        "sample_rods": c.sample_rods,
        "length_mm": _num(c.length_mm),
        "hardness": _num(c.hardness),
        "glue_seam_ok": c.glue_seam_ok,
        "cut_quality_ok": c.cut_quality_ok,
        "visual_appearance_ok": c.visual_appearance_ok,
        "notes": c.notes,
        "verdicts": c.verdicts or {},
        "overall_status": c.overall_status,
        "voided": c.voided_at is not None,
        "voided_at": c.voided_at.isoformat() if c.voided_at else None,
        "void_reason": c.void_reason,
    }


def _manual_checks_summary(db: Session, run_id: int) -> Dict[str, Any]:
    """Per-run roll-up of non-voided manual checks for the shift summary / certificate."""
    checks = (
        db.query(models.ManualQualityCheck)
        .filter(models.ManualQualityCheck.mo_id == run_id, models.ManualQualityCheck.voided_at.is_(None))
        .order_by(models.ManualQualityCheck.id)
        .all()
    )
    failed = [c for c in checks if c.overall_status == "FAIL"]
    weights = [_num(c.sample_weight) / (c.sample_rods or 10) for c in checks if c.sample_weight is not None]
    lengths = [_num(c.length_mm) for c in checks if c.length_mm is not None]
    hardnesses = [_num(c.hardness) for c in checks if c.hardness is not None]
    return {
        "count": len(checks),
        "failed": len(failed),
        "status": "FAIL" if failed else ("PASS" if any(c.overall_status for c in checks) else None),
        "mean_weight_per_rod_g": round(sum(weights) / len(weights), 5) if weights else None,
        "mean_length_mm": round(sum(lengths) / len(lengths), 3) if lengths else None,
        "mean_hardness": round(sum(hardnesses) / len(hardnesses), 3) if hardnesses else None,
        "items": [_manual_check_dict(c) for c in checks],
    }


def _resolve_active_shift_for_check(
    db: Session, shift_id: Optional[int], user: models.User
) -> models.ShiftSession:
    shift = db.get(models.ShiftSession, shift_id) if shift_id is not None else None
    if shift is None:
        # Old / stale client: fall back to the user's own open shift.
        shift = (
            db.query(models.ShiftSession)
            .filter(models.ShiftSession.operator_id == user.id, models.ShiftSession.ended_at.is_(None))
            .order_by(models.ShiftSession.started_at.desc())
            .first()
        )
    if shift is None:
        raise HTTPException(status_code=404, detail="No active shift found")
    if shift.ended_at is not None:
        raise HTTPException(status_code=409, detail="Shift is closed - checks can only be added to an active shift")
    return shift


@router.post("/quality/manual-check")
def submit_manual_check(
    payload: ManualCheckPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Record an in-process QC check.

    The check is bound server-side to the shift's currently open run (machine and MO
    snapshot) - the tablet's cached ``mo_id`` is never trusted, so a check always
    lands on the MO / machine the operator is really on. Only an active shift
    accepts checks. ``client_check_id`` makes offline re-submission idempotent."""
    if payload.client_check_id:
        dup = (
            db.query(models.ManualQualityCheck)
            .filter(models.ManualQualityCheck.client_check_id == payload.client_check_id)
            .first()
        )
        if dup is not None:
            return {**_manual_check_dict(dup), "duplicate": True}

    shift = _resolve_active_shift_for_check(db, payload.shift_id, current_user)
    run = shift_lifecycle.active_run(db, shift.id)
    if run is None:
        raise HTTPException(status_code=409, detail="Shift has no open run - start an MO first")

    specs = aggregation.load_run_specs(db, run)
    verdicts, overall = manual_check_rules.evaluate(
        specs,
        sample_weight=payload.sample_weight,
        sample_rods=payload.sample_rods,
        length_mm=payload.length_mm,
        hardness=payload.hardness,
        glue_seam_ok=payload.glue_seam_ok,
        cut_quality_ok=payload.cut_quality_ok,
        visual_appearance_ok=payload.visual_appearance_ok,
    )
    if not verdicts and not (payload.notes or "").strip():
        raise HTTPException(status_code=422, detail="Nothing to record: enter a value, a toggle or a note")

    check = models.ManualQualityCheck(
        shift_id=shift.id,
        mo_id=run.id,
        machine_id=run.machine_id or shift.machine_id,
        po_id=run.po_id,
        mo_ref=run.mo_ref,
        operator_id=current_user.id,
        sample_weight=payload.sample_weight,
        sample_rods=payload.sample_rods if payload.sample_rods > 0 else manual_check_rules.DEFAULT_SAMPLE_RODS,
        length_mm=payload.length_mm,
        hardness=payload.hardness,
        glue_seam_ok=payload.glue_seam_ok,
        cut_quality_ok=payload.cut_quality_ok,
        visual_appearance_ok=payload.visual_appearance_ok,
        notes=payload.notes,
        verdicts=verdicts,
        overall_status=overall,
        measured_at=payload.measured_at or _utcnow(),
        client_check_id=payload.client_check_id,
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return _manual_check_dict(check)


@router.get("/quality/manual-checks")
def list_manual_checks(
    shift_id: Optional[int] = None,
    mo_id: Optional[int] = None,
    machine_id: Optional[int] = None,
    include_voided: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    q = db.query(models.ManualQualityCheck).order_by(
        models.ManualQualityCheck.created_at.desc(), models.ManualQualityCheck.id.desc()
    )
    if shift_id is not None:
        q = q.filter(models.ManualQualityCheck.shift_id == shift_id)
    if mo_id is not None:
        q = q.filter(models.ManualQualityCheck.mo_id == mo_id)
    if machine_id is not None:
        q = q.filter(models.ManualQualityCheck.machine_id == machine_id)
    if not include_voided:
        q = q.filter(models.ManualQualityCheck.voided_at.is_(None))
    return [_manual_check_dict(c) for c in q.limit(500).all()]


@router.post("/quality/manual-checks/{check_id}/void")
def void_manual_check(
    check_id: int,
    payload: VoidCheckPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Void (never delete) a wrongly entered check: the author during the shift, or a supervisor."""
    check = _get_or_404(db, models.ManualQualityCheck, check_id)
    if not (payload.reason or "").strip():
        raise HTTPException(status_code=400, detail="A reason is required")
    if check.voided_at is not None:
        raise HTTPException(status_code=409, detail="Check is already voided")
    if not _is_supervisor(current_user):
        shift = db.get(models.ShiftSession, check.shift_id)
        if check.operator_id != current_user.id or (shift is not None and shift.ended_at is not None):
            raise HTTPException(
                status_code=403, detail="Only the author (during the shift) or a supervisor can void a check"
            )
    check.voided_at = _utcnow()
    check.voided_by = current_user.id
    check.void_reason = payload.reason.strip()
    db.commit()
    db.refresh(check)
    return _manual_check_dict(check)
