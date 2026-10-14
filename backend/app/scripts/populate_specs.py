"""
One-off: populate quality_specs from purchase_orders with default tolerances.

The production dump has PO nominals (diameter, pd) but no tolerance limits.
We apply the E050/H087 certificate tolerances as defaults and reset the
(incorrectly-formatted) run.spec_snapshot so aggregation.load_run_specs falls
through to the quality_specs table.

Run AFTER the ETL + relink:
    cd backend
    .venv/Scripts/python.exe -m app.scripts.populate_specs
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal


def _specs_for_po(po):
    specs = []
    if po.diameter:
        specs.append(dict(
            scope="po", po_id=po.id, parameter="diameter",
            nominal=float(po.diameter),
            lower_limit=float(po.diameter) - 0.03,
            upper_limit=float(po.diameter) + 0.03,
            reject_multiplier=3, rod_count=100,
            report_unit="mm", report_scale=1, decimals=3,
        ))
    if po.pd:
        specs.append(dict(
            scope="po", po_id=po.id, parameter="pd",
            nominal=float(po.pd),
            lower_limit=float(po.pd) - 15,
            upper_limit=float(po.pd) + 25,
            reject_multiplier=3, rod_count=100,
            report_unit="mm WG", report_scale=1, decimals=1,
        ))
    # NOTE: no weight spec — the PO `weight` column is in an unknown unit
    # (478..574) while the station measures g/rod (~0.37..0.66), so a weight
    # nominal cannot be derived reliably. Weight can be added back once the
    # correct per-product weight limits are known.
    return specs


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Populate quality_specs from purchase_orders")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be created/reset without writing anything")
    args = ap.parse_args()

    session: Session = SessionLocal()
    try:
        pos = session.query(models.PurchaseOrder).all()
        created = 0
        would_create: list = []
        for po in pos:
            for spec in _specs_for_po(po):
                existing = (
                    session.query(models.QualitySpec)
                    .filter_by(po_id=po.id, parameter=spec["parameter"])
                    .first()
                )
                if existing is None:
                    would_create.append((po.po_number, spec["parameter"], spec["nominal"]))
                    if not args.dry_run:
                        session.add(models.QualitySpec(**spec))
                    created += 1
        reset = session.query(models.ProductionRun).update(
            {"spec_snapshot": {}}, synchronize_session=False
        )
        if args.dry_run:
            session.rollback()
            print(f"[dry-run] would create quality_specs: {created}")
            print(f"[dry-run] would reset spec_snapshot on runs: {reset}")
            for row in would_create:
                print(f"  {row[0]:<24} {row[1]:<10} {row[2]}")
        else:
            session.commit()
            print(f"created quality_specs: {created}")
            print(f"runs with spec_snapshot reset: {reset}")
        total = session.query(models.QualitySpec).count()
        print(f"total quality_specs: {total}")
    finally:
        session.close()


if __name__ == "__main__":
    main()