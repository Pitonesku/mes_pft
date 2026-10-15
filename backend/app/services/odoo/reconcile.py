"""Odoo -> MES reconciliation (Phase 2).

Safety net for the webhook: periodically re-reads the Odoo MO chain of every linked,
not-finished order and updates the MES view (state, current open MO, quantity drift).

Never deletes or overwrites production data (invariant #2). A cancelled / finished
chain only changes ``odoo_state``; orders are not hidden or archived automatically,
and a cancelled chain downgrades ``sync_mode`` to ``link_only`` so nothing can be
posted to a dead MO.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.services.odoo.client import OdooClient, OdooError, _id_ref

logger = logging.getLogger(__name__)

TRACKED_STATES = (None, "open", "check")


def reconcile_order(client: OdooClient, po: models.PurchaseOrder) -> Dict[str, Any]:
    """Refresh one linked order from Odoo. Returns a small change report."""
    start = po.odoo_current_mo_id or po.odoo_mo_id
    if start is None:
        return {"po_id": po.id, "skipped": "not linked"}

    was_full = po.sync_mode == "full"
    before = (po.odoo_state, po.odoo_current_mo_id, po.sync_mode)
    status = client.chain_status(int(start))
    state = status["state"]

    # Current MO may itself be gone/done while the chain continues: re-resolve from root.
    if state == "missing" and po.odoo_mo_id and po.odoo_mo_id != start:
        status = client.chain_status(int(po.odoo_mo_id))
        state = status["state"]

    notes: List[str] = []
    if state == "missing":
        # Do not trust a single failed lookup to unlink anything: flag for review.
        po.odoo_state = "missing"
        notes.append("MO not found in Odoo (deleted or no access)")
    else:
        po.odoo_state = state
        if status.get("open_mo_id"):
            po.odoo_current_mo_id = int(status["open_mo_id"])
        total = status.get("total_qty")
        if total is not None and po.target_qty is not None:
            drift = float(total) - float(po.target_qty)
            po.odoo_qty_drift = drift if abs(drift) > 1e-9 else 0
        if state in ("cancel", "done") and po.sync_mode == "full":
            po.sync_mode = "link_only"
            notes.append(f"chain {state}: sync_mode -> link_only")
    po.odoo_synced_at = datetime.now(timezone.utc)

    after = (po.odoo_state, po.odoo_current_mo_id, po.sync_mode)
    return {
        "po_id": po.id,
        "po_number": po.po_number,
        "state": po.odoo_state,
        "changed": before != after,
        "notes": notes,
        "was_full": was_full,
    }


def reconcile_all(
    session: Session,
    client: OdooClient,
    limit: int = 200,
) -> Dict[str, Any]:
    """Reconcile every linked order that is not known to be finished/cancelled."""
    orders = (
        session.query(models.PurchaseOrder)
        .filter(
            models.PurchaseOrder.odoo_mo_id.isnot(None),
            (models.PurchaseOrder.odoo_state.is_(None))
            | (models.PurchaseOrder.odoo_state.in_(["open", "check", "missing"])),
        )
        .order_by(models.PurchaseOrder.odoo_synced_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )
    changed: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for po in orders:
        try:
            report = reconcile_order(client, po)
            if report.get("changed") or report.get("notes"):
                changed.append(report)
            # Auto-finalize: the Odoo chain is fully done -> compute + snapshot +
            # (optionally) push the summary. Idempotent: only runs once.
            if report.get("state") == "done" and po.completion_status != "completed":
                try:
                    from app.services import order_finalize
                    order_finalize.finalize_order(
                        session, po, actor="odoo",
                        push_odoo=(po.odoo_mo_id is not None))
                    changed.append({"po_id": po.id, "finalized": True, "state": "done"})
                except Exception as exc:  # noqa: BLE001 - finalize must not break reconcile
                    logger.warning("order finalize failed for %s: %s", po.id, exc)
        except Exception as exc:  # noqa: BLE001 - one bad order must not stop the rest
            logger.warning("reconcile failed for order %s: %s", po.id, exc)
            errors.append({"po_id": po.id, "error": str(exc)})
    session.commit()
    return {"checked": len(orders), "changed": changed, "errors": errors}


# --- Legacy order matching (one-time cleanup) ----------------------------------

_CODE_FIELDS = ("origin", "x_production_order_no", "name")
_CODE_LABELS = {"origin": "code:source", "x_production_order_no": "code:production_order_no", "name": "code:mo_number"}
HEURISTIC_DAYS = 14

_SPEC_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*[*x\-]\s*(\d+)\s+PD\s*(\d+)", re.IGNORECASE)
_CU_RE = re.compile(r"\b(\d+)\s*Cu\b", re.IGNORECASE)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _day(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _parse_spec(product_name: str) -> Optional[Dict[str, float]]:
    m = _SPEC_RE.search(product_name or "")
    if not m:
        return None
    cu = _CU_RE.search(product_name or "")
    return {
        "diameter": float(m.group(1).replace(",", ".")),
        "length": float(m.group(2)),
        "pd": float(m.group(3)),
        "cu": int(cu.group(1)) if cu else None,
    }


# Fields read from mrp.production when grouping chains. Odoo 18: the UoM field
# is ``product_uom_id`` (``product_uom`` does not exist and fails the whole read).
MO_CHAIN_FIELDS = ["id", "name", "origin", "x_production_order_no", "state", "product_id",
                   "product_qty", "product_uom_id", "backorder_sequence", "procurement_group_id",
                   "date_start", "date_finished", "date_deadline"]


def _chain_rows(client: OdooClient) -> Dict[int, Dict[str, Any]]:
    """Fetch all MOs and group them into backorder chains (procurement group)."""
    fields = list(MO_CHAIN_FIELDS)
    mos = None
    for attempt in range(2):
        try:
            mos = client.search_read("mrp.production", [], fields, limit=10000)
            break
        except OdooError as exc:
            m = re.search(r"Invalid field '([^']+)'", str(exc))
            if m and m.group(1) in fields and len(fields) > 1:
                # stock_cmr_packing / custom fields vary per instance: drop and retry.
                fields = [f for f in fields if f != m.group(1)]
                continue
            raise
    assert mos is not None
    # Batch-resolve UoM ratios ONCE per request: 544 MOs previously caused 544
    # sequential uom.uom reads (~21 s); this makes it a single call.
    uom_ids = {_id_ref(m.get("product_uom_id")) for m in mos if _id_ref(m.get("product_uom_id"))}
    ratios = client.fetch_uom_ratios(uom_ids) if uom_ids else {}

    chains: Dict[int, List[Dict[str, Any]]] = {}
    for mo in mos:
        group = _id_ref(mo.get("procurement_group_id")) or mo["id"]
        chains.setdefault(int(group), []).append(mo)

    rows: Dict[int, Dict[str, Any]] = {}
    for group, members in chains.items():
        root = min(members, key=lambda m: (int(m.get("backorder_sequence") or 0), m["id"]))
        days = [_day(m.get(f)) for m in members for f in ("date_start", "date_finished", "date_deadline")]
        days = [d for d in days if d is not None]
        states = sorted({str(m.get("state") or "") for m in members})
        if any(s in ("confirmed", "progress", "to_close") for s in states):
            state = "open"
        elif any(s == "done" for s in states):
            state = "done"
        elif all(s == "cancel" for s in states):
            state = "cancel"
        else:
            state = "draft"
        total_rods = sum(
            float(m.get("product_qty") or 0.0) * ratios.get(_id_ref(m.get("product_uom_id")), 1.0)
            for m in members
            if m.get("state") != "cancel"
        )
        rows[group] = {
            "root_id": int(root["id"]),
            "root_name": str(root.get("name") or ""),
            "mo_count": len(members),
            "state": state,
            "start": min(days) if days else None,
            "end": max(days) if days else None,
            "total_rods": total_rods,
            "spec": _parse_spec(str((root.get("product_id") or [0, ""])[1])),
            "keys": {
                f: _norm(m.get(f))
                for m in members
                for f in _CODE_FIELDS
                if m.get(f)
            },
            "open_mo_id": next(
                (m["id"] for m in members if m.get("state") in ("confirmed", "progress", "to_close")), None
            ),
        }
    return rows


def rank_chains(chains: Dict[int, Dict[str, Any]], q: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Filter chains by a search string and rank exact code matches first.

    An exact match (the query equals the MO name or one of the code fields such as
    Source / Production Order No.) is always listed before partial matches, and the
    limit is applied AFTER ranking so an exact hit can never be cut off by it.
    """
    needle = _norm(q)
    scored: List[Any] = []
    for chain in chains.values():
        name = _norm(chain.get("root_name"))
        keys = [str(v) for v in (chain.get("keys") or {}).values()]
        exact = False
        if needle:
            if needle not in " ".join([name] + keys):
                continue
            exact = needle == name or needle in keys
        scored.append((0 if exact else 1, str(chain.get("root_name") or ""), chain))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [c for _, _, c in scored[:limit]]


def suggest_unlinked_orders(
    session: Session,
    client: OdooClient,
    limit: int = 500,
) -> Dict[str, Any]:
    """Propose Odoo MO chains for orders that have no link yet (read-only).

    Matching order (never auto-selected by MES):
      1. exact code match on Source (origin), Production Order No. or MO name;
      2. heuristic: same rod spec AND a production window within +-14 days.

    Every candidate carries ``matched_on`` and a ``risk`` label; orders that only
    get heuristic candidates are returned as ``unmatched`` (need human decision).
    """
    orders = (
        session.query(models.PurchaseOrder)
        .filter(
            models.PurchaseOrder.odoo_mo_id.is_(None),
            (models.PurchaseOrder.odoo_state.is_(None)) | (models.PurchaseOrder.odoo_state != "ignored"),
        )
        .order_by(models.PurchaseOrder.id.desc())
        .all()
    )
    if not orders:
        return {"ok": True, "orders": 0, "matched": [], "unmatched": [], "review": []}

    chains = _chain_rows(client)

    matched: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    for order in orders:
        number = _norm(order.po_number or "")
        candidates: List[Dict[str, Any]] = []

        for group, chain in chains.items():
            matched_on = None
            for field in _CODE_FIELDS:
                if number and chain["keys"].get(field) == number:
                    matched_on = _CODE_LABELS[field]
                    break
            if matched_on:
                candidates.append(_candidate(group, chain, matched_on, order))

        window = _report_window(session, order.po_number)
        if not candidates and _order_has_spec(order):
            for group, chain in chains.items():
                if _spec_matches(order, chain):
                    gap = _date_gap(window, chain)
                    if gap is not None and gap <= HEURISTIC_DAYS:
                        candidates.append(_candidate(group, chain, "heuristic:spec+date", order, gap))

        candidates.sort(key=lambda c: (
            0 if str(c["matched_on"]).startswith("code") else 1,
            c["date_gap"] if c["date_gap"] is not None else 99999,
            c["root_id"],
        ))
        row = {
            "local_mo_id": order.id,
            "po_number": order.po_number,
            "target_qty": order.target_qty,
            "reports_from": window["from"].isoformat() if window and window["from"] else None,
            "reports_to": window["to"].isoformat() if window and window["to"] else None,
            "candidates": candidates,
        }
        review.append(row)
        if candidates and str(candidates[0]["matched_on"]).startswith("code"):
            matched.append(row)
        else:
            unmatched.append({
                "local_mo_id": order.id, "po_number": order.po_number,
                "reason": "heuristic candidates need review" if candidates else "no Odoo MO",
            })

    return {"ok": True, "orders": len(orders), "matched": matched, "unmatched": unmatched, "review": review}


def attach_suggestions(
    rows: List[Dict[str, Any]],
    review: List[Dict[str, Any]],
    per_order: int = 3,
) -> List[Dict[str, Any]]:
    """Merge matcher candidates into the Order Sync rows as ``suggestions`` (pure).

    Only unlinked orders (``odoo_mo_id`` is None) receive suggestions, each capped at
    ``per_order`` and already ordered best-first by ``suggest_unlinked_orders``.
    Linked rows and orders without candidates get an empty list. Input rows are not
    mutated, and nothing is written anywhere.
    """
    by_order = {int(r["local_mo_id"]): r.get("candidates") or [] for r in review}
    out: List[Dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        if row.get("odoo_mo_id") is None:
            merged["suggestions"] = list(by_order.get(int(row["id"]), []))[:per_order]
        else:
            merged["suggestions"] = []
        out.append(merged)
    return out


def _order_has_spec(order: models.PurchaseOrder) -> bool:
    return all(getattr(order, f, None) is not None for f in ("diameter", "length", "pd"))


def _spec_matches(order: models.PurchaseOrder, chain: Dict[str, Any]) -> bool:
    spec = chain["spec"]
    if not spec:
        return False
    return (
        abs(float(order.diameter or 0) - spec["diameter"]) < 0.011
        and abs(float(order.length or 0) - spec["length"]) < 0.011
        and abs(float(order.pd or 0) - spec["pd"]) < 0.5
    )


def _report_window(session: Session, po_number: str) -> Optional[Dict[str, Optional[datetime]]]:
    row = (
        session.query(
            func.min(models.ProductionReport.report_date),
            func.max(models.ProductionReport.report_date),
        )
        .filter(models.ProductionReport.po_number == po_number)
        .first()
    )
    if not row or not row[0]:
        return None
    return {"from": _day(row[0]), "to": _day(row[1])}


def _date_gap(order_window: Optional[Dict], chain: Dict[str, Any]) -> Optional[int]:
    if not order_window or chain["start"] is None or chain["end"] is None:
        return None
    a, b = order_window["from"], order_window["to"]
    if a is None or b is None:
        return None
    if a <= chain["end"] and b >= chain["start"]:
        return 0
    return min(abs((a - chain["end"]).days), abs((b - chain["start"]).days))


def _candidate(
    group: int,
    chain: Dict[str, Any],
    matched_on: str,
    order: models.PurchaseOrder,
    gap: Optional[int] = None,
) -> Dict[str, Any]:
    qty_mismatch = None
    if order.target_qty and chain["total_rods"]:
        try:
            local = float(order.target_qty)
            odoo = float(chain["total_rods"])
            if min(local, odoo) > 0:
                ratio = max(local, odoo) / min(local, odoo)
                if ratio > 1.05:
                    qty_mismatch = "local %s rods vs Odoo %s rods" % (f"{local:.0f}", f"{odoo:.0f}")
        except (TypeError, ValueError):
            pass
    risk: List[str] = []
    if chain["state"] == "open":
        risk.append("open_chain")
    if chain["state"] in ("done", "cancel"):
        risk.append("done_history")
    if qty_mismatch:
        risk.append("qty_mismatch")
    return {
        "root_id": chain["root_id"],
        "root_name": chain["root_name"],
        "open_mo_id": chain["open_mo_id"],
        "mo_count": chain["mo_count"],
        "state": chain["state"],
        "start": chain["start"].isoformat() if chain["start"] else None,
        "end": chain["end"].isoformat() if chain["end"] else None,
        "total_rods": round(chain["total_rods"]),
        "matched_on": matched_on,
        "date_gap": gap,
        "risk": risk,
        "qty_mismatch": qty_mismatch,
    }

