"""
Shift/run quality aggregation and certificate assembly.

This module ties together:
  * quality_stats (pure statistics: mean, sample/population SD, rejection rules)
  * the unified models (QualitySpec, QualityMeasurement, ProductionRun, ...)
  * certificate_rows (the certificate parameter table with lower/upper limits)

It is deliberately free of HTTP concerns so it can be called from the shift-close
endpoint, a background recompute job, and the certificate renderer.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.quality_stats import (
    STATUS_NOT_MEASURED,
    STATUS_PASS,
    ParamSpec,
    certificate_rows,
    compute_run_stats,
    manual_rods,
    manual_triacetin_measurements,
    merge_manual_parameters,
    merge_triacetin,
    triacetin_measurements,
    triacetin_status,
)


def build_param_specs(specs: Iterable[models.QualitySpec]) -> Dict[str, ParamSpec]:
    """Convert QualitySpec rows into quality_stats.ParamSpec objects."""
    result: Dict[str, ParamSpec] = {}
    for s in specs:
        nominal = _f(s.nominal)
        lower = _f(s.lower_limit)
        upper = _f(s.upper_limit)
        report_scale = _f(s.report_scale) or 1.0
        report_unit = s.report_unit or ""
        if s.parameter == "weight":
            # Weight specs are stored in report units (mg/rod) when the nominal
            # is implausibly large for a single rod. Normalize to g/rod so rejection
            # bounds compare like-for-like against the per-rod measurement, and
            # report weight in mg/rod (g/rod x 1000).
            if report_scale > 1 and nominal is not None and nominal > 5.0:
                nominal = nominal / report_scale
                lower = None if lower is None else lower / report_scale
                upper = None if upper is None else upper / report_scale
            report_unit = "mg"
            report_scale = 1000.0
        result[s.parameter] = ParamSpec(
            parameter=s.parameter,
            nominal=nominal,
            lower=lower,
            upper=upper,
            reject_multiplier=_f(s.reject_multiplier),
            report_unit=report_unit,
            report_scale=report_scale,
            decimals=int(s.decimals or 3),
        )
    return result


GLOBAL_SPECS_SETTING_KEY = "mes_global_quality_specs"

# Factory-wide fallback (Level 3). Tolerances come from quality_settings +
# system_settings; nominals come from the PO columns (auto-measured params) or a
# global override. Hardness has no PO column, so it is None unless configured.
_GLOBAL_SPEC_PARAMS = ("diameter", "pd", "weight", "length", "hardness")
_FALLBACK_REPORT_UNIT = {"diameter": "mm", "pd": "mm WG", "weight": "mg", "length": "mm", "hardness": "%"}


def global_spec_defaults(session: Session) -> Dict[str, Dict[str, Optional[float]]]:
    """Level 3 factory defaults: ``{param: {nominal, tolerance}}``.

    Merged from the ``quality_settings`` singleton (diameter/pd tolerances) and
    the ``system_settings`` override ``mes_global_quality_specs`` (admin-editable
    per-parameter nominal/tolerance).
    """
    defaults: Dict[str, Dict[str, Optional[float]]] = {
        "diameter": {"nominal": None, "tolerance": 0.03},
        "pd": {"nominal": None, "tolerance": 20.0},
        "weight": {"nominal": None, "tolerance": None},
        "length": {"nominal": None, "tolerance": 0.5},
        "hardness": {"nominal": None, "tolerance": None},
    }
    qs = session.query(models.QualitySettings).first()
    if qs is not None:
        _set_global(defaults, "diameter", "tolerance", qs.diameter_tolerance)
        _set_global(defaults, "pd", "tolerance", qs.pd_tolerance)
    row = session.get(models.SystemSetting, GLOBAL_SPECS_SETTING_KEY)
    overrides = (row.value or {}) if row is not None else {}
    if isinstance(overrides, dict):
        for param in _GLOBAL_SPEC_PARAMS:
            entry = overrides.get(param)
            if isinstance(entry, dict):
                _set_global(defaults, param, "nominal", entry.get("nominal"))
                _set_global(defaults, param, "tolerance", entry.get("tolerance"))
    return defaults


def _set_global(defaults, param: str, key: str, value) -> None:
    f = _f(value)
    if f is not None:
        defaults[param][key] = f


def fallback_param_specs(
    session: Session,
    run: Optional[models.ProductionRun] = None,
    po: Optional[models.PurchaseOrder] = None,
) -> Dict[str, ParamSpec]:
    """Level 3 ParamSpecs from the PO nominal columns + factory default tolerances.

    Guarantees ``compute_run_stats`` receives a non-empty spec set for the
    measured parameters even when an order has no ``quality_specs`` rows (e.g.
    Odoo-imported orders whose backorders lost their targets).
    """
    if po is None and run is not None and run.po_id:
        po = session.get(models.PurchaseOrder, run.po_id)
    glob = global_spec_defaults(session)
    nominals = {
        "diameter": getattr(po, "diameter", None),
        "pd": getattr(po, "pd", None),
        "weight": getattr(po, "weight", None),
        "length": getattr(po, "length", None),
        "hardness": None,
    }
    rows = []
    for param in _GLOBAL_SPEC_PARAMS:
        nominal = _f(nominals.get(param))
        if nominal is None:
            nominal = _f((glob.get(param) or {}).get("nominal"))
        tolerance = _f((glob.get(param) or {}).get("tolerance"))
        if nominal is None and tolerance is None:
            continue
        lower = None if (nominal is None or tolerance is None) else nominal - tolerance
        upper = None if (nominal is None or tolerance is None) else nominal + tolerance
        rows.append(SimpleNamespace(
            parameter=param,
            nominal=nominal,
            lower_limit=lower,
            upper_limit=upper,
            reject_multiplier=3.0,
            report_unit=_FALLBACK_REPORT_UNIT.get(param, ""),
            report_scale=1000.0 if param == "weight" else 1.0,
            decimals=3,
        ))
    return build_param_specs(rows)


def load_run_specs(session: Session, run: models.ProductionRun) -> Dict[str, ParamSpec]:
    """Resolve a run's frozen specs, then quality_specs rows, then global defaults."""
    snapshot = run.spec_snapshot or {}
    # Only a snapshot that carries ``parameters`` rows is a usable frozen spec. The
    # flat ``{diameter, length, pd, ...}`` form written by older tablet builds and
    # the ETL has no limits, so it must fall through to the quality_specs rows
    # instead of yielding "no specs".
    frozen = snapshot.get("parameters") if isinstance(snapshot, dict) else None
    if frozen:
        specs = [
            models.QualitySpec(**row) if isinstance(row, dict) else row
            for row in frozen
        ]
        built = build_param_specs([s for s in specs if isinstance(s, models.QualitySpec)])
        if built:
            return built
    if run.po_id is not None:
        rows = session.query(models.QualitySpec).filter(
            models.QualitySpec.po_id == run.po_id
        ).all()
        built = build_param_specs(rows)
        if built:
            return built
    # Level 3: PO nominal columns + factory default tolerances. Always returns a
    # spec set for the measured parameters so compute_run_stats never gets {}.
    return fallback_param_specs(session, run=run)


def load_rods(session: Session, run_id: int) -> List[Dict[str, Optional[float]]]:
    """Return the run's PRODUCTION rods as the dict shape quality_stats expects.

    Dry (``is_triacetin``) batches are excluded from every statistic; they are
    only used to compute the triacetin percentage (see ``compute_triacetin``).
    """
    rods = (
        session.query(models.QualityMeasurement)
        .join(models.QualitySample, models.QualityMeasurement.sample_id == models.QualitySample.id)
        .filter(
            models.QualityMeasurement.run_id == run_id,
            models.QualitySample.is_triacetin.is_(False),
        )
        .order_by(
            models.QualityMeasurement.measured_at,
            models.QualityMeasurement.sample_id,
            models.QualityMeasurement.rod_no,
        )
        .all()
    )
    return [
        {
            "pd": _f(r.pd),
            "weight": _f(r.weight),
            "diameter": _f(r.diameter),
            "ovality": _f(r.ovality),
            "roundness": _f(r.roundness),
            "shape": _f(r.shape),
            "hardness": _f(r.hardness),
        }
        for r in rods
    ]


def load_triacetin_samples(
    session: Session,
    run_id: Optional[int] = None,
    run_ids: Optional[List[int]] = None,
    shift_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Chronological batch summaries (regular + dry) for triacetin pairing.

    Each entry carries ``time`` (produced_at), ``is_triacetin``, ``rod_count``
    (actual measured rods, falling back to ``rods_declared``) and ``weight``
    (mean weight per rod for that batch).
    """
    q = session.query(models.QualitySample)
    if run_ids:
        q = q.filter(models.QualitySample.run_id.in_(run_ids))
    elif run_id is not None:
        q = q.filter(models.QualitySample.run_id == run_id)
    elif shift_id is not None:
        q = q.filter(models.QualitySample.shift_id == shift_id)
    else:
        return []

    samples = q.order_by(models.QualitySample.produced_at, models.QualitySample.id).all()
    result: List[Dict[str, Any]] = []
    for s in samples:
        rod_count = (
            session.query(func.count(models.QualityMeasurement.id))
            .filter(models.QualityMeasurement.sample_id == s.id)
            .scalar()
        ) or (s.rods_declared or 0)
        mean_w = (
            session.query(func.avg(models.QualityMeasurement.weight))
            .filter(
                models.QualityMeasurement.sample_id == s.id,
                models.QualityMeasurement.weight.isnot(None),
            )
            .scalar()
        )
        result.append({
            "time": s.produced_at,
            "is_triacetin": bool(s.is_triacetin),
            "rod_count": int(rod_count or 0),
            "weight": _f(mean_w),
        })
    return result


def compute_triacetin(
    session: Session,
    run_id: Optional[int] = None,
    run_ids: Optional[List[int]] = None,
    shift_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Compute paired triacetin percentages for a run / set of runs / shift."""
    return triacetin_measurements(
        load_triacetin_samples(session, run_id=run_id, run_ids=run_ids, shift_id=shift_id)
    )


def inject_triacetin_certificate(
    rows: List[Dict[str, Any]],
    specs: Dict[str, ParamSpec],
    overall_pct: Optional[float],
) -> List[Dict[str, Any]]:
    """Fill the certificate's Triacetin row with the computed percentage."""
    spec = specs.get("triacetin")
    for row in rows:
        if row.get("parameter") == "triacetin":
            row["mean"] = overall_pct
            row["sd"] = None
            row["n"] = None
            row["source"] = "triacetin" if overall_pct is not None else "not_measured"
            row["status"] = (
                triacetin_status(overall_pct, spec)
                if spec is not None
                else (STATUS_NOT_MEASURED if overall_pct is None else STATUS_PASS)
            )
    return rows


def inject_triacetin_parameters(
    parameters: Dict[str, Any],
    specs: Dict[str, ParamSpec],
    overall_pct: Optional[float],
) -> None:
    """Mirror the computed triacetin % into the ``parameters`` roll-up (for cards)."""
    spec = specs.get("triacetin")
    entry = parameters.get("triacetin")
    if entry is None:
        if spec is None:
            return
        entry = {
            "nominal": spec.nominal, "lower": spec.lower, "upper": spec.upper,
            "report_unit": spec.report_unit, "report_scale": spec.report_scale,
            "decimals": spec.decimals, "n": 0,
        }
        parameters["triacetin"] = entry
    entry["mean"] = overall_pct
    entry["sd_samp"] = None
    entry["sd_pop"] = None
    entry["source"] = "triacetin" if overall_pct is not None else "not_measured"
    entry["status"] = (
        triacetin_status(overall_pct, spec)
        if spec is not None
        else (STATUS_NOT_MEASURED if overall_pct is None else STATUS_PASS)
    )


def load_manual_checks(session: Session, run_id: int) -> List[models.ManualQualityCheck]:
    """Non-voided manual QC checks bound to one run, in entry order."""
    return (
        session.query(models.ManualQualityCheck)
        .filter(
            models.ManualQualityCheck.mo_id == run_id,
            models.ManualQualityCheck.voided_at.is_(None),
        )
        .order_by(models.ManualQualityCheck.id)
        .all()
    )


def manual_check_dicts(checks: Iterable[models.ManualQualityCheck]) -> List[Dict[str, Any]]:
    """Flatten manual check rows into the dict shape ``manual_rods`` expects.

    Includes the qualitative toggles and timestamp so the certificate can render a
    full per-check "manual measurement" table.
    """
    return [
        {
            "sample_weight": _f(c.sample_weight),
            "sample_rods": int(c.sample_rods or 10),
            "length_mm": _f(c.length_mm),
            "hardness": _f(c.hardness),
            "triacetin_wet_mg": _f(c.triacetin_wet_mg),
            "triacetin_dry_mg": _f(c.triacetin_dry_mg),
            "triacetin_rods": c.triacetin_rods,
            "triacetin_pct": _f(c.triacetin_pct),
            "glue_seam_ok": c.glue_seam_ok,
            "cut_quality_ok": c.cut_quality_ok,
            "visual_appearance_ok": c.visual_appearance_ok,
            "notes": c.notes,
            "measured_at": c.measured_at.isoformat() if c.measured_at else None,
        }
        for c in checks
    ]


def manual_remarks(check_dicts: List[Dict[str, Any]]) -> Optional[str]:
    notes = [
        str(d["notes"]).strip()
        for d in check_dicts
        if d.get("notes") and str(d["notes"]).strip()
    ]
    return " | ".join(notes) if notes else None


def manual_measurements(
    parameters: Dict[str, Any], check_dicts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Compact manual roll-up (count + per-parameter mean/SD) for the summary."""
    out: Dict[str, Any] = {"count": len(check_dicts)}
    for name, p in parameters.items():
        if p.get("manual_n"):
            out[name] = {
                "mean": p.get("manual_mean"),
                "sd": p.get("manual_sd"),
                "n": p.get("manual_n"),
            }
    return out


def manual_table_rows(check_dicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-check rows for the certificate's "Manual measurement" table.

    The operator enters weight in grams per ``sample_rods`` rods; the table shows it
    in mg per rod (grams x 1000 / rods).
    """
    rows: List[Dict[str, Any]] = []
    for idx, d in enumerate(check_dicts, start=1):
        w = _f(d.get("sample_weight"))
        n = int(d.get("sample_rods") or 10)
        weight_mg = round(w * 1000 / n, 2) if (w is not None and n) else None
        rows.append({
            "seq": idx,
            "measured_at": d.get("measured_at"),
            "length_mm": _f(d.get("length_mm")),
            "weight_mg": weight_mg,
            "hardness": _f(d.get("hardness")),
            "glue_seam_ok": d.get("glue_seam_ok"),
            "cut_quality_ok": d.get("cut_quality_ok"),
            "visual_appearance_ok": d.get("visual_appearance_ok"),
            "triacetin_pct": _f(d.get("triacetin_pct")),
            "notes": d.get("notes"),
        })
    return rows


def compute_run_summary(
    session: Session,
    run: models.ProductionRun,
    manual: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
    sd_kind: str = "samp",
) -> Dict:
    """Compute stats + certificate rows for one run.

    Station measurements (per rod) are merged with the operator's manual QC
    checks: a manual value fills a parameter only when the station did not
    measure it (length, hardness; weight only as a fallback), so a station
    measurement can never be overwritten.
    """
    specs = load_run_specs(session, run)
    rods = load_rods(session, run.id)
    stats = compute_run_stats(rods, specs)
    auto_rows = certificate_rows(stats, specs, manual=manual, sd_kind=sd_kind)

    check_dicts = manual_check_dicts(load_manual_checks(session, run.id))
    merge_manual_parameters(stats["parameters"], manual_rods(check_dicts), specs)

    tri = compute_triacetin(session, run_id=run.id)
    tri = merge_triacetin(tri, manual_triacetin_measurements(check_dicts))
    rows = certificate_rows(stats, specs, manual=manual, sd_kind=sd_kind)
    inject_triacetin_certificate(rows, specs, tri["overall_pct"])
    inject_triacetin_parameters(stats["parameters"], specs, tri["overall_pct"])
    return {
        "run_id": run.id,
        "mo_ref": run.mo_ref,
        "machine_id": run.machine_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "end_counter": float(run.end_counter) if run.end_counter is not None else None,
        "status": stats["status"],
        "rods_total": stats["rods_total"],
        "rods_rejected": stats["rods_rejected"],
        "rods_used": stats["rods_used"],
        "parameters": stats["parameters"],
        "automatic": auto_rows,
        "certificate": rows,
        "remarks": manual_remarks(check_dicts),
        "manual_measurements": manual_measurements(stats["parameters"], check_dicts),
        "manual_checks": manual_table_rows(check_dicts),
        "triacetin": tri["measurements"],
        "triacetin_overall": tri["overall_pct"],
    }


def compute_order_summary(session: Session, po_id: int) -> Dict:
    """Quality summary of a WHOLE order: every rod of every run (shift / backorder).

    Statistics are recomputed over all tested rods of the order (mean, sample SD n-1,
    rejected count); ``runs`` lists the per-run results for the certificate's detail
    table. Specs come from the order's ``quality_specs`` rows (same for every run).
    """
    runs = (
        session.query(models.ProductionRun)
        .filter(models.ProductionRun.po_id == po_id)
        .order_by(models.ProductionRun.id)
        .all()
    )
    rows = session.query(models.QualitySpec).filter(models.QualitySpec.po_id == po_id).all()
    specs = build_param_specs(rows)
    if not specs and runs:
        specs = load_run_specs(session, runs[0])

    run_ids = [r.id for r in runs]
    rods = []
    if run_ids:
        rods = (
            session.query(models.QualityMeasurement)
            .join(models.QualitySample, models.QualityMeasurement.sample_id == models.QualitySample.id)
            .filter(
                models.QualityMeasurement.run_id.in_(run_ids),
                models.QualitySample.is_triacetin.is_(False),
            )
            .order_by(
                models.QualityMeasurement.measured_at,
                models.QualityMeasurement.sample_id,
                models.QualityMeasurement.rod_no,
            )
            .all()
        )
    keys = ("pd", "weight", "diameter", "ovality", "roundness", "shape", "hardness", "length")
    rod_dicts = [{k: _f(getattr(r, k)) for k in keys} for r in rods]
    stats = compute_run_stats(rod_dicts, specs)
    auto_rows = certificate_rows(stats, specs)

    # Merge the operator's manual QC checks across every run of the order, matched
    # by po_id OR by the order's runs (some checks only carry mo_id).
    order_checks = (
        session.query(models.ManualQualityCheck)
        .filter(models.ManualQualityCheck.voided_at.is_(None))
        .filter(
            (models.ManualQualityCheck.po_id == po_id)
            | (models.ManualQualityCheck.mo_id.in_(run_ids))
        )
        .order_by(models.ManualQualityCheck.id)
        .all()
    )
    order_check_dicts = manual_check_dicts(order_checks)
    merge_manual_parameters(stats["parameters"], manual_rods(order_check_dicts), specs)

    tri = compute_triacetin(session, run_ids=run_ids) if run_ids else {"measurements": [], "overall_pct": None}
    tri = merge_triacetin(tri, manual_triacetin_measurements(order_check_dicts))
    cert_rows = certificate_rows(stats, specs)
    inject_triacetin_certificate(cert_rows, specs, tri["overall_pct"])
    inject_triacetin_parameters(stats["parameters"], specs, tri["overall_pct"])

    per_run = []
    for run in runs:
        s = compute_run_summary(session, run)
        if not s["rods_total"]:
            continue
        shift = session.get(models.ShiftSession, run.shift_id)
        machine_id = run.machine_id or (shift.machine_id if shift else None)
        machine = session.get(models.Machine, machine_id) if machine_id else None
        s["seq"] = run.seq
        s["started_at"] = shift.started_at.isoformat() if shift and shift.started_at else None
        s["machine"] = machine.name if machine else None
        per_run.append(s)
    first = rods[0].measured_at.isoformat() if rods and rods[0].measured_at else None
    last = rods[-1].measured_at.isoformat() if rods and rods[-1].measured_at else None
    return {
        "po_id": po_id,
        "status": stats["status"],
        "rods_total": stats["rods_total"],
        "rods_rejected": stats["rods_rejected"],
        "rods_used": stats["rods_used"],
        "parameters": stats["parameters"],
        "automatic": auto_rows,
        "certificate": cert_rows,
        "runs": per_run,
        "first_measured_at": first,
        "last_measured_at": last,
        "remarks": manual_remarks(order_check_dicts),
        "manual_measurements": manual_measurements(stats["parameters"], order_check_dicts),
        "manual_checks": manual_table_rows(order_check_dicts),
        "triacetin": tri["measurements"],
        "triacetin_overall": tri["overall_pct"],
    }


def compute_order_production_summary(session: Session, po_id: int) -> Dict[str, Any]:
    """Cumulative production + material consumption across every shift/run of an order.

    Sums the operator-submitted production reports (boxes, rods, waste) and the
    per-material consumption totals (acetate / paper / cold glue (PVA) / hot melt /
    triacetin). Obsolete and soft-deleted reports are excluded, mirroring the PO
    counter logic.
    """
    po = session.get(models.PurchaseOrder, po_id)
    po_number = po.po_number if po else None

    reports = (
        session.query(models.ProductionReport)
        .filter(
            models.ProductionReport.po_number == po_number,
            models.ProductionReport.status != "obsolete",
            (models.ProductionReport.is_deleted.is_(False))
            | (models.ProductionReport.is_deleted.is_(None)),
        )
        .all()
    )

    def _sum_int(field):
        return sum(int(getattr(r, field) or 0) for r in reports)

    def _sum_float(field):
        return round(sum(float(getattr(r, field) or 0.0) for r in reports), 3)

    return {
        "po_id": po_id,
        "po_number": po_number,
        "report_count": len(reports),
        "total_boxes": _sum_int("boxes_produced"),
        "total_rods": _sum_int("produced_rods"),
        "total_waste_kg": _sum_float("waste_kg"),
        "materials": {
            "acetate": _sum_float("total_acetate"),
            "paper": _sum_float("total_paper"),
            "pva": _sum_float("total_pva"),
            "hm": _sum_float("total_hm"),
            "triacetin": _sum_float("total_triacetin"),
        },
    }


def fingerprint(*parts: object) -> str:
    """Deterministic fingerprint used to detect stale shift summaries."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(json.dumps(part, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()[:40]


def _f(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
