"""Push QUALITY ONLY for legacy (link_only) orders to their Odoo backorder MOs.

Historical MOs are already ``done`` in Odoo, so this module must never touch stock:
it writes a whitelisted set of Quality-Control / MES-sync fields and attaches the
quality certificate (PDF) and the raw measurements (CSV). It never calls completion,
consumption, ``button_mark_done`` or backorder creation (the fake-client test enforces
that only read / write / create / attach calls are used).

Matching: each approved/pending shift report's ``produced_rods`` equals one backorder
quantity (see ``legacy_matching``); rods of that report's shift + time window give the
statistics. Anything ambiguous is reported, never guessed.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app import models
from app.quality_stats import certificate_rows, compute_run_stats
from app.services import aggregation, run_assignment as ra
from app.services.lot_number import lot_number
from app.services.odoo import legacy_matching as lm
from app.services.odoo.client import OdooClient, OdooError, _id_ref
from app.services.odoo.outbound import render_certificate_pdf

logger = logging.getLogger(__name__)

from app.config import get_plant_timezone

PLANT_TZ = get_plant_timezone()

# The ONLY fields this module may write on mrp.production.
ALLOWED_FIELDS = frozenset({
    "mean_diameter", "sd_diameter", "mean_pd", "sd_pd", "quality_status",
    "tested_rods_count", "rejected_rods_count",
    "mes_shift_id", "mes_run_id", "mes_sync_status", "mes_last_sync_at",
    "x_lot_number",
})

_PARAMS = ("pd", "weight", "diameter", "ovality", "roundness", "shape", "hardness", "length")


def _f(value) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def safe_name(mo_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", mo_name or "MO")


def build_summary(specs, rods, mo_name: str, run_id: Optional[int]) -> Dict[str, Any]:
    """Stats + certificate rows for a list of rod objects (pure: no DB access)."""
    rod_dicts = [{k: _f(getattr(r, k, None)) for k in _PARAMS} for r in rods]
    stats = compute_run_stats(rod_dicts, specs)
    return {
        "run_id": run_id,
        "mo_ref": mo_name,
        "status": stats["status"],
        "rods_total": stats["rods_total"],
        "rods_rejected": stats["rods_rejected"],
        "rods_used": stats["rods_used"],
        "parameters": stats["parameters"],
        "certificate": certificate_rows(stats, specs),
    }


def measurements_csv(rods, machine_name: str) -> bytes:
    """Raw rod table as UTF-8 CSV (header + one row per rod)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in lm.csv_rows([
        {
            "measured_at": r.measured_at.astimezone(PLANT_TZ).isoformat(timespec="seconds")
            if r.measured_at else None,
            "rod_no": r.rod_no, "machine": machine_name,
            "diameter": _f(r.diameter), "pd": _f(r.pd), "weight": _f(r.weight),
            "ovality": _f(r.ovality), "roundness": _f(r.roundness),
            "shape": _f(r.shape), "hardness": _f(r.hardness), "length": _f(r.length),
        }
        for r in rods
    ]):
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def push_pair(
    client, mo: Dict[str, Any], summary: Dict[str, Any], csv_bytes: bytes,
    shift_id: Optional[int], run_id: Optional[int], lot: Optional[str], dry_run: bool,
) -> Dict[str, Any]:
    """Write quality fields + attach certificate/CSV to ONE backorder MO."""
    values = client.build_quality_values(summary)
    if values is None:
        return {"mo": mo["name"], "skipped": "no measured rods"}
    values = dict(values)
    values.update({
        "mes_shift_id": int(shift_id or 0),
        "mes_run_id": int(run_id or 0),
        "mes_sync_status": "synced",
        "mes_last_sync_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    })
    current_lot = None
    try:
        rec = client.read("mrp.production", [mo["id"]], ["x_lot_number"])
        current_lot = (rec[0].get("x_lot_number") if rec else None) or None
    except OdooError:
        lot = None  # stock_cmr_packing not installed: no lot field to fill
    if lot and not current_lot:  # additive: never overwrite an existing lot
        values["x_lot_number"] = lot
    unexpected = set(values) - ALLOWED_FIELDS
    if unexpected:
        raise RuntimeError(f"refusing to write non-quality fields: {sorted(unexpected)}")

    base = safe_name(mo["name"])
    pdf = render_certificate_pdf(summary)
    files = [(f"Quality_Measurements_{base}.csv", len(csv_bytes))]
    if pdf:
        files.insert(0, (f"Quality_Certificate_{base}.pdf", len(pdf)))
    result = {"mo": mo["name"], "mo_id": mo["id"], "values": values,
              "attachments": [f[0] for f in files], "rods": summary["rods_total"],
              "status": summary["status"]}
    if dry_run:
        return result
    client.write("mrp.production", [mo["id"]], values)
    if pdf:
        client.attach_file(f"Quality_Certificate_{base}.pdf", "mrp.production", mo["id"],
                           pdf, "application/pdf")
    client.attach_file(f"Quality_Measurements_{base}.csv", "mrp.production", mo["id"],
                       csv_bytes, "text/csv")
    return result


def resolve_report_mo(client, po: models.PurchaseOrder, produced_rods) -> Optional[tuple]:
    """Return ``(mo_id, mo_name)`` for the done MO whose rod quantity == ``produced_rods``.

    Used when a single shift report is approved: its quantity points at exactly one
    backorder of the order's Odoo chain. Returns ``None`` when the order is unlinked,
    the chain is missing, or the quantity is not a unique done MO.
    """
    if po is None or not po.odoo_mo_id:
        return None
    root = client.read("mrp.production", [int(po.odoo_mo_id)], ["procurement_group_id"])
    group = _id_ref(root[0].get("procurement_group_id")) if root else None
    if not group:
        return None
    mos_raw = client.search_read(
        "mrp.production", [["procurement_group_id", "=", group]],
        ["id", "name", "state", "product_qty", "product_uom_id"],
        order="backorder_sequence asc, id asc",
    )
    ratios = client.fetch_uom_ratios({_id_ref(m.get("product_uom_id")) for m in mos_raw
                                      if _id_ref(m.get("product_uom_id"))})
    qty = int(round(produced_rods or 0))
    matches = []
    for m in mos_raw:
        if m.get("state") != "done":
            continue
        rods = float(m.get("product_qty") or 0) * ratios.get(_id_ref(m.get("product_uom_id")), 1.0)
        if int(round(rods)) == qty:
            matches.append((int(m["id"]), m["name"]))
    return matches[0] if len(matches) == 1 else None


def _report_rods_window(session: Session, report, shift, windows) -> List[Any]:
    """Rods of this report's run that fall inside the report's own time window."""
    # `windows`: list of (po_number, run_id, t0, t1, report_id) for the shift.
    mine = next((w for w in windows if w[4] == report.id), None)
    if mine is None:
        return []
    run_id, t0, t1 = mine[1], mine[2], mine[3]
    rods = (
        session.query(models.QualityMeasurement)
        .filter(models.QualityMeasurement.run_id == run_id)
        .order_by(models.QualityMeasurement.measured_at, models.QualityMeasurement.rod_no)
        .all()
    )
    out = []
    for r in rods:
        if r.measured_at is None:
            continue
        local = r.measured_at.astimezone(PLANT_TZ)
        if t0 <= local <= t1 + ra.GRACE:
            out.append(r)
    return out


def plan_order(session: Session, client, po: models.PurchaseOrder, windows_by_shift) -> Dict[str, Any]:
    """Match the order's non-deleted reports to the done MOs of its Odoo chain."""
    root = client.read("mrp.production", [int(po.odoo_mo_id)], ["procurement_group_id"])
    group = _id_ref(root[0].get("procurement_group_id")) if root else None
    if not group:
        return {"po": po.po_number, "error": "no procurement group on root MO"}
    mos_raw = client.search_read(
        "mrp.production", [["procurement_group_id", "=", group]],
        ["id", "name", "state", "product_qty", "product_uom_id", "backorder_sequence"],
        order="backorder_sequence asc, id asc",
    )
    ratios = client.fetch_uom_ratios({_id_ref(m.get("product_uom_id")) for m in mos_raw
                                      if _id_ref(m.get("product_uom_id"))})
    mos = [{"id": int(m["id"]), "name": m["name"], "state": m["state"],
            "rods": float(m.get("product_qty") or 0) * ratios.get(_id_ref(m.get("product_uom_id")), 1.0),
            "seq": int(m.get("backorder_sequence") or 0)}
           for m in mos_raw]
    reports = (
        session.query(models.ProductionReport)
        .filter(models.ProductionReport.po_number == po.po_number,
                models.ProductionReport.status != "obsolete",
                (models.ProductionReport.is_deleted.is_(None))
                | (models.ProductionReport.is_deleted.is_(False)))
        .order_by(models.ProductionReport.report_date, models.ProductionReport.id)
        .all()
    )
    rep_in = [{"id": r.id, "rods": int(r.produced_rods or 0), "obj": r,
               "date": str(r.report_date), "machine": r.machine_name,
               "shift": r.shift_name} for r in reports]
    match = lm.match_reports_to_mos(rep_in, mos)
    return {"po": po.po_number, "match": match, "mos": mos, "reports": rep_in}


def run_order(session: Session, client, po: models.PurchaseOrder, windows_by_shift,
              dry_run: bool = True) -> Dict[str, Any]:
    """Plan (and, when ``dry_run`` is False, push) quality for one legacy order."""
    plan = plan_order(session, client, po, windows_by_shift)
    if "error" in plan:
        return plan
    results: List[Dict[str, Any]] = []
    for rep, mo in plan["match"]["pairs"]:
        report = rep["obj"]
        run = (
            session.query(models.ProductionRun)
            .filter(models.ProductionRun.po_id == po.id,
                    models.ProductionRun.report_id == report.id).first()
        )
        shift = None
        windows = []
        if run is None:
            # Legacy runs carry no report_id: locate the run through the report's window.
            for sid, wins in windows_by_shift.items():
                for w in wins:
                    if w[4] == report.id:
                        run = session.get(models.ProductionRun, w[1])
                        windows, shift = wins, session.get(models.ShiftSession, sid)
                        break
                if run is not None:
                    break
        else:
            shift = session.get(models.ShiftSession, run.shift_id)
            windows = windows_by_shift.get(run.shift_id, [])
        if run is None or shift is None:
            results.append({"mo": mo["name"], "skipped": "no MES run for report", "report": report.id})
            continue
        rods = _report_rods_window(session, report, shift, windows)
        specs = aggregation.load_run_specs(session, run)
        summary = build_summary(specs, rods, mo["name"], run.id)
        machine = session.get(models.Machine, shift.machine_id)
        machine_name = machine.name if machine else ""
        csv_bytes = measurements_csv(rods, machine_name)
        lot = lot_number(shift.started_at, machine_name)
        out = push_pair(client, mo, summary, csv_bytes, shift.id, run.id, lot, dry_run)
        out["report"] = report.id
        out["lot"] = lot
        results.append(out)
        if not dry_run and "skipped" not in out:
            run.odoo_mo_id = mo["id"]
            run.report_id = run.report_id or report.id
            run.odoo_sync_status = "synced"
    if not dry_run:
        session.commit()
    m = plan["match"]
    return {
        "po": po.po_number, "dry_run": dry_run, "results": results,
        "ambiguous": m["ambiguous"],
        "unmatched_reports": [r["id"] for r in m["unmatched_reports"]],
        "unmatched_mos": [x["name"] for x in m["unmatched_mos"]],
    }

