"""
Push QUALITY ONLY for legacy (link_only) orders to Odoo.

For each linked order whose Odoo chain is already done, every shift report is matched
to its backorder MO by exact rod quantity, then quality fields + the quality
certificate PDF + the raw measurements CSV are written/attached on that MO.
Stock, consumption and MO state are never touched.

    cd backend
    python -m app.scripts.push_legacy_quality --po G080            # dry run (default)
    python -m app.scripts.push_legacy_quality --po G080 --apply
    python -m app.scripts.push_legacy_quality --all --apply
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from app import models
from app.database import SessionLocal
from app.scripts.assign_runs import build_shift_windows
from app.services.odoo import legacy_push
from app.services.odoo.client import OdooClient, OdooConfig


def main():
    ap = argparse.ArgumentParser(description="Push legacy quality data to Odoo (quality only)")
    ap.add_argument("--po", default=None, help="one PO number, e.g. G080")
    ap.add_argument("--all", action="store_true", help="every linked link_only order")
    ap.add_argument("--apply", action="store_true", help="write to Odoo (default: dry run)")
    args = ap.parse_args()
    if not args.po and not args.all:
        ap.error("pass --po <number> or --all")

    cfg = OdooConfig.from_env()
    if not (cfg.enabled and cfg.valid()):
        sys.exit("Odoo is not configured")
    client = OdooClient(cfg)
    client.connect()

    session = SessionLocal()
    try:
        q = session.query(models.PurchaseOrder).filter(
            models.PurchaseOrder.odoo_mo_id.isnot(None),
            models.PurchaseOrder.sync_mode == "link_only",
        )
        if args.po:
            q = q.filter(models.PurchaseOrder.po_number == args.po)
        orders = q.order_by(models.PurchaseOrder.po_number).all()
        windows = build_shift_windows(session)
        print(f"orders: {len(orders)}  mode: {'APPLY' if args.apply else 'DRY RUN'}")
        for po in orders:
            out = legacy_push.run_order(session, client, po, windows, dry_run=not args.apply)
            if "error" in out:
                print(f"{po.po_number}: ERROR {out['error']}")
                continue
            ok = [r for r in out["results"] if "skipped" not in r]
            print(f"{po.po_number}: pushed={len(ok)} skipped={len(out['results']) - len(ok)} "
                  f"ambiguous={len(out['ambiguous'])} unmatched_reports={out['unmatched_reports']} "
                  f"unmatched_mos={out['unmatched_mos']}")
            for r in out["results"]:
                if "skipped" in r:
                    print(f"   SKIP {r.get('mo')}: {r['skipped']}")
                else:
                    v = r["values"]
                    print(f"   {r['mo']:<18} report#{r['report']} lot={r['lot']} rods={r['rods']} "
                          f"status={r['status']} meanPD={v.get('mean_pd')} "
                          f"meanDia={v.get('mean_diameter')} files={r['attachments']}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
