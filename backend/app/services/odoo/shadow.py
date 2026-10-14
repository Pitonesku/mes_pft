"""Shadow-mode Odoo client (Phase 3).

``ShadowClient`` wraps a real ``OdooClient``: every READ is forwarded to Odoo (so
the plan is computed against real data), every WRITE is recorded in ``actions``
and NOT sent. The dispatcher can therefore run the complete production flow for
weeks and the recorded actions be compared with what the warehouse expects before
going live (``ODOO_SHADOW_MODE=false``).
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

from app.services.odoo.client import OdooClient


class ShadowClient:
    is_shadow = True

    def __init__(self, real: OdooClient) -> None:
        self._real = real
        self.actions: List[Dict[str, Any]] = []

    # -- reads: forwarded to the real Odoo ---------------------------------
    def connect(self) -> None:
        self._real.connect()

    def search_read(self, *args, **kwargs):
        return self._real.search_read(*args, **kwargs)

    def read(self, *args, **kwargs):
        return self._real.read(*args, **kwargs)

    def resolve_open_mo(self, mo_id: int) -> Optional[int]:
        return self._real.resolve_open_mo(mo_id)

    def plan_completion(self, mo_id: int, qty_rods: float) -> Dict[str, Any]:
        return self._real.plan_completion(mo_id, qty_rods)

    def plan_consumption(self, mo_id: int, items: List[Dict[str, Any]], proportion: Optional[float] = None) -> Dict[str, Any]:
        return self._real.plan_consumption(mo_id, items, proportion)

    # -- writes: recorded only ----------------------------------------------
    def write_mo_quality(self, mo_id: int, run: Dict[str, Any]) -> Dict[str, Any]:
        values = self._real.build_quality_values(run)
        if values is None:
            self.actions.append({"action": "write_quality", "mo_id": mo_id, "skipped": "no measured parameters"})
            return {"skipped": True, "reason": "no measured parameters"}
        self.actions.append({"action": "write_quality", "mo_id": mo_id, "values": values})
        return values

    def attach_pdf(self, name: str, res_model: str, res_id: int, pdf_bytes: bytes) -> int:
        self.actions.append({
            "action": "attach_pdf", "name": name, "res_model": res_model,
            "res_id": res_id, "bytes": len(pdf_bytes),
        })
        return 0

    def attach_file(self, name: str, res_model: str, res_id: int, data: bytes,
                    mimetype: str = "application/octet-stream") -> int:
        self.actions.append({
            "action": "attach_file", "name": name, "res_model": res_model,
            "res_id": res_id, "bytes": len(data), "mimetype": mimetype,
        })
        return 0

    def post_completion(self, mo_id: int, qty_rods: float, consumption: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        plan = self._real.plan_completion(mo_id, qty_rods)
        if plan.get("skipped"):
            self.actions.append({"action": "complete_mo", "mo_id": mo_id, "skipped": plan.get("reason")})
            return plan
        proportion = (plan["qty"] / plan["planned"]) if plan.get("planned") else None
        cons = self._real.plan_consumption(mo_id, consumption or [], proportion)
        self.actions.append({"action": "apply_consumption", "mo_id": mo_id, **cons})
        self.actions.append({
            "action": "complete_mo",
            "mo_id": mo_id,
            "rods": qty_rods,
            "qty_producing": plan["qty"],
            "planned_qty": plan["planned"],
            "partial": plan["partial"],
            "expects_backorder": plan["partial"],
            "context": plan["context"],
        })
        return {"mo_id": mo_id, "qty": plan["qty"], "uom_id": plan["uom_id"],
                "backorder_id": None, "shadow": True}
