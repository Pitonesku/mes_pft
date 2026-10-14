"""Order finalization.

Computes the cumulative production + consolidated quality for an order, persists
immutable snapshots on ``purchase_orders``, marks it ``completed``, renders the
Summary PDF and (when ``push_odoo``) attaches it to the root MO and writes the
``x_final_*`` consolidated quality fields.

Pure orchestration over ``aggregation`` / ``pdf_generator`` / the Odoo client; it
owns no HTTP concerns so both the admin endpoint and the Odoo reconcile hook can
call it.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app import models
from app.services import aggregation

logger = logging.getLogger(__name__)

COMPLETED = "completed"
ACTIVE = "active"
CANCELLED = "cancelled"


def _safe_name(value: Optional[str]) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value or "MO")


def _spec_string(po: models.PurchaseOrder) -> Optional[str]:
    parts = []
    if po.diameter and po.length:
        parts.append(f"{po.diameter}*{po.length}")
    if po.pd:
        parts.append(f"PD {po.pd}")
    if po.cu is not None:
        parts.append(f"CU {po.cu}")
    return " ".join(parts) or None


def _summary_pdf_data(
    session: Session, po: models.PurchaseOrder, production: Dict, quality: Dict
) -> Dict[str, Any]:
    """Assemble the data dict consumed by ``render_order_summary_pdf``."""
    reports = (
        session.query(models.ProductionReport)
        .filter(
            models.ProductionReport.po_number == po.po_number,
            models.ProductionReport.status != "obsolete",
            (models.ProductionReport.is_deleted.is_(False))
            | (models.ProductionReport.is_deleted.is_(None)),
        )
        .order_by(models.ProductionReport.report_date)
        .all()
    )
    machines = ", ".join(sorted({r.machine_name for r in reports if r.machine_name})) or None
    operators = ", ".join(sorted({r.operator_name for r in reports if r.operator_name})) or None
    dates = [r.report_date for r in reports if r.report_date]
    date_range = None
    if dates:
        date_range = f"{min(dates)} – {max(dates)}" if len(dates) > 1 else dates[0]

    return {
        "header": {
            "mo_number": po.po_number,
            "spec_string": _spec_string(po),
            "machines": machines,
            "date_range": date_range,
            "operator": operators,
        },
        "production": production,
        "quality": {
            "certificate": quality.get("certificate") or [],
            "rods_total": quality.get("rods_total"),
            "rods_rejected": quality.get("rods_rejected"),
            "status": quality.get("status"),
        },
    }


def finalize_order(
    session: Session,
    po: models.PurchaseOrder,
    actor: str,
    push_odoo: bool = True,
) -> Dict[str, Any]:
    """Compute + persist the final rollup; render + (optionally) push the Summary PDF.

    ``push_odoo`` should be ``True`` only for ``sync_mode == 'full'`` orders: it
    gates the Odoo attachment and the ``x_final_*`` root-MO write. The snapshot and
    ``completion_status`` are written regardless, so a ``link_only`` order is still
    finalized locally.
    """
    production = aggregation.compute_order_production_summary(session, po.id)
    quality = aggregation.compute_order_summary(session, po.id)

    final_quality = {
        "status": quality["status"],
        "rods_total": quality["rods_total"],
        "rods_rejected": quality["rods_rejected"],
        "rods_used": quality["rods_used"],
        "certificate": quality["certificate"],
        "first_measured_at": quality.get("first_measured_at"),
        "last_measured_at": quality.get("last_measured_at"),
    }

    po.final_boxes = production["total_boxes"]
    po.final_rods = production["total_rods"]
    po.final_waste_kg = production["total_waste_kg"]
    po.final_materials = production["materials"]
    po.final_quality = final_quality
    po.completion_status = COMPLETED
    po.completed_at = datetime.now(timezone.utc)
    po.completed_by = actor
    # Hide from the tablet MO dropdown (reuses the existing operator-facing filter).
    po.is_hidden = True
    session.commit()

    result: Dict[str, Any] = {
        "po_id": po.id,
        "po_number": po.po_number,
        "completion_status": po.completion_status,
        "production": production,
        "quality": final_quality,
        "odoo_attached": False,
    }

    # Render the summary PDF always (the web console can expose it directly).
    try:
        from app.pdf_generator import render_order_summary_pdf
        pdf_bytes = render_order_summary_pdf(_summary_pdf_data(session, po, production, quality))
        result["pdf_bytes_len"] = len(pdf_bytes) if pdf_bytes else 0
    except Exception as exc:  # noqa: BLE001 - never break finalize over the PDF
        logger.warning("Order summary PDF render failed for %s: %s", po.id, exc)
        result["pdf_error"] = str(exc)
        pdf_bytes = None

    # Push to Odoo (attach + x_final_*) only for full-sync linked orders.
    if push_odoo and po.odoo_mo_id and pdf_bytes:
        try:
            from app.services.odoo.client import OdooClient, OdooConfig
            cfg = OdooConfig.from_env()
            if cfg.enabled and cfg.valid():
                client = OdooClient(cfg)
                client.connect()
                filename = f"Order_Summary_{_safe_name(po.po_number)}.pdf"
                att_id = client.attach_pdf(
                    filename, "mrp.production", int(po.odoo_mo_id), pdf_bytes)
                client.write_final_quality(int(po.odoo_mo_id), quality)
                po.odoo_summary_attachment_id = att_id
                session.commit()
                result["odoo_attached"] = True
                result["odoo_attachment_id"] = att_id
        except Exception as exc:  # noqa: BLE001 - finalize must not fail on Odoo
            logger.warning("Odoo summary push failed for order %s: %s", po.id, exc)
            result["odoo_error"] = str(exc)

    return result
