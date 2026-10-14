"""Supervisor corrections of an already-closed production run.

A wrong MO or machine on a *closed* run is fixed here (never by editing rows by
hand): the change cascades to the run's manual QC checks and linked production
report(s), the latest shift summary is marked stale and an audit row is written.
Rods keep the machine they were physically measured on.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.services.shift_lifecycle import LifecycleError, build_spec_snapshot, log_change, run_brief


def recompute_po_produced(db: Session, po_number: Optional[str]) -> None:
    """Recompute ``purchase_orders.produced_qty`` exactly like report submission does."""
    if not po_number:
        return
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.po_number == po_number).first()
    if po is None:
        return
    total = (
        db.query(func.sum(models.ProductionReport.produced_rods))
        .filter(
            models.ProductionReport.po_number == po_number,
            (models.ProductionReport.is_deleted.is_(False)) | (models.ProductionReport.is_deleted.is_(None)),
        )
        .scalar()
    )
    po.produced_qty = total or 0


def _cascade_reports(
    db: Session, run: models.ProductionRun, user: models.User,
    machine: Optional[models.Machine], changed_po: bool, changed_machine: bool,
) -> int:
    reports = db.query(models.ProductionReport).filter(models.ProductionReport.run_id == run.id).all()
    for rep in reports:
        before: Dict[str, Any] = {}
        after: Dict[str, Any] = {}
        if changed_po and rep.po_number != run.mo_ref:
            before["po_number"], after["po_number"] = rep.po_number, run.mo_ref
            rep.po_number = run.mo_ref
        if changed_machine and machine is not None and rep.machine_name != machine.name:
            before["machine_name"], after["machine_name"] = rep.machine_name, machine.name
            rep.machine_name = machine.name
        if after:
            rep.is_modified_manually = True
            rep.status = "edited"
            # A corrected report must be re-approved before it reaches Odoo.
            rep.verification_status = "pending"
            rep.verified_by = None
            rep.verified_at = None
            db.add(models.ReportEditLog(
                report_id=rep.id, user_id=user.id, username=user.username,
                changed_fields=json.dumps(sorted(after)),
                old_values=json.dumps(before), new_values=json.dumps(after),
            ))
    return len(reports)


def reassign_run(
    db: Session,
    run: models.ProductionRun,
    user: models.User,
    *,
    po: Optional[models.PurchaseOrder],
    machine_id: Optional[int],
    reason: str,
    allow_synced: bool,
) -> Dict[str, Any]:
    if not (reason or "").strip():
        raise LifecycleError(400, "A reason is required")
    if po is None and machine_id is None:
        raise LifecycleError(400, "Nothing to change: give po_id / mo_ref and / or machine_id")
    shift = db.get(models.ShiftSession, run.shift_id)
    if run.ended_at is None or (shift is not None and shift.ended_at is None):
        raise LifecycleError(409, "Run is still active - use switch-mo / change-machine instead")
    if run.odoo_sync_status == "synced" and not allow_synced:
        raise LifecycleError(409, "Run is already synced to Odoo; only an admin may force this correction")

    machine = None
    if machine_id is not None:
        machine = db.get(models.Machine, machine_id)
        if machine is None:
            raise LifecycleError(404, f"Machine {machine_id} not found")

    changed_po = po is not None and po.id != run.po_id
    changed_machine = machine is not None and machine.id != run.machine_id
    if not changed_po and not changed_machine:
        raise LifecycleError(409, "The run already has these values")

    old = run_brief(run)
    old_po_number = run.mo_ref
    if changed_po:
        run.po_id = po.id
        run.mo_ref = po.po_number
        run.spec_snapshot = build_spec_snapshot(db, po)
    if changed_machine:
        run.machine_id = machine.id

    checks = db.query(models.ManualQualityCheck).filter(models.ManualQualityCheck.mo_id == run.id).all()
    for c in checks:
        if changed_po:
            c.po_id, c.mo_ref = run.po_id, run.mo_ref
        if changed_machine:
            c.machine_id = run.machine_id
    reports_updated = _cascade_reports(db, run, user, machine, changed_po, changed_machine)

    if shift is not None:
        machines = {
            r.machine_id
            for r in db.query(models.ProductionRun).filter(models.ProductionRun.shift_id == shift.id)
            if r.machine_id is not None
        }
        if len(machines) == 1:
            shift.machine_id = next(iter(machines))
        summary = (
            db.query(models.ShiftSummary)
            .filter(models.ShiftSummary.shift_id == shift.id)
            .order_by(models.ShiftSummary.version.desc())
            .first()
        )
        if summary is not None:
            summary.is_stale = True

    db.flush()
    if changed_po:
        recompute_po_produced(db, old_po_number)
        recompute_po_produced(db, run.mo_ref)

    action = "REASSIGN_MACHINE" if (changed_machine and not changed_po) else "REASSIGN_MO"
    new = run_brief(run)
    log_change(db, run, user.id, action, old, new, reason.strip())
    return {"old": old, "new": new, "checks_updated": len(checks), "reports_updated": reports_updated}
