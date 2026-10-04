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
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app import models
from app.quality_stats import ParamSpec, certificate_rows, compute_run_stats


def build_param_specs(specs: Iterable[models.QualitySpec]) -> Dict[str, ParamSpec]:
    """Convert QualitySpec rows into quality_stats.ParamSpec objects."""
    result: Dict[str, ParamSpec] = {}
    for s in specs:
        result[s.parameter] = ParamSpec(
            parameter=s.parameter,
            nominal=_f(s.nominal),
            lower=_f(s.lower_limit),
            upper=_f(s.upper_limit),
            reject_multiplier=_f(s.reject_multiplier),
            report_unit=s.report_unit or "",
            report_scale=_f(s.report_scale) or 1.0,
            decimals=int(s.decimals or 3),
        )
    return result


def load_run_specs(session: Session, run: models.ProductionRun) -> Dict[str, ParamSpec]:
    """Resolve the frozen spec snapshot for a run; fall back to quality_specs rows."""
    snapshot = run.spec_snapshot or {}
    if snapshot:
        specs = [
            models.QualitySpec(**row) if isinstance(row, dict) else row
            for row in snapshot.get("parameters", [])
        ]
        return build_param_specs([s for s in specs if isinstance(s, models.QualitySpec)])
    rows = session.query(models.QualitySpec).filter(
        models.QualitySpec.po_id == run.po_id
    ).all()
    return build_param_specs(rows)


def load_rods(session: Session, run_id: int) -> List[Dict[str, Optional[float]]]:
    """Return the run's rods as the dict shape quality_stats expects, in order."""
    rods = (
        session.query(models.QualityMeasurement)
        .filter(models.QualityMeasurement.run_id == run_id)
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


def compute_run_summary(
    session: Session,
    run: models.ProductionRun,
    manual: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
    sd_kind: str = "samp",
) -> Dict:
    """Compute stats + certificate rows for one run."""
    specs = load_run_specs(session, run)
    rods = load_rods(session, run.id)
    stats = compute_run_stats(rods, specs)
    rows = certificate_rows(stats, specs, manual=manual, sd_kind=sd_kind)
    return {
        "run_id": run.id,
        "mo_ref": run.mo_ref,
        "status": stats["status"],
        "rods_total": stats["rods_total"],
        "rods_rejected": stats["rods_rejected"],
        "rods_used": stats["rods_used"],
        "parameters": stats["parameters"],
        "certificate": rows,
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
