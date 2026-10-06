"""
One-off backfill: link shift-linked quality samples to production runs.

The ETL linked samples to shifts (by timestamp) but left run_id NULL because the
station data carries no MO reference. This script applies the timestamp fallback:
each sample is attached to the run active at its produced_at within its shift.

Batched: updates are grouped by run_id (IN-clause) to avoid per-row round-trips.

Run AFTER the ETL:
    cd backend
    .venv/Scripts/python.exe -m app.scripts.relink_runs
"""

import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal


def _pick_run_id(candidates, produced_at):
    if produced_at is None:
        return None
    best = None
    for run in candidates:
        if run.started_at is not None and produced_at < run.started_at:
            continue
        if run.ended_at is not None and produced_at >= run.ended_at:
            continue
        best = run
    return best.id if best is not None else None


def main():
    session: Session = SessionLocal()
    try:
        runs_by_shift: dict = defaultdict(list)
        for run in session.query(models.ProductionRun).order_by(models.ProductionRun.seq).all():
            runs_by_shift[run.shift_id].append(run)

        samples = (
            session.query(
                models.QualitySample.id,
                models.QualitySample.shift_id,
                models.QualitySample.produced_at,
            )
            .filter(
                models.QualitySample.shift_id.isnot(None),
                models.QualitySample.run_id.is_(None),
            )
            .all()
        )
        print(f"samples with shift but no run: {len(samples)}")

        run_to_sample_ids: dict = defaultdict(list)
        for sid, shift_id, produced_at in samples:
            run_id = _pick_run_id(runs_by_shift.get(shift_id, []), produced_at)
            if run_id is not None:
                run_to_sample_ids[run_id].append(sid)

        total = sum(len(ids) for ids in run_to_sample_ids.values())
        print(f"samples to link: {total} across {len(run_to_sample_ids)} runs")

        updated_samples = 0
        updated_meas = 0
        for run_id, sample_ids in run_to_sample_ids.items():
            updated_samples += (
                session.query(models.QualitySample)
                .filter(models.QualitySample.id.in_(sample_ids))
                .update({"run_id": run_id, "link_status": "LINKED"}, synchronize_session=False)
            )
            updated_meas += (
                session.query(models.QualityMeasurement)
                .filter(models.QualityMeasurement.sample_id.in_(sample_ids))
                .update({"run_id": run_id}, synchronize_session=False)
            )

        session.commit()
        print(f"updated samples: {updated_samples}")
        print(f"updated measurements: {updated_meas}")

        runs_with_rods = (
            session.query(models.ProductionRun.id)
            .join(models.QualityMeasurement, models.QualityMeasurement.run_id == models.ProductionRun.id)
            .distinct()
            .count()
        )
        print(f"runs now having rods: {runs_with_rods}")
    finally:
        session.close()


if __name__ == "__main__":
    main()