"""Unified v2 API routes (docs/api.md).

Shifts (the central aggregate), rod-level measurements, quality/certificate stats
and the Odoo outbox. Pure HTTP layer: the actual statistics live in
``app/quality_stats`` / ``app/services/aggregation``, shift resolution in
``app/services/shift_resolver``.
"""

from __future__ import annotations

import csv as _csv
import hashlib
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_user
from app.database import get_db
from app.quality_stats import STATUS_FAIL, STATUS_NO_DATA, STATUS_PASS, STATUS_WARN, _is_rejected, _num, compute_run_stats, certificate_rows
from app.services import aggregation, shift_resolver
from app.services.odoo import outbound as odoo_outbound

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


def _shift_dict(s: models.ShiftSession) -> Dict[str, Any]:
    return {
        "id": s.id, "machine_id": s.machine_id, "operator_id": s.operator_id,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "status": s.status, "plant_tz": s.plant_tz, "source": s.source,
        "client_shift_id": s.client_shift_id,
        "closed_at": s.closed_at.isoformat() if s.closed_at else None,
        "closed_by": s.closed_by, "legacy_report_key": s.legacy_report_key,
    }


def _run_dict(r: models.ProductionRun) -> Dict[str, Any]:
    return {
        "id": r.id, "shift_id": r.shift_id, "seq": r.seq, "po_id": r.po_id,
        "mo_ref": r.mo_ref,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "status": r.status,
    }


_MEASURE_PARAM_KEYS = ("pd", "weight", "diameter", "ovality", "roundness", "shape", "hardness")


BUDAPEST = ZoneInfo("Europe/Budapest")


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


class ShiftClose(BaseModel):
    ended_at: Optional[datetime] = None
    manual_quality: Optional[Dict[str, Dict[str, Optional[float]]]] = None
    material_logs: List[Dict[str, Any]] = []
    scrap_logs: List[Dict[str, Any]] = []


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
    if status:
        q = q.filter(models.ShiftSession.status == status)
    if started_after:
        q = q.filter(models.ShiftSession.started_at >= started_after)
    if started_before:
        q = q.filter(models.ShiftSession.started_at <= started_before)
    return [_shift_dict(s) for s in q.order_by(models.ShiftSession.started_at.desc()).limit(500).all()]


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
    if existing:
        raise HTTPException(status_code=409, detail=f"Machine already has an open shift (id={existing.id})")
    shift = models.ShiftSession(
        machine_id=payload.machine_id,
        operator_id=payload.operator_id or current_user.id,
        started_at=payload.started_at or _utcnow(),
        status="OPEN",
        plant_tz=payload.plant_tz,
        source=payload.source,
        client_shift_id=payload.client_shift_id,
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return _shift_dict(shift)


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

    # Idempotent: already closed -> return the stored summary.
    if shift.ended_at is not None:
        summary = (
            db.query(models.ShiftSummary)
            .filter(models.ShiftSummary.shift_id == shift_id)
            .order_by(models.ShiftSummary.version.desc())
            .first()
        )
        if summary:
            return summary.payload
        return _shift_dict(shift)

    shift.ended_at = payload.ended_at or _utcnow()
    shift.status = "CLOSED"
    shift.closed_at = _utcnow()
    shift.closed_by = current_user.id

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
        run_summaries.append(s)
    verdict = _overall_verdict([r["status"] for r in run_summaries])
    return {
        "schema_version": "1.1",
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


def _shift_quality_summary(db: Session, shift_id: int) -> Dict[str, Any]:
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
    return {
        "status": stats["status"],
        "rods_total": stats["rods_total"],
        "rods_rejected": stats["rods_rejected"],
        "rods_used": stats["rods_used"],
        "parameters": stats["parameters"],
        "certificate": certificate_rows(stats, specs),
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
    current_user: models.User = Depends(get_current_user),
):
    """Ingest one station file (multipart) through the same parse -> resolve -> insert pipeline."""
    data = await file.read()
    from app.services.parsers.quantum_csv import parse_bytes

    try:
        sample = parse_bytes(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"parse failed: {exc}")

    sha256 = hashlib.sha256(data).hexdigest()
    if db.query(models.IngestionFile).filter(models.IngestionFile.sha256 == sha256).first():
        return {"status": "duplicate", "sha256": sha256, "filename": file.filename}

    machine_id = shift_resolver.resolve_machine(db, "quantum_neo", "maker", sample.maker)
    produced_at = sample.produced_on or _utcnow()
    if produced_at.tzinfo is None:
        produced_at = produced_at.replace(tzinfo=timezone.utc)

    kind, is_non_production = shift_resolver.classify_sample(sample.maker)
    shift_id, link_status = (None, shift_resolver.LINK_NON_PRODUCTION) if is_non_production else shift_resolver.resolve_shift(db, machine_id, produced_at)
    run_id: Optional[int] = None
    if shift_id is not None:
        run_id, _ = shift_resolver.resolve_run(db, shift_id, produced_at, sample.mo_ref)

    db_sample = models.QualitySample(
        shift_id=shift_id, run_id=run_id, machine_id=machine_id,
        link_status=link_status, link_source="auto", kind=kind,
        source_instrument_id=sample.instrument_id,
        source_maker=sample.maker, source_team=sample.team,
        sample_id=sample.sample_id, mo_ref=sample.mo_ref,
        brand=sample.brand, operator=sample.operator,
        produced_at=produced_at,
        batch_started_at=sample.batch_start,
        batch_ended_at=sample.batch_end,
        rods_declared=sample.rods_count,
        file_sha256=sha256,
    )
    db.add(db_sample)
    db.flush()
    for rod in sample.rods:
        db.add(models.QualityMeasurement(
            sample_id=db_sample.id, shift_id=shift_id, run_id=run_id, machine_id=machine_id,
            measured_at=produced_at, rod_no=rod.rod_no, pd=rod.pd, weight=rod.weight,
            diameter=rod.diameter, ovality=rod.ovality, roundness=rod.roundness,
            shape=rod.shape, hardness=rod.hardness,
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
            run_id, _ = shift_resolver.resolve_run(db, shift_id, s.produced_at, s.mo_ref)
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
        f"MO reference: {run.mo_ref or '(none)'} | Status: {summary.get('status')}",
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
    summary = _shift_quality_summary(db, shift.id)
    pdf_bytes = _render_certificate_table(
        f"Internal Quality Summary - Shift {shift.id}",
        f"Machine: {shift.machine_id} | Status: {summary.get('status')}",
        summary,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=quality_shift_{shift_id}.pdf"},
    )


def _render_certificate_table(title: str, subtitle: str, summary: Dict[str, Any]) -> bytes:
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
    story.append(Spacer(1, 8 * mm))

    header = ["Parameter", "Unit", "Nominal", "Lower", "Upper", "Mean", "SD", "n", "Status"]
    rows = [header]
    for row in summary.get("certificate", []):
        rows.append([
            str(row.get("parameter", "")),
            str(row.get("unit", "")),
            _fmt(row.get("nominal")), _fmt(row.get("lower")), _fmt(row.get("upper")),
            _fmt(row.get("mean")), _fmt(row.get("sd")),
            str(row.get("n", "")),
            str(row.get("status", "")),
        ])
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def _fmt(value: Any) -> str:
    return "" if value is None else f"{value}"


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


@router.post("/odoo/dispatch")
def dispatch_odoo_now(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Dispatch pending outbox items to Odoo now (admin only)."""
    if current_user.username != "superadmin":
        raise HTTPException(status_code=403, detail="Admin only")
    from app.database import SessionLocal

    cfg = odoo_outbound.OdooConfig.from_env()
    if not (cfg.enabled and cfg.valid()):
        raise HTTPException(status_code=400, detail="Odoo is not configured")
    return {"dispatched": odoo_outbound.dispatch_pending(SessionLocal, cfg)}


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


def _active_po_id_for_machine(db: Session, machine_id: int) -> Optional[int]:
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
            .filter(models.ShiftSession.machine_id == machine_id, models.ProductionRun.po_id.isnot(None))
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
        shift = db.get(models.ShiftSession, run.shift_id)
        if shift is None:
            continue
        m = db.get(models.Machine, shift.machine_id)
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


def _specs_for_context(db: Session, machine_id: Optional[int], po_id: Optional[int], shift_id: Optional[int]) -> Dict:
    if po_id is not None:
        rows = db.query(models.QualitySpec).filter(models.QualitySpec.po_id == po_id).all()
        if rows:
            return aggregation.build_param_specs(rows)
    if shift_id is not None:
        specs = _load_shift_specs(db, shift_id)
        if specs:
            return specs
    if machine_id is not None:
        specs = _load_machine_specs(db, machine_id)
        if specs:
            return specs
    return {}


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


def _quality_header(db: Session, machine, shift, po_id) -> Dict[str, Any]:
    header: Dict[str, Any] = {
        "machine": machine or "All",
        "po_number": None,
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
    if po_id is not None:
        po = db.get(models.PurchaseOrder, po_id)
        if po is not None:
            header["po_number"] = po.po_number
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
    return header


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
            machine_id = shift.machine_id

    base = db.query(models.QualityMeasurement)
    if machine_id is not None:
        base = base.filter(models.QualityMeasurement.machine_id == machine_id)
    if shift is not None:
        in_range = (models.QualityMeasurement.machine_id == shift.machine_id) & (models.QualityMeasurement.measured_at >= shift.started_at)
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

    specs = _specs_for_context(db, machine_id, po_id, shift_id)
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
        "series": series,
        "active_machines": sorted(series.keys()),
        "measurements": {"total": total, "page": page, "page_size": page_size, "rows": rows_out},
        "raw_rows": raw_rows,
    }
