"""Telegram Quality section for a production report.

Mean PD / Mean Dia / SD PD / SD Dia over the ORDER's own time window in the
shift: [run.started_at, report submission]. With a single order in the shift
this equals the whole shift; with several orders each report only covers its
own samples (order 101 14:00-18:00, order 102 18:00-22:00). The SD rows carry
🟢/🟡/🔴 by the SD thresholds from quality_settings; means stay uncoloured.

SD is the sample standard deviation (n-1) per the factory methodology.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import models
from app.quality_stats import _num


def _mean_sd(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if not values:
        return None, None
    n = len(values)
    if n == 1:
        return values[0], None
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    return mean, math.sqrt(var)


def _fmt(v: Optional[float], decimals: int) -> str:
    return "—" if v is None else f"{v:.{decimals}f}"


def _sd_sign(sd: Optional[float], warn: float, fail: float) -> str:
    if sd is None:
        return ""
    if sd < warn:
        return " 🟢"
    if sd <= fail:
        return " 🟡"
    return " 🔴"


def _report_end_utc(report) -> datetime:
    sync_at = getattr(report, "sync_at", None)
    if sync_at is not None:
        if getattr(sync_at, "tzinfo", None) is None:
            return sync_at.replace(tzinfo=timezone.utc)
        return sync_at.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def quality_section_text(db: Session, report) -> Optional[str]:
    """The ``Quality:`` block for a report's Telegram message, or None.

    Needs a linked production run (report.run_id) so the order's time window is
    known; otherwise the section is omitted rather than guessed.
    """
    run_id = getattr(report, "run_id", None)
    if not run_id:
        return None
    run = db.get(models.ProductionRun, run_id)
    if run is None or run.started_at is None:
        return None
    machine = (
        db.query(models.Machine)
        .filter(models.Machine.name == getattr(report, "machine_name", None))
        .first()
    )
    if machine is None:
        return None

    order = (run.mo_ref or getattr(report, "mo_number", "") or "").strip()
    start = run.started_at
    end = _report_end_utc(report)
    if end <= start:
        return None

    q = db.query(models.QualityMeasurement).filter(
        models.QualityMeasurement.machine_id == machine.id,
        models.QualityMeasurement.measured_at >= start,
        models.QualityMeasurement.measured_at < end,
    )
    if order:
        labelled = (
            db.query(models.QualitySample.id)
            .filter(
                or_(
                    func.btrim(func.coalesce(models.QualitySample.sample_id, "")) == order,
                    func.btrim(func.coalesce(models.QualitySample.mo_ref, "")) == order,
                )
            )
        )
        q = q.filter(
            or_(
                models.QualityMeasurement.run_id == run.id,
                models.QualityMeasurement.sample_id.in_(labelled),
            )
        )
    else:
        q = q.filter(models.QualityMeasurement.run_id == run.id)

    rods = q.all()
    pd_vals = [v for v in (_num(r.pd) for r in rods) if v is not None]
    dia_vals = [v for v in (_num(r.diameter) for r in rods) if v is not None]
    if not pd_vals and not dia_vals:
        return None

    settings = db.query(models.QualitySettings).first()
    if settings is not None:
        pd_warn = _num(settings.pd_sd_warn) or 12.0
        pd_fail = _num(settings.pd_sd_fail) or 15.0
        dia_warn = _num(settings.dia_sd_warn) or 0.013
        dia_fail = _num(settings.dia_sd_fail) or 0.015
    else:
        pd_warn, pd_fail = 12.0, 15.0
        dia_warn, dia_fail = 0.013, 0.015

    mean_pd, sd_pd = _mean_sd(pd_vals)
    mean_dia, sd_dia = _mean_sd(dia_vals)

    return "\n".join([
        "Quality:",
        f"Mean PD: {_fmt(mean_pd, 2)}",
        f"Mean Dia: {_fmt(mean_dia, 4)}",
        f"SD PD: {_fmt(sd_pd, 2)}{_sd_sign(sd_pd, pd_warn, pd_fail)}",
        f"SD Dia: {_fmt(sd_dia, 4)}{_sd_sign(sd_dia, dia_warn, dia_fail)}",
    ])
