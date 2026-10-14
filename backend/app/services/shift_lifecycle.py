"""Shift / production-run lifecycle (Option 2 model).

A *shift* is an operator session; a *production run* is "one MO on one machine
over an interval". Everything that opens, closes or switches runs lives here so
the HTTP layer (``v2_routes``) stays thin and the rules are testable:

* exactly one open run per shift, and one open run per machine (DB-enforced);
* run ``seq`` is ``max(seq) + 1`` (never a hard-coded 1);
* a new run starts *now* (never at the shift start); the previous run is closed
  at the same instant, optionally with the final machine counter;
* closing / stopping / auto-closing / taking over a shift closes its open runs;
* every MO / machine change is audited in ``run_change_log``.

Supervisor corrections of closed runs are in ``run_corrections``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.quality_stats import _num

RUN_OPEN = "OPEN"
RUN_CLOSED = "CLOSED"


class LifecycleError(Exception):
    """Business-rule violation; ``status`` maps 1:1 onto an HTTP status code."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# lookups
# --------------------------------------------------------------------------- #

def resolve_po(db: Session, po_id: Optional[int], mo_ref: Optional[str]) -> Optional[models.PurchaseOrder]:
    if po_id is not None:
        return db.get(models.PurchaseOrder, po_id)
    if mo_ref:
        return db.query(models.PurchaseOrder).filter(models.PurchaseOrder.po_number == mo_ref).first()
    return None


def active_run(db: Session, shift_id: int) -> Optional[models.ProductionRun]:
    return (
        db.query(models.ProductionRun)
        .filter(models.ProductionRun.shift_id == shift_id, models.ProductionRun.ended_at.is_(None))
        .order_by(models.ProductionRun.seq.desc())
        .first()
    )


def machine_busy(db: Session, machine_id: int, exclude_shift_id: Optional[int] = None) -> Optional[str]:
    """Return a human reason when ``machine_id`` already has an open shift or run."""
    q = db.query(models.ShiftSession).filter(
        models.ShiftSession.machine_id == machine_id, models.ShiftSession.ended_at.is_(None)
    )
    if exclude_shift_id is not None:
        q = q.filter(models.ShiftSession.id != exclude_shift_id)
    other = q.first()
    if other is not None:
        return f"Machine already has an open shift (id={other.id})"
    rq = db.query(models.ProductionRun).filter(
        models.ProductionRun.machine_id == machine_id, models.ProductionRun.ended_at.is_(None)
    )
    if exclude_shift_id is not None:
        rq = rq.filter(models.ProductionRun.shift_id != exclude_shift_id)
    other_run = rq.first()
    if other_run is not None:
        return f"Machine already has an open run (id={other_run.id})"
    return None


# --------------------------------------------------------------------------- #
# run primitives
# --------------------------------------------------------------------------- #

def build_spec_snapshot(db: Session, po: Optional[models.PurchaseOrder]) -> Dict[str, Any]:
    """Frozen limits for a run: the flat PO values plus the ``parameters`` rows that
    ``aggregation.load_run_specs`` consumes (the flat form alone yields no specs)."""
    if po is None:
        return {}
    snapshot: Dict[str, Any] = {
        "diameter": _num(po.diameter),
        "length": _num(po.length),
        "pd": _num(po.pd),
        "weight": _num(po.weight),
        "box_type": po.box_type,
    }
    rows = db.query(models.QualitySpec).filter(models.QualitySpec.po_id == po.id).all()
    snapshot["parameters"] = [
        {
            "parameter": s.parameter,
            "nominal": _num(s.nominal),
            "lower_limit": _num(s.lower_limit),
            "upper_limit": _num(s.upper_limit),
            "reject_multiplier": _num(s.reject_multiplier),
            "report_unit": s.report_unit or "",
            "report_scale": _num(s.report_scale) or 1.0,
            "decimals": int(s.decimals or 3),
        }
        for s in rows
    ]
    return snapshot


def next_seq(db: Session, shift_id: int) -> int:
    current = db.query(func.max(models.ProductionRun.seq)).filter(models.ProductionRun.shift_id == shift_id).scalar()
    return (current or 0) + 1


def close_open_runs_for_machine(db: Session, machine_id: int) -> List[models.ProductionRun]:
    """Close every OPEN run on ``machine_id`` whose shift has already ended.

    This is a safety net for runs left open by an older server build (a shift was
    auto-closed / taken over without closing its runs). Without it the
    ``one_open_run_per_machine`` index would block the machine forever."""
    rows = (
        db.query(models.ProductionRun, models.ShiftSession.ended_at)
        .join(models.ShiftSession, models.ProductionRun.shift_id == models.ShiftSession.id)
        .filter(
            models.ProductionRun.machine_id == machine_id,
            models.ProductionRun.ended_at.is_(None),
            models.ShiftSession.ended_at.isnot(None),
        )
        .all()
    )
    for run, ended in rows:
        run.ended_at = ended
        run.status = RUN_CLOSED
    if rows:
        db.flush()
    return [run for run, _ in rows]


def close_open_runs(
    db: Session, shift_id: int, at: datetime, end_counter: Optional[float] = None
) -> List[models.ProductionRun]:
    runs = (
        db.query(models.ProductionRun)
        .filter(models.ProductionRun.shift_id == shift_id, models.ProductionRun.ended_at.is_(None))
        .all()
    )
    for r in runs:
        r.ended_at = at
        r.status = RUN_CLOSED
        if end_counter is not None:
            r.end_counter = end_counter
    if runs:
        db.flush()
    return runs


def open_run(
    db: Session,
    shift: models.ShiftSession,
    machine_id: int,
    po: Optional[models.PurchaseOrder],
    started_at: datetime,
    mo_ref: Optional[str] = None,
) -> models.ProductionRun:
    run = models.ProductionRun(
        shift_id=shift.id,
        seq=next_seq(db, shift.id),
        machine_id=machine_id,
        po_id=po.id if po is not None else None,
        mo_ref=po.po_number if po is not None else mo_ref,
        started_at=started_at,
        status=RUN_OPEN,
        spec_snapshot=build_spec_snapshot(db, po),
    )
    db.add(run)
    db.flush()
    return run


def run_brief(run: Optional[models.ProductionRun]) -> Dict[str, Any]:
    if run is None:
        return {}
    return {"run_id": run.id, "po_id": run.po_id, "mo_ref": run.mo_ref, "machine_id": run.machine_id}


def log_change(
    db: Session,
    run: models.ProductionRun,
    user_id: Optional[int],
    action: str,
    old: Dict[str, Any],
    new: Dict[str, Any],
    reason: Optional[str] = None,
) -> None:
    db.add(models.RunChangeLog(
        run_id=run.id, shift_id=run.shift_id, user_id=user_id, action=action,
        old_values=old, new_values=new, reason=reason,
    ))
    db.flush()  # sessions here run with autoflush=False; make the audit row visible at once


# --------------------------------------------------------------------------- #
# operator actions
# --------------------------------------------------------------------------- #

def start_first_run(
    db: Session, shift: models.ShiftSession, po: Optional[models.PurchaseOrder], now: Optional[datetime] = None
) -> models.ProductionRun:
    """Open the first run of a fresh shift (the run records the machine even without an MO)."""
    close_open_runs_for_machine(db, shift.machine_id)
    return open_run(db, shift, shift.machine_id, po, now or shift.started_at or utcnow())


def resume_run(
    db: Session, shift: models.ShiftSession, po: Optional[models.PurchaseOrder], now: Optional[datetime] = None
) -> models.ProductionRun:
    """A reopened (AUTO_CLOSED -> IN_PROGRESS) shift gets a NEW run: the same MO as
    its last run unless another one is requested."""
    now = now or utcnow()
    if po is None:
        last = (
            db.query(models.ProductionRun)
            .filter(models.ProductionRun.shift_id == shift.id)
            .order_by(models.ProductionRun.seq.desc())
            .first()
        )
        if last is not None and last.po_id is not None:
            po = db.get(models.PurchaseOrder, last.po_id)
    close_open_runs_for_machine(db, shift.machine_id)
    return open_run(db, shift, shift.machine_id, po, now)


def switch_mo(
    db: Session,
    shift: models.ShiftSession,
    user_id: Optional[int],
    po: models.PurchaseOrder,
    end_counter: Optional[float] = None,
    now: Optional[datetime] = None,
) -> Tuple[models.ProductionRun, bool]:
    """Close the open run and open one for ``po`` on the same machine.

    Returns ``(run, changed)``; choosing the MO that is already active is an
    idempotent no-op (``changed`` is False)."""
    if shift.ended_at is not None:
        raise LifecycleError(409, "Shift is not active")
    now = now or utcnow()
    current = active_run(db, shift.id)
    if current is not None and current.po_id == po.id:
        return current, False
    machine_id = current.machine_id if (current is not None and current.machine_id) else shift.machine_id
    old = run_brief(current)
    close_open_runs(db, shift.id, now, end_counter)
    run = open_run(db, shift, machine_id, po, now)
    log_change(db, run, user_id, "SWITCH_MO", old, run_brief(run))
    return run, True


def change_machine(
    db: Session,
    shift: models.ShiftSession,
    user_id: Optional[int],
    new_machine_id: int,
    end_counter: Optional[float] = None,
    po: Optional[models.PurchaseOrder] = None,
    now: Optional[datetime] = None,
) -> models.ProductionRun:
    """Move the operator session to another machine: close the current run and open
    a new one on ``new_machine_id`` (same MO unless ``po`` is given). The shift stays
    open; ``shift.machine_id`` always names the machine it is on right now."""
    if shift.ended_at is not None:
        raise LifecycleError(409, "Shift is not active")
    machine = db.get(models.Machine, new_machine_id)
    if machine is None:
        raise LifecycleError(404, f"Machine {new_machine_id} not found")
    if machine.is_inactive:
        raise LifecycleError(409, f"Machine {machine.name} is inactive")
    if new_machine_id == shift.machine_id:
        raise LifecycleError(409, "Shift is already on this machine")
    busy = machine_busy(db, new_machine_id, exclude_shift_id=shift.id)
    if busy:
        raise LifecycleError(409, busy)

    now = now or utcnow()
    current = active_run(db, shift.id)
    if po is None and current is not None and current.po_id is not None:
        po = db.get(models.PurchaseOrder, current.po_id)
    old = run_brief(current)
    close_open_runs(db, shift.id, now, end_counter)
    close_open_runs_for_machine(db, new_machine_id)
    shift.machine_id = new_machine_id
    db.flush()
    run = open_run(db, shift, new_machine_id, po, now)
    log_change(db, run, user_id, "CHANGE_MACHINE", old, run_brief(run))
    return run


def close_shift_runs(
    db: Session, shift: models.ShiftSession, at: Optional[datetime] = None
) -> List[models.ProductionRun]:
    """Close every open run of ``shift`` (used by close / stop / takeover / auto-close)."""
    return close_open_runs(db, shift.id, at or shift.ended_at or utcnow())



# --------------------------------------------------------------------------- #
# report <-> run link (one report per MO run)
# --------------------------------------------------------------------------- #

def link_report_to_run(db: Session, report: models.ProductionReport) -> Optional[models.ProductionRun]:
    """Attach a freshly saved production report to its production run.

    The tablet's ``run_id`` / ``shift_id`` are only trusted when they agree with the
    report's MO number; otherwise (old APK, stale context, edited report) the run is
    found from the parent report, or from the shift's runs by MO number + machine.
    Sets ``report.run_id`` / ``report.shift_id`` and ``run.report_id`` (the link the
    Odoo dispatcher uses first). Returns the run, or None when nothing matches."""
    po_number = (report.po_number or "").strip()
    run: Optional[models.ProductionRun] = None

    if report.run_id is not None:
        cand = db.get(models.ProductionRun, report.run_id)
        if cand is not None and (cand.mo_ref or "").strip() == po_number:
            run = cand
    if run is None and report.parent_report_id is not None:
        parent = db.get(models.ProductionReport, report.parent_report_id)
        if parent is not None and parent.run_id is not None:
            cand = db.get(models.ProductionRun, parent.run_id)
            if cand is not None and (cand.mo_ref or "").strip() == po_number:
                run = cand
    if run is None and report.shift_id is not None:
        q = db.query(models.ProductionRun).filter(
            models.ProductionRun.shift_id == report.shift_id,
            models.ProductionRun.mo_ref == po_number,
        )
        machine = db.query(models.Machine).filter(models.Machine.name == report.machine_name).first()
        if machine is not None:
            q = q.filter(
                (models.ProductionRun.machine_id == machine.id) | (models.ProductionRun.machine_id.is_(None))
            )
        run = q.order_by(models.ProductionRun.seq.desc()).first()

    if run is None:
        report.run_id = None
        return None

    report.run_id = run.id
    report.shift_id = run.shift_id
    current = db.get(models.ProductionReport, run.report_id) if run.report_id else None
    replaceable = (
        current is None
        or current.id == report.id
        or current.status == "obsolete"
        or bool(current.is_deleted)
        or current.id == report.parent_report_id
    )
    if replaceable:
        run.report_id = report.id
    return run
