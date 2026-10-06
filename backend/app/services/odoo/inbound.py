"""Inbound Odoo -> MES: fetch open manufacturing orders and link them to local
production runs / purchase orders without touching existing production data."""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app import models
from app.services.odoo.client import OdooClient


def fetch_open_mos(client: OdooClient) -> List[Dict[str, Any]]:
    """Return active/confirmed Manufacturing Orders from Odoo."""
    return client.search_read(
        "mrp.production",
        [["state", "in", ["confirmed", "progress"]]],
        ["id", "name", "product_id", "product_uom_id", "product_qty",
         "qty_producing", "state", "origin"],
    )


def sync_open_mos(session: Session, client: OdooClient) -> Dict[str, int]:
    """Link local records to Odoo ids (additive only). Returns a small summary."""
    linked_runs = 0
    linked_pos = 0
    for mo in fetch_open_mos(client):
        mo_id = int(mo["id"])

        ref = str(mo.get("name") or "").strip()
        if ref:
            run = (
                session.query(models.ProductionRun)
                .filter(models.ProductionRun.mo_ref == ref)
                .first()
            )
            if run is not None and run.odoo_mo_id is None:
                run.odoo_mo_id = mo_id
                linked_runs += 1

        # Link the customer PO via the MO's origin (sale.order name).
        origin = str(mo.get("origin") or "").strip()
        if origin:
            po = (
                session.query(models.PurchaseOrder)
                .filter(models.PurchaseOrder.po_number == origin)
                .first()
            )
            if po is not None and po.odoo_id is None:
                sale = client.search_read(
                    "sale.order", [["name", "=", origin]], ["id"], limit=1
                )
                if sale:
                    po.odoo_id = int(sale[0]["id"])
                    linked_pos += 1

    session.commit()
    return {"linked_runs": linked_runs, "linked_pos": linked_pos}
