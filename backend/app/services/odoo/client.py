"""Odoo XML-RPC client + transport abstraction, UoM conversion and MO quality
field mapping for the MES -> Odoo integration.

Odoo 18 Community exposes two XML-RPC endpoints:

    * ``/xmlrpc/2/common``  - ``authenticate``
    * ``/xmlrpc/2/object``  - ``execute_kw``

Authentication uses a database name, login and an API key (set on the Odoo user).
The transport is behind an interface so JSON-RPC (Odoo 19+) can be added later
without touching the callers.

Structured quality fields (the custom ``Quality Control`` tab on ``mrp.production``)
are written directly to the MO - never to the chatter.
"""

from __future__ import annotations

import base64
import logging
import os
import xmlrpc.client
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Field-name contract for the custom "Quality Control" tab on mrp.production.
# These live in a small Odoo addon; rename here if the addon changes.
QC_FIELD_MEAN_DIAMETER = "mean_diameter"
QC_FIELD_SD_DIAMETER = "sd_diameter"
QC_FIELD_MEAN_PD = "mean_pd"
QC_FIELD_SD_PD = "sd_pd"
QC_FIELD_QUALITY_STATUS = "quality_status"
QC_FIELD_TESTED_RODS = "tested_rods_count"
QC_FIELD_REJECTED_RODS = "rejected_rods_count"

# MES status -> Odoo selection value.
_STATUS_MAP = {"PASS": "pass", "WARN": "warn", "FAIL": "fail"}


class OdooError(RuntimeError):
    pass


@dataclass
class OdooConfig:
    url: str
    db: str
    username: str
    api_key: str
    enabled: bool = False

    @classmethod
    def from_env(cls) -> "OdooConfig":
        raw = os.getenv("ODOO_ENABLED", "").strip().lower()
        enabled = raw in ("1", "true", "yes", "on")
        return cls(
            url=(os.getenv("ODOO_URL", "") or "").rstrip("/"),
            db=os.getenv("ODOO_DB", "") or "",
            username=os.getenv("ODOO_USER", "") or "",
            api_key=os.getenv("ODOO_API_KEY", "") or "",
            enabled=enabled,
        )

    def valid(self) -> bool:
        return bool(self.url and self.db and self.username and self.api_key)


class OdooTransport:
    """XML-RPC transport for Odoo 18 ``/xmlrpc/2`` (API-key auth)."""

    def __init__(self, url: str) -> None:
        self._common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
        self._object = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def authenticate(self, db: str, username: str, api_key: str) -> int:
        try:
            uid = self._common.authenticate(db, username, api_key, {})
            if not uid:
                raise OdooError("authenticate returned no uid (check credentials)")
            return int(uid)
        except OdooError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OdooError(f"authenticate failed: {exc}") from exc

    def call(
        self,
        db: str,
        uid: int,
        api_key: str,
        model: str,
        method: str,
        args: list,
        kwargs: Optional[dict] = None,
    ) -> Any:
        try:
            return self._object.execute_kw(db, uid, api_key, model, method, args, kwargs or {})
        except Exception as exc:  # noqa: BLE001
            raise OdooError(f"{model}.{method} failed: {exc}") from exc


class OdooClient:
    """High-level Odoo facade used by the inbound/outbound services."""

    def __init__(self, config: OdooConfig) -> None:
        self.config = config
        self._uid: Optional[int] = None
        self._transport: Optional[OdooTransport] = None

    def connect(self) -> None:
        self._transport = OdooTransport(self.config.url)
        self._uid = self._transport.authenticate(
            self.config.db, self.config.username, self.config.api_key
        )

    def _call(self, model: str, method: str, args: list, kwargs: Optional[dict] = None) -> Any:
        if self._transport is None or self._uid is None:
            self.connect()
        assert self._transport is not None and self._uid is not None
        return self._transport.call(
            self.config.db, self._uid, self.config.api_key, model, method, args, kwargs
        )

    # -- low-level helpers ---------------------------------------------------

    def search_read(self, model: str, domain: list, fields: List[str], limit: Optional[int] = None) -> List[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {"fields": fields}
        if limit:
            kwargs["limit"] = limit
        return self._call(model, "search_read", [domain], kwargs)

    def read(self, model: str, ids: List[int], fields: List[str]) -> List[Dict[str, Any]]:
        return self._call(model, "read", [ids], {"fields": fields})

    def write(self, model: str, ids: List[int], values: Dict[str, Any]) -> Any:
        return self._call(model, "write", [ids, values])

    def create(self, model: str, values: Dict[str, Any]) -> int:
        return int(self._call(model, "create", [values]))

    def call(self, model: str, method: str, ids: List[int]) -> Any:
        return self._call(model, method, [ids])

    def attach_pdf(self, name: str, res_model: str, res_id: int, pdf_bytes: bytes) -> int:
        """Attach a PDF as ``ir.attachment`` linked to ``res_model``/``res_id``."""
        return self.create("ir.attachment", {
            "name": name,
            "res_model": res_model,
            "res_id": res_id,
            "type": "binary",
            "mimetype": "application/pdf",
            "datas": base64.b64encode(pdf_bytes).decode("ascii"),
        })

    # -- UoM conversion ------------------------------------------------------

    def resolve_uom_ratio(self, uom_id: Optional[int]) -> float:
        """Return reference units per one product UoM unit.

        ``qty = rods / ratio`` expresses rods in the product's UoM.
        """
        if not uom_id:
            return 1.0
        uoms = self.read("uom.uom", [uom_id], ["name", "factor", "uom_type", "category_id"])
        if not uoms:
            return 1.0
        factor = _num(uoms[0].get("factor"))
        if factor:
            return factor
        return _fallback_ratio(str(uoms[0].get("name", "")))

    def _uom_rounding(self, uom_id: Optional[int]) -> float:
        if not uom_id:
            return 0.001
        uoms = self.read("uom.uom", [uom_id], ["rounding"])
        if uoms and uoms[0].get("rounding"):
            rounding = _num(uoms[0].get("rounding"))
            if rounding:
                return rounding
        return 0.001

    def convert_rods(self, rods: float, uom_id: Optional[int], rounding: Optional[float] = None) -> float:
        ratio = self.resolve_uom_ratio(uom_id)
        qty = rods / ratio
        return float_round(qty, rounding if rounding is not None else self._uom_rounding(uom_id))

    # -- MO completion + quality --------------------------------------------

    def post_completion(self, mo_id: int, qty_rods: float) -> Dict[str, Any]:
        """Record partial completion and let Odoo create a backorder.

        Sets ``qty_producing`` (converted to the product UoM) then calls
        ``button_mark_done``; Odoo automatically creates a backorder for the
        remaining quantity.
        """
        mo = self.read("mrp.production", [mo_id], ["product_uom_id", "product_qty"])
        if not mo:
            raise OdooError(f"mrp.production {mo_id} not found")
        uom_id = _id_ref(mo[0].get("product_uom_id"))
        qty = self.convert_rods(qty_rods, uom_id)
        self.write("mrp.production", [mo_id], {"qty_producing": qty})
        self.call("mrp.production", "button_mark_done", [mo_id])
        return {"mo_id": mo_id, "qty": qty, "uom_id": uom_id}

    def write_mo_quality(self, mo_id: int, run: Dict[str, Any]) -> Dict[str, Any]:
        """Write the structured QC fields for one MO (run). Returns what was set."""
        params = run.get("parameters") or {}
        pd = params.get("pd") or {}
        dia = params.get("diameter") or {}
        has_pd = bool(pd.get("n"))
        has_dia = bool(dia.get("n"))
        if not has_pd and not has_dia:
            return {"skipped": True, "reason": "no measured parameters"}

        values: Dict[str, Any] = {}
        if has_dia:
            values[QC_FIELD_MEAN_DIAMETER] = _num(dia.get("mean"))
            values[QC_FIELD_SD_DIAMETER] = _num(dia.get("sd_samp"))
        if has_pd:
            values[QC_FIELD_MEAN_PD] = _num(pd.get("mean"))
            values[QC_FIELD_SD_PD] = _num(pd.get("sd_samp"))
        values[QC_FIELD_TESTED_RODS] = int(run.get("rods_total") or 0)
        values[QC_FIELD_REJECTED_RODS] = int(run.get("rods_rejected") or 0)

        status = _STATUS_MAP.get(str(run.get("status")))
        if status:
            values[QC_FIELD_QUALITY_STATUS] = status

        self.write("mrp.production", [mo_id], values)
        return values


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if (f != f or f in (float("inf"), float("-inf"))) else f


def _id_ref(value: Any) -> Optional[int]:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fallback_ratio(name: str) -> float:
    n = name.strip().lower()
    if not n:
        return 1.0
    if "million" in n or n in ("m", "m pcs", "mio", "mio pcs"):
        return 1_000_000.0
    if "thousand" in n or "kilo" in n or n in ("k", "k pcs") or n.startswith("k "):
        return 1_000.0
    return 1.0


def float_round(value: float, precision_rounding: float = 0.001) -> float:
    """Round HALF-UP to the given precision (mirrors Odoo's ``float_round``)."""
    if not precision_rounding:
        return float(value)
    d = Decimal(str(value))
    p = Decimal(str(precision_rounding))
    return float((d / p).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * p)

