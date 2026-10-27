"""One-off backfill: resolve quality specs for Odoo-linked orders using the
3-level fallback and re-dispatch the blocked Odoo outbox queue.

Fixes the Odoo backorder-loses-its-target/tolerance defect:
  1. Resolve specs per linked order: MO (L1) -> product (L2) -> global (L3).
  2. Upsert the resolved specs into ``quality_specs`` (scope=po) for orders that
     have none yet (never overwrites existing specs).
  3. Self-heal the Odoo backorder MOs: write the product x_qc_* defaults onto
     any chain MO whose fields are zero (so the Odoo UI no longer shows zeros).
  4. Requeue ``failed`` outbox items (shift-dispatch manual_checks crash fixed).
  5. Re-write QC (link-only, no completion) to already-completed MOs of the
     orders that were missing specs (their QC fields were left empty).

Run:
    cd backend
    python -m app.scripts.backfill_odoo_specs [--dry-run]
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from app.config import load_env
from app.database import SessionLocal
from app import models
from app.services import aggregation
from app.services.odoo.client import OdooClient, OdooConfig, OdooError, _id_ref
from app.services.odoo import inbound, outbound


def _resolve_spec(db, client, po):
    """Resolve a clean spec dict for a linked PO (MO -> product -> global)."""
    mo_id = po.odoo_mo_id
    product_id = None
    spec = {}
    if client is not None and mo_id:
        try:
            recs = client.read("mrp.production", [mo_id], ["product_id"])
            product_id = recs[0].get("product_id") if recs else None
            spec, _ = client.resolve_mo_product_spec(mo_id, product_id)
        except OdooError as exc:
            print(f"  [warn] spec read failed for PO {po.po_number}: {exc}")
    return inbound._fill_global_fallback(db, spec, po), product_id


def _chain_mo_ids(client, root_mo_id):
    """Return [(mo_id, product_id)] for every MO of the backorder chain."""
    if client is None or not root_mo_id:
        return []
    try:
        recs = client.read("mrp.production", [root_mo_id], ["procurement_group_id"])
        gid = _id_ref(recs[0].get("procurement_group_id")) if recs else None
        if gid:
            chain = client.search_read(
                "mrp.production", [["procurement_group_id", "=", gid]],
                ["id", "product_id"],
            )
            return [(int(m["id"]), m.get("product_id")) for m in chain]
    except OdooError as exc:
        print(f"  [warn] chain read failed: {exc}")
    return [(int(root_mo_id), None)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env()
    cfg = OdooConfig.from_env()
    client = None
    if cfg.enabled and cfg.valid():
        client = OdooClient(cfg)
        try:
            client.connect()
            print(f"[backfill] Odoo connected: {cfg.url} db={cfg.db}")
        except OdooError as exc:
            print(f"[backfill] Odoo unreachable: {exc}")
            client = None
    else:
        print("[backfill] Odoo not configured; spec fallback limited to MES globals")

    db = SessionLocal()
    try:
        linked = (
            db.query(models.PurchaseOrder)
            .filter(models.PurchaseOrder.odoo_mo_id.isnot(None))
            .order_by(models.PurchaseOrder.id)
            .all()
        )
        print(f"[backfill] {len(linked)} Odoo-linked orders")

        specs_orders = 0
        healed = 0
        backfilled = set()
        for po in linked:
            existing = (
                db.query(models.QualitySpec)
                .filter(models.QualitySpec.scope == "po", models.QualitySpec.po_id == po.id)
                .count()
            )
            spec, product_id = _resolve_spec(db, client, po)
            present = {k: v for k, v in spec.items() if v not in (None, 0.0)}
            print(f"  PO {po.po_number} (id={po.id}, root_mo={po.odoo_mo_id}, had_specs={existing}) -> {present}")
            if not existing and present:
                backfilled.add(po.id)
                if not args.dry_run:
                    inbound._upsert_po_specs(db, po, spec)
                    specs_orders += 1
            for mo_id, pid in _chain_mo_ids(client, po.odoo_mo_id):
                if args.dry_run:
                    continue
                try:
                    res = client.fill_mo_spec_from_product(mo_id, pid or product_id)
                    if res.get("written"):
                        healed += 1
                except OdooError as exc:
                    print(f"    [warn] self-heal MO {mo_id}: {exc}")

        failed = (
            db.query(models.OdooOutbox)
            .filter(models.OdooOutbox.status == "failed")
            .order_by(models.OdooOutbox.id)
            .all()
        )
        print(f"[backfill] requeue {len(failed)} failed outbox items")
        for item in failed:
            print(f"  outbox {item.id} ({item.aggregate_type} {item.aggregate_id}) {item.idempotency_key}")
            if not args.dry_run:
                item.status = "pending"
                item.last_error = None
                item.next_attempt_at = None
                item.attempts = 0

        qc_rerun = 0
        for po_id in backfilled:
            runs = (
                db.query(models.ProductionRun)
                .filter(
                    models.ProductionRun.po_id == po_id,
                    models.ProductionRun.odoo_mo_id.isnot(None),
                )
                .all()
            )
            for run in runs:
                summary = aggregation.compute_run_summary(db, run)
                params = summary.get("parameters") or {}
                if not params or not summary.get("rods_total"):
                    continue
                print(f"  [qc] run {run.id} ({run.mo_ref}) -> MO {run.odoo_mo_id} params={list(params)}")
                if args.dry_run or client is None:
                    continue
                try:
                    outbound._dispatch_run(
                        db, client, run, summary, int(run.odoo_mo_id), link_only=True
                    )
                    db.commit()
                    qc_rerun += 1
                except Exception as exc:
                    db.rollback()
                    print(f"    [warn] QC re-dispatch run {run.id}: {exc}")

        if not args.dry_run:
            db.commit()
        print(
            f"[backfill] done. specs_orders={specs_orders} healed_mos={healed} "
            f"failed_requeued={len(failed)} qc_rerun={qc_rerun} dry_run={args.dry_run}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
