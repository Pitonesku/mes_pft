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


def _summary_reports(session: Session, po: models.PurchaseOrder) -> list:
    """Return the non-obsolete reports of an order (used by the audit summary PDF)."""
    return (
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


def summary_pdf_bytes(session: Session, po: models.PurchaseOrder) -> Optional[bytes]:
    """Return the consolidated Order Summary PDF bytes.

    Prefer the Flutter-generated PDF uploaded by the client (the primary source of
    truth); fall back to the ReportLab render only when none has been uploaded yet
    (backend-initiated finalize with no client in the loop). Returns ``None`` when
    neither is available.
    """
    if po.order_summary_pdf_base64:
        try:
            import base64

            return base64.b64decode(po.order_summary_pdf_base64)
        except Exception as exc:  # noqa: BLE001 - invalid payload falls through
            logger.warning("Invalid Flutter order-summary PDF for order %s: %s", po.id, exc)
    try:
        from app.pdf_generator import render_order_summary_pdf

        reports = _summary_reports(session, po)
        quality = po.final_quality or {}
        return render_order_summary_pdf(po, reports, quality)
    except Exception as exc:  # noqa: BLE001 - never break finalize over the PDF
        logger.warning("Order summary PDF render failed for %s: %s", po.id, exc)
        return None


def push_order_summary(
    session: Session,
    po: models.PurchaseOrder,
    quality: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach the consolidated Order Summary PDF to Odoo (root + backorder MO).

    Idempotent against duplicate chatter attachments (``attach_file`` replaces by
    name + record), so a late Flutter upload can re-push and replace an earlier
    ReportLab render. Returns a status dict and never raises.
    """
    result: Dict[str, Any] = {"odoo_attached": False}
    if not po.odoo_mo_id:
        return result
    pdf_bytes = summary_pdf_bytes(session, po)
    if not pdf_bytes:
        result["odoo_error"] = "no summary PDF available"
        return result
    quality = quality or po.final_quality or {}
    try:
        from app.services.odoo.client import OdooClient, OdooConfig

        cfg = OdooConfig.from_env()
        if not (cfg.enabled and cfg.valid()):
            result["odoo_error"] = "Odoo not configured"
            return result
        client = OdooClient(cfg)
        client.connect()
        filename = po.order_summary_pdf_filename or (
            f"Order_Summary_{_safe_name(po.po_number)}.pdf")
        root_id = int(po.odoo_mo_id)
        backorder_id = int(po.odoo_current_mo_id) if po.odoo_current_mo_id else None
        # attach_file REPLACES by name+record, so re-pushing never stacks
        # duplicate chatter attachments.
        att_id = client.attach_file(
            filename, "mrp.production", root_id, pdf_bytes, "application/pdf")
        backorder_att_id = None
        if backorder_id and backorder_id != root_id:
            backorder_att_id = client.attach_file(
                filename, "mrp.production", backorder_id, pdf_bytes, "application/pdf")
        client.write_final_quality(root_id, quality)
        po.odoo_summary_attachment_id = att_id
        session.commit()
        result["odoo_attached"] = True
        result["odoo_attachment_id"] = att_id
        result["odoo_backorder_attachment_id"] = backorder_att_id
    except Exception as exc:  # noqa: BLE001 - never raise over Odoo
        logger.warning("Odoo summary push failed for order %s: %s", po.id, exc)
        result["odoo_error"] = str(exc)
    return result


def finalize_order(
    session: Session,
    po: models.PurchaseOrder,
    actor: str,
    push_odoo: bool = True,
) -> Dict[str, Any]:
    """Compute + persist the final rollup; render + (optionally) push the Summary PDF.

    ``push_odoo`` gates the Odoo attachment and the ``x_final_*`` root-MO write; it
    is ``True`` for any linked order (regardless of ``sync_mode``). The snapshot and
    ``completion_status`` are written regardless, so an unlinked order is still
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

    # Render the summary PDF (the Flutter-generated one when the client uploaded
    # it; ReportLab only as a fallback). Always populated so the web console and
    # the Odoo print endpoint can expose it.
    pdf_bytes = summary_pdf_bytes(session, po)
    result["pdf_bytes_len"] = len(pdf_bytes) if pdf_bytes else 0
    result["pdf_source"] = "flutter" if po.order_summary_pdf_base64 else "reportlab"

    # Push to Odoo whenever the order is linked, regardless of sync_mode.
    if push_odoo and po.odoo_mo_id and pdf_bytes:
        result.update(push_order_summary(session, po, quality=quality))

    return result


def maybe_auto_finalize(session: Session, po: models.PurchaseOrder, actor: str) -> bool:
    """Finalize an order once its cumulative production reaches the target.

    Called after a report is approved. Generates the consolidated Order Summary
    PDF and - for linked orders (regardless of sync_mode) - attaches it to the Odoo
    **root MO** (``po.odoo_mo_id``) and the latest backorder MO so the full
    production history lives on the main order.

    Idempotent: no-ops when the order is already completed or the target is not
    yet reached. Returns True when a finalize ran.
    """
    if po is None or po.completion_status == COMPLETED or not po.target_qty:
        return False
    production = aggregation.compute_order_production_summary(session, po.id)
    if (production.get("total_rods") or 0) < po.target_qty:
        return False
    finalize_order(
        session, po, actor=actor,
        push_odoo=(po.odoo_mo_id is not None),
    )
    return True
