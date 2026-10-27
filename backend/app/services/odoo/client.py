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
import re
import xmlrpc.client
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.services.odoo.consumption import bobbin_length_metres

logger = logging.getLogger(__name__)

# Field-name contract for the custom "Quality Control" tab on mrp.production.
# These live in a small Odoo addon; rename here if the addon changes.
QC_FIELD_MEAN_DIAMETER = "mean_diameter"
QC_FIELD_SD_DIAMETER = "sd_diameter"
QC_FIELD_MEAN_PD = "mean_pd"
QC_FIELD_SD_PD = "sd_pd"
QC_FIELD_MEAN_LENGTH = "mean_length"
QC_FIELD_SD_LENGTH = "sd_length"
QC_FIELD_MEAN_WEIGHT = "mean_weight"
QC_FIELD_SD_WEIGHT = "sd_weight"
QC_FIELD_MEAN_HARDNESS = "mean_hardness"
QC_FIELD_SD_HARDNESS = "sd_hardness"
QC_FIELD_MEAN_TRIACETIN = "mean_triacetin"
QC_FIELD_QUALITY_STATUS = "quality_status"
QC_FIELD_TESTED_RODS = "tested_rods_count"
QC_FIELD_REJECTED_RODS = "rejected_rods_count"
QC_FIELD_QUALITY_NOTES = "quality_notes"

# Final consolidated order quality (written on the ROOT MO at finalize, distinct
# from the per-backorder QC fields above).
QC_FINAL_MEAN_DIAMETER = "x_final_mean_diameter"
QC_FINAL_SD_DIAMETER = "x_final_sd_diameter"
QC_FINAL_MEAN_PD = "x_final_mean_pd"
QC_FINAL_SD_PD = "x_final_sd_pd"
QC_FINAL_MEAN_LENGTH = "x_final_mean_length"
QC_FINAL_SD_LENGTH = "x_final_sd_length"
QC_FINAL_MEAN_WEIGHT = "x_final_mean_weight"
QC_FINAL_SD_WEIGHT = "x_final_sd_weight"
QC_FINAL_MEAN_HARDNESS = "x_final_mean_hardness"
QC_FINAL_SD_HARDNESS = "x_final_sd_hardness"
QC_FINAL_MEAN_TRIACETIN = "x_final_mean_triacetin"
QC_FINAL_QUALITY_STATUS = "x_final_quality_status"
QC_FINAL_TESTED_RODS = "x_final_tested_rods"
QC_FINAL_REJECTED_RODS = "x_final_rejected_rods"

# Filter-rod QC target/tolerance parameters and their Odoo field names. These
# fields live on BOTH mrp.production (per-MO target) and product.template
# (product default). Odoo does not copy them onto backorders, so the MES reads
# them with a MO, then product, then global fallback.
QC_SPEC_PARAMS = ("diameter", "pd", "weight", "length", "hardness")


def _qc_nominal_field(param: str) -> str:
    return f"x_qc_{param}_nominal"


def _qc_tolerance_field(param: str) -> str:
    return f"x_qc_{param}_tolerance"


QC_SPEC_FIELDS = [
    f for p in QC_SPEC_PARAMS
    for f in (_qc_nominal_field(p), _qc_tolerance_field(p))
]

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
    # Shadow mode: dispatcher reads from Odoo but only records its writes.
    shadow: bool = False

    @classmethod
    def from_env(cls) -> "OdooConfig":
        raw = os.getenv("ODOO_ENABLED", "").strip().lower()
        enabled = raw in ("1", "true", "yes", "on")
        shadow_raw = os.getenv("ODOO_SHADOW_MODE", "").strip().lower()
        return cls(
            url=(os.getenv("ODOO_URL", "") or "").rstrip("/"),
            db=os.getenv("ODOO_DB", "") or "",
            username=os.getenv("ODOO_USER", "") or "",
            api_key=os.getenv("ODOO_API_KEY", "") or "",
            enabled=enabled,
            shadow=shadow_raw in ("1", "true", "yes", "on"),
        )

    def valid(self) -> bool:
        return bool(self.url and self.db and self.username and self.api_key)


class _TimeoutTransport(xmlrpc.client.Transport):
    """HTTP transport with a socket timeout, so a hung Odoo cannot block the
    dispatcher/reconciler request thread forever."""

    def __init__(self, timeout: float = 20.0):
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self.timeout
        return conn


class OdooTransport:
    """XML-RPC transport for Odoo 18 ``/xmlrpc/2`` (API-key auth)."""

    def __init__(self, url: str) -> None:
        self._common = xmlrpc.client.ServerProxy(
            f"{url}/xmlrpc/2/common", transport=_TimeoutTransport(), allow_none=True
        )
        self._object = xmlrpc.client.ServerProxy(
            f"{url}/xmlrpc/2/object", transport=_TimeoutTransport(), allow_none=True
        )

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
        # Per-client UoM ratio cache: resolve_uom_ratio / fetch_uom_ratios read
        # uom.uom over XML-RPC, and bulk flows (chain grouping) need batching.
        self._uom_ratio_cache: Dict[int, float] = {}

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

    def search_read(
        self,
        model: str,
        domain: list,
        fields: List[str],
        limit: Optional[int] = None,
        order: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {"fields": fields}
        if limit:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
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

    def attach_file(
        self, name: str, res_model: str, res_id: int, data: bytes,
        mimetype: str = "application/octet-stream",
    ) -> int:
        """Attach (or REPLACE, matched by name + record) a binary file as ``ir.attachment``.

        Re-sending the same document updates the existing attachment instead of
        stacking duplicates on the MO chatter.
        """
        values = {
            "mimetype": mimetype,
            "datas": base64.b64encode(data).decode("ascii"),
        }
        existing = self.search_read(
            "ir.attachment",
            [["res_model", "=", res_model], ["res_id", "=", res_id], ["name", "=", name]],
            ["id"], limit=1,
        )
        if existing:
            self.write("ir.attachment", [int(existing[0]["id"])], values)
            return int(existing[0]["id"])
        return self.create("ir.attachment", {
            "name": name, "res_model": res_model, "res_id": res_id, "type": "binary", **values,
        })

    # -- UoM conversion ------------------------------------------------------

    def resolve_uom_ratio(self, uom_id: Optional[int]) -> float:
        """Return reference units per one product UoM unit (i.e. ``factor_inv``).

        Odoo converts ``qty / self.factor * to_unit.factor``; a "bigger" unit like
        "1000 pcs" therefore has ``factor = 0.001`` and ``factor_inv = 1000``. To
        express a reference-unit count in that UoM you MULTIPLY by ``factor``
        (== divide by ``factor_inv``), so this returns ``factor_inv``.

        ``qty = rods / ratio`` then yields the quantity in the product's UoM.
        """
        if not uom_id:
            return 1.0
        cache = getattr(self, "_uom_ratio_cache", None)
        if cache is not None and int(uom_id) in cache:
            return cache[int(uom_id)]
        uoms = self.read(
            "uom.uom", [uom_id], ["name", "factor", "factor_inv", "uom_type", "category_id"]
        )
        if not uoms:
            return 1.0
        factor_inv = _num(uoms[0].get("factor_inv"))
        if factor_inv:
            ratio = factor_inv
        else:
            factor = _num(uoms[0].get("factor"))
            ratio = 1.0 / factor if factor else _fallback_ratio(str(uoms[0].get("name", "")))
        if cache is not None:
            cache[int(uom_id)] = ratio
        return ratio

    def fetch_uom_ratios(self, uom_ids) -> Dict[int, float]:
        """Batch-resolve ``factor_inv`` for many UoM ids with ONE Odoo call.

        Avoids the N+1 round trips that made chain grouping (544 MOs) take ~21 s.
        """
        ids = sorted({int(i) for i in uom_ids if i})
        cache = getattr(self, "_uom_ratio_cache", None)
        missing = [i for i in ids if cache is None or i not in cache]
        if missing and cache is not None:
            uoms = self.search_read(
                "uom.uom",
                [["id", "in", missing]],
                ["id", "name", "factor_inv", "factor"],
                limit=len(missing) + 10,
            )
            for u in uoms:
                factor_inv = _num(u.get("factor_inv"))
                if factor_inv:
                    ratio = factor_inv
                else:
                    factor = _num(u.get("factor"))
                    ratio = 1.0 / factor if factor else _fallback_ratio(str(u.get("name", "")))
                cache[int(u["id"])] = ratio
        elif missing and cache is None:
            for i in missing:
                self.resolve_uom_ratio(i)
        return {i: (cache.get(i, 1.0) if cache is not None else self.resolve_uom_ratio(i)) for i in ids}

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

    def to_rods(self, qty_in_uom: float, uom_id: Optional[int]) -> float:
        """Convert a quantity given in a product UoM back into single rods."""
        return float(qty_in_uom or 0.0) * self.resolve_uom_ratio(uom_id)

    # -- MO completion + quality --------------------------------------------

    def post_completion(
        self, mo_id: int, qty_rods: float, consumption: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Record partial completion and let Odoo create a backorder.

        Sets ``qty_producing`` (converted to the product UoM) then calls
        ``button_mark_done``; Odoo automatically creates a backorder for the
        remaining quantity. Returns the new backorder id (or ``None`` when the MO
        is fully consumed) so the caller can store it for lineage.

        ``consumption`` (optional) is a list of per-material items (see
        ``services/odoo/consumption.py``); when given, the matched, untracked,
        unit-compatible components are written onto the raw ``stock.move`` records
        before the MO is marked done.

        Idempotent: a MO already in ``done`` state is left untouched (no double
        completion / no spurious empty backorder).
        """
        plan = self.plan_completion(mo_id, qty_rods)
        if plan.get("skipped"):
            return plan
        mo, uom_id, qty, partial = plan["mo"], plan["uom_id"], plan["qty"], plan["partial"]

        self.write("mrp.production", [mo_id], {"qty_producing": qty})
        # Plan consumption for the reported direct materials AND the remaining
        # (non-direct) components — boxes, pallets, labels, ... — the latter scaled
        # by the produced/planned ratio exactly as Odoo would calculate them.
        proportion = (qty / plan["planned"]) if plan.get("planned") else None
        self.apply_consumption(mo_id, self.plan_consumption(mo_id, consumption or [], proportion))

        try:
            result = self._call(
                "mrp.production", "button_mark_done", [[mo_id]], {"context": plan["context"]}
            )
        except OdooError:
            # Odoo 18 may fail to marshal its response (the redirect action holds a
            # None) even though the completion already landed. Verify the real state
            # before failing, otherwise a retry would complete the next backorder
            # and double-count production.
            if self.read_mo_state(mo_id) != "done":
                raise
            result = True
        if isinstance(result, dict) and result.get("res_model"):
            raise OdooError(
                f"button_mark_done returned wizard {result.get('res_model')} "
                f"for MO {mo_id}; completion not applied"
            )

        state = self.read_mo_state(mo_id)
        if state != "done":
            raise OdooError(f"MO {mo_id} is '{state}' after button_mark_done, expected 'done'")

        backorder_id = self.find_backorder(mo) if partial else None
        if partial and backorder_id is None:
            logger.warning("MO %s completed partially but no backorder was found", mo_id)
        return {"mo_id": mo_id, "qty": qty, "uom_id": uom_id, "backorder_id": backorder_id}

    # -- component consumption ------------------------------------------------

    def uom_category_name(self, uom_id: Optional[int]) -> Optional[str]:
        """Return the category name (e.g. "Weight", "Length") of a uom.uom."""
        if not uom_id:
            return None
        uoms = self.read("uom.uom", [uom_id], ["category_id"])
        if not uoms:
            return None
        cat_id = _id_ref(uoms[0].get("category_id"))
        if not cat_id:
            return None
        cats = self.read("uom.category", [cat_id], ["name"])
        return str(cats[0].get("name")) if cats else None

    def plan_consumption(
        self, mo_id: int, items: List[Dict[str, Any]], proportion: Optional[float] = None
    ) -> Dict[str, Any]:
        """Match consumption items to the MO's raw stock moves and plan the writes.

        ``items`` are the records from ``services/odoo/consumption.py``. Returns
        ``{"actions": [...], "skipped": [...]}`` where each action is
        ``{move_id, product_id, qty, unit, note}`` and each skipped entry carries a
        ``reason`` (needs manual attention, never silently guessed).

        ``proportion`` (produced_qty / planned_qty) enables auto-consumption of the
        remaining (non-direct) components — boxes, pallets, labels, ... — scaled
        exactly as Odoo would calculate them for the produced quantity.
        """
        moves = self.search_read(
            "stock.move",
            [["raw_material_production_id", "=", mo_id], ["state", "!=", "cancel"]],
            ["id", "product_id", "product_uom", "product_uom_qty", "quantity", "state",
             "bom_line_id", "picked"],
        )
        if not moves:
            return {"actions": [], "skipped": [], "note": "no raw moves found"}

        actions: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        used_moves = set()
        for item in items:
            name = str(item.get("type_name") or "").strip()
            qty = float(item.get("used") or 0.0)
            category = str(item.get("category") or "")
            unit = str(item.get("unit") or "kg")
            if not name or qty < 0:
                continue

            move = None
            odoo_product_id = item.get("odoo_product_id")
            if odoo_product_id:
                move = next(
                    (m for m in moves
                     if m["id"] not in used_moves
                     and _id_ref(m.get("product_id")) == int(odoo_product_id)),
                    None,
                )
            if move is None:
                target = normalize_product_name(name)
                move = next(
                    (m for m in moves
                     if m["id"] not in used_moves and _name_matches(m, target)),
                    None,
                )
            if move is None:
                skipped.append({"type_name": name, "reason": "no matching Odoo component/move"})
                continue

            pid = _id_ref(move.get("product_id"))
            if move.get("picked"):
                used_moves.add(move["id"])
                continue  # already consumed on a previous attempt
            tracked = self._product_tracking(pid) if pid else "none"
            if tracked in ("lot", "serial"):
                skipped.append({"type_name": name, "reason": f"product is {tracked}-tracked"})
                used_moves.add(move["id"])
                continue

            cat_name = self.uom_category_name(_id_ref(move.get("product_uom")))
            final_qty = self._consumption_qty(item, move, cat_name)
            if final_qty is None:
                skipped.append({
                    "type_name": name,
                    "reason": f"unit mismatch (report {unit}, move UoM category {cat_name})",
                })
                used_moves.add(move["id"])
                continue

            # Write the true reported amount verbatim, even when it exceeds the
            # move BOM demand: the operator production log is authoritative and must
            # not be silently capped to the BOM quantity.
            actions.append({
                "move_id": int(move["id"]),
                "product_id": pid,
                "qty": float_round(final_qty, self._uom_rounding(_id_ref(move.get("product_uom")))),
                "category": category,
                "type_name": name,
            })
            used_moves.add(move["id"])

        # Auto-consume the remaining (non-direct) components proportionally —
        # boxes, pallets, labels, etc. — because skip_consumption=True means Odoo
        # will not compute them for us.
        if proportion is not None and proportion > 0:
            bom_line_ids = {_id_ref(m.get("bom_line_id")) for m in moves}
            bom_line_ids.discard(None)
            manual_lines: set = set()
            if bom_line_ids:
                try:
                    bom_lines = self.read("mrp.bom.line", sorted(bom_line_ids), ["manual_consumption"])
                    manual_lines = {int(bl["id"]) for bl in bom_lines if bl.get("manual_consumption")}
                except Exception:  # noqa: BLE001 - best effort; default to auto-consume
                    manual_lines = set()
            for move in moves:
                if move["id"] in used_moves:
                    continue
                if _id_ref(move.get("bom_line_id")) in manual_lines:
                    continue  # manual-consumption line: leave for manual entry
                pid = _id_ref(move.get("product_id"))
                tracked = self._product_tracking(pid) if pid else "none"
                if tracked in ("lot", "serial"):
                    continue  # cannot write a tracked component without a lot
                if move.get("picked"):
                    continue  # already consumed on a previous attempt
                remaining = _num(move.get("product_uom_qty")) or 0.0
                if remaining <= 0:
                    continue  # nothing to consume
                qty = min(remaining * proportion, remaining)
                if qty <= 0:
                    continue
                prod = move.get("product_id") or []
                pname = str(prod[1] if isinstance(prod, (list, tuple)) and len(prod) > 1 else "")
                actions.append({
                    "move_id": int(move["id"]),
                    "product_id": pid,
                    "qty": float_round(qty, self._uom_rounding(_id_ref(move.get("product_uom")))),
                    "category": "auto",
                    "type_name": pname or f"component {pid}",
                })
                used_moves.add(move["id"])

        if skipped:
            print(f"[Odoo] consumption skipped {len(skipped)} item(s) for MO {mo_id}: {skipped}")

        return {"actions": actions, "skipped": skipped}

    def _product_tracking(self, product_id: int) -> str:
        products = self.read("product.product", [product_id], ["tracking"])
        return str(products[0].get("tracking") or "none") if products else "none"

    # -- QC target/tolerance resolution (MO, product, global fallback) ------

    def read_mo_spec_fields(self, mo_id: int) -> Dict[str, Any]:
        """Raw ``x_qc_*`` target/tolerance fields from mrp.production (Level 1)."""
        recs = self.read("mrp.production", [int(mo_id)], QC_SPEC_FIELDS)
        return recs[0] if recs else {}

    def read_product_spec_fields(self, product_id: Any) -> Dict[str, Any]:
        """Raw ``x_qc_*`` target/tolerance fields from the product (Level 2).

        ``product_id`` may be a ``product.product`` id (or an ``[id, name]``
        reference); the template is resolved via ``product_tmpl_id``.
        """
        pid = _id_ref(product_id)
        if not pid:
            return {}
        tmpl_id = pid
        prod = self.read("product.product", [pid], ["product_tmpl_id"])
        if prod:
            tmpl_id = _id_ref(prod[0].get("product_tmpl_id")) or pid
        recs = self.read("product.template", [tmpl_id], QC_SPEC_FIELDS)
        return recs[0] if recs else {}

    @staticmethod
    def spec_from_raw_fields(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Map raw ``x_qc_*`` fields to the clean spec dict (param + tolerance)."""
        spec: Dict[str, Any] = {}
        for param in QC_SPEC_PARAMS:
            spec[param] = _num(raw.get(_qc_nominal_field(param)))
            spec[f"{param}_tolerance"] = _num(raw.get(_qc_tolerance_field(param)))
        return spec

    def resolve_mo_product_spec(self, mo_id: int, product_id: Any) -> Tuple[Dict[str, Any], List[str]]:
        """Resolve target params/tolerances from the MO, falling back to the product."""
        mo = self.spec_from_raw_fields(self.read_mo_spec_fields(mo_id))
        product: Dict[str, Any] = {}
        sources: List[str] = []
        for param in QC_SPEC_PARAMS:
            nominal = _num(mo.get(param))
            if nominal not in (None, 0.0):
                sources.append(f"{param}:mo")
                continue
            if not product and product_id is not None:
                product = self.spec_from_raw_fields(self.read_product_spec_fields(product_id))
            p_nominal = _num(product.get(param))
            if p_nominal not in (None, 0.0):
                mo[param] = p_nominal
                mo[f"{param}_tolerance"] = _num(product.get(f"{param}_tolerance"))
                sources.append(f"{param}:product")
            else:
                sources.append(f"{param}:none")
        return mo, sources

    def fill_mo_spec_from_product(self, mo_id: int, product_id: Any) -> Dict[str, Any]:
        """Self-heal a backorder MO whose ``x_qc_*`` fields were not copied.

        Writes the product default target/tolerance fields onto the MO for any
        parameter that is missing/zero, so the Odoo UI no longer shows zeros.
        Never overwrites a non-zero value already on the MO.
        """
        mo = self.read_mo_spec_fields(mo_id)
        product = self.read_product_spec_fields(product_id)
        if not product:
            return {"written": False, "reason": "no product spec"}
        values: Dict[str, Any] = {}
        for param in QC_SPEC_PARAMS:
            mo_nominal = _num(mo.get(_qc_nominal_field(param)))
            prod_nominal = _num(product.get(_qc_nominal_field(param)))
            if mo_nominal in (None, 0.0) and prod_nominal not in (None, 0.0):
                values[_qc_nominal_field(param)] = prod_nominal
                prod_tol = _num(product.get(_qc_tolerance_field(param)))
                if prod_tol is not None:
                    values[_qc_tolerance_field(param)] = prod_tol
        if values:
            self.write("mrp.production", [int(mo_id)], values)
        return {"written": bool(values), "fields": list(values.keys())}

    def _consumption_qty(
        self, item: Dict[str, Any], move: Dict[str, Any], cat_name: Optional[str]
    ) -> Optional[float]:
        """Convert the reported quantity into the move's UoM, or None if unsure."""
        unit = str(item.get("unit") or "kg")
        qty = float(item.get("used") or 0.0)
        move_uom = _id_ref(move.get("product_uom"))
        cat = (cat_name or "").lower()

        if unit == "kg":
            if not cat or "weight" in cat:
                return qty
            if "unit" in cat:  # e.g. "Unit"/"Units" -> reference units (kg == reference)
                return self.convert_rods(qty, move_uom)
            return None

        if unit == "bob":
            if cat and "unit" in cat:
                # Paper tracked as a count of bobbins/rolls: report the count as-is.
                return qty
            metres_per_bob = bobbin_length_metres(str(item.get("type_name") or ""))
            if metres_per_bob is None:
                return None
            total_metres = qty * metres_per_bob
            if cat and "length" in cat:
                return self.convert_rods(total_metres, move_uom)
            return None

        return None

    def apply_consumption(self, mo_id: int, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Write the planned quantities onto the MO's raw stock moves."""
        for action in plan.get("actions", []):
            self.write("stock.move", [action["move_id"]], {
                "quantity": action["qty"],
                "picked": True,
            })
        return plan

    def plan_completion(self, mo_id: int, qty_rods: float) -> Dict[str, Any]:
        """Read-only planning step of ``post_completion`` (safe in shadow mode).

        Returns either a ``{"skipped": True, "reason": ...}`` result, or the plan:
        ``mo`` (header), ``uom_id``, ``qty`` (product UoM), ``planned``, ``partial``
        and the ``context`` flags for ``button_mark_done``.
        """
        mos = self.read(
            "mrp.production",
            [mo_id],
            ["product_uom_id", "product_qty", "state", "procurement_group_id", "backorder_sequence"],
        )
        if not mos:
            raise OdooError(f"mrp.production {mo_id} not found")
        mo = mos[0]
        if mo.get("state") in ("done", "cancel"):
            return {
                "mo_id": mo_id,
                "skipped": True,
                "reason": f"already {mo.get('state')}",
                "backorder_id": None,
            }

        uom_id = _id_ref(mo.get("product_uom_id"))
        qty = self.convert_rods(qty_rods, uom_id)
        if qty <= 0:
            return {"mo_id": mo_id, "skipped": True, "reason": "zero quantity", "backorder_id": None}

        planned = _num(mo.get("product_qty")) or 0.0
        partial = qty < planned - self._uom_rounding(uom_id) / 2.0

        # In Odoo 18 button_mark_done returns a wizard action (backorder /
        # consumption warning / immediate production) unless these context flags
        # are given. With them it completes the MO directly and, for a partial
        # quantity, creates the backorder for the remainder.
        context: Dict[str, Any] = {
            "skip_consumption": True,
            "skip_immediate": True,
            "skip_backorder": True,
            # button_mark_done returns a redirect action (whose context holds
            # mo_ids_to_backorder=None) when it creates a backorder; Odoo's XML-RPC
            # marshaller (allow_none=False) cannot serialize that None. This flag
            # makes button_mark_done return a plain True instead.
            "skip_redirection": True,
        }
        if partial:
            context["mo_ids_to_backorder"] = [mo_id]
        return {
            "mo_id": mo_id,
            "mo": mo,
            "uom_id": uom_id,
            "qty": qty,
            "planned": planned,
            "partial": partial,
            "context": context,
        }

    def find_backorder(self, mo: Dict[str, Any]) -> Optional[int]:
        """Return the backorder created from ``mo`` (next in the procurement group)."""
        group_id = _id_ref(mo.get("procurement_group_id"))
        if not group_id:
            return None
        seq = int(mo.get("backorder_sequence") or 0)
        found = self.search_read(
            "mrp.production",
            [["procurement_group_id", "=", group_id], ["backorder_sequence", ">", seq]],
            ["id", "backorder_sequence"],
            limit=1,
            order="backorder_sequence asc, id asc",
        )
        return int(found[0]["id"]) if found else None

    def chain_status(self, mo_id: int) -> Dict[str, Any]:
        """State of the whole backorder chain that contains ``mo_id``.

        Returns ``{"state": open|done|cancel|missing, "open_mo_id": int|None,
        "total_qty": float|None}`` (total = sum over non-cancelled MOs, i.e. the
        original planned quantity in the product UoM). ``open`` means at least one MO of the chain is
        still confirmed/progress/to_close; ``done`` means the chain is finished
        (at least one MO done); ``cancel`` means every MO was cancelled.
        """
        mos = self.read(
            "mrp.production", [mo_id],
            ["state", "procurement_group_id", "product_qty", "backorder_sequence"],
        )
        if not mos:
            return {"state": "missing", "open_mo_id": None, "total_qty": None}
        head = mos[0]
        group_id = _id_ref(head.get("procurement_group_id"))
        chain = [head | {"id": mo_id}]
        if group_id:
            chain = self.search_read(
                "mrp.production",
                [["procurement_group_id", "=", group_id]],
                ["id", "state", "product_qty", "backorder_sequence"],
                order="backorder_sequence asc, id asc",
            ) or chain
        open_states = ("confirmed", "progress", "to_close")
        open_mos = [m for m in chain if m.get("state") in open_states]
        # A backorder split shrinks the root MO to the produced qty and moves the
        # remainder to the backorder, so the ORIGINAL plan is the chain total.
        total_qty = sum(
            (_num(m.get("product_qty")) or 0.0) for m in chain if m.get("state") != "cancel"
        )
        if open_mos:
            current = max(open_mos, key=lambda m: (m.get("backorder_sequence") or 0, m["id"]))
            state, open_id = "open", int(current["id"])
        elif any(m.get("state") == "done" for m in chain):
            state, open_id = "done", None
        elif all(m.get("state") == "cancel" for m in chain):
            state, open_id = "cancel", None
        else:
            state, open_id = "open", None  # draft: not started yet, keep tracking
        return {"state": state, "open_mo_id": open_id, "total_qty": total_qty}

    def resolve_open_mo(self, mo_id: int) -> Optional[int]:
        """Return the currently open MO of a backorder chain starting at ``mo_id``.

        After a partial completion the remaining quantity lives in a new MO, so a
        link stored on the root MO must be advanced to the open backorder.
        Returns ``None`` when the whole chain is done/cancelled.
        """
        mo = self.read("mrp.production", [mo_id], ["state", "procurement_group_id"])
        if not mo:
            return None
        if mo[0].get("state") not in ("done", "cancel"):
            return mo_id
        group_id = _id_ref(mo[0].get("procurement_group_id"))
        if not group_id:
            return None
        found = self.search_read(
            "mrp.production",
            [["procurement_group_id", "=", group_id],
             ["state", "in", ["confirmed", "progress", "to_close"]]],
            ["id"],
            limit=1,
            order="backorder_sequence desc, id desc",
        )
        return int(found[0]["id"]) if found else None

    def read_mo_state(self, mo_id: int) -> Optional[str]:
        """Return the current ``state`` of a manufacturing order, or None."""
        mos = self.read("mrp.production", [mo_id], ["state"])
        return mos[0].get("state") if mos else None

    def write_mo_quality(self, mo_id: int, run: Dict[str, Any]) -> Dict[str, Any]:
        """Write the structured QC fields for one MO (run). Returns what was set."""
        values = self.build_quality_values(run)
        if values is None:
            return {"skipped": True, "reason": "no measured parameters"}
        self.write("mrp.production", [mo_id], values)
        return values

    @staticmethod
    def build_quality_values(run: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Pure mapping run summary -> Odoo QC field values (None if nothing measured)."""
        params = run.get("parameters") or {}
        pd = params.get("pd") or {}
        dia = params.get("diameter") or {}
        length = params.get("length") or {}
        weight = params.get("weight") or {}
        hardness = params.get("hardness") or {}
        tri = run.get("triacetin_overall")

        def has(p: Dict[str, Any]) -> bool:
            return bool(p.get("n"))

        if not any(has(p) for p in (pd, dia, length, weight, hardness)) and tri is None:
            return None

        values: Dict[str, Any] = {}
        if has(dia):
            values[QC_FIELD_MEAN_DIAMETER] = _num(dia.get("mean"))
            values[QC_FIELD_SD_DIAMETER] = _num(dia.get("sd_samp"))
        if has(pd):
            values[QC_FIELD_MEAN_PD] = _num(pd.get("mean"))
            values[QC_FIELD_SD_PD] = _num(pd.get("sd_samp"))
        if has(length):
            values[QC_FIELD_MEAN_LENGTH] = _num(length.get("mean"))
            values[QC_FIELD_SD_LENGTH] = _num(length.get("sd_samp"))
        if has(hardness):
            values[QC_FIELD_MEAN_HARDNESS] = _num(hardness.get("mean"))
            values[QC_FIELD_SD_HARDNESS] = _num(hardness.get("sd_samp"))
        if has(weight):
            # Weight is measured per rod but certified per ``report_scale`` rods
            # (g / 100), matching the Odoo certificate's weight unit.
            scale = float(weight.get("report_scale") or 1.0)
            values[QC_FIELD_MEAN_WEIGHT] = _scaled_num(weight.get("mean"), scale)
            values[QC_FIELD_SD_WEIGHT] = _scaled_num(weight.get("sd_samp"), scale)
        if tri is not None:
            values[QC_FIELD_MEAN_TRIACETIN] = _num(tri)
        values[QC_FIELD_TESTED_RODS] = int(run.get("rods_total") or 0)
        values[QC_FIELD_REJECTED_RODS] = int(run.get("rods_rejected") or 0)

        status = _STATUS_MAP.get(str(run.get("status")))
        if status:
            values[QC_FIELD_QUALITY_STATUS] = status
        notes = (run.get("remarks") or "").strip()
        if notes:
            values[QC_FIELD_QUALITY_NOTES] = notes
        return values

    def write_final_quality(self, mo_id: int, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Write the consolidated order quality onto the ROOT MO's ``x_final_*`` fields.

        Distinct from ``write_mo_quality`` (per-backorder): this captures the
        weighted mean / combined SD / tested / rejected over the whole order.
        """
        values = self.build_final_quality_values(summary)
        if values is None:
            return {"skipped": True, "reason": "no measured parameters"}
        self.write("mrp.production", [mo_id], values)
        return values

    @staticmethod
    def build_final_quality_values(summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        params = summary.get("parameters") or {}
        pd = params.get("pd") or {}
        dia = params.get("diameter") or {}
        length = params.get("length") or {}
        weight = params.get("weight") or {}
        hardness = params.get("hardness") or {}
        tri = summary.get("triacetin_overall")

        def has(p: Dict[str, Any]) -> bool:
            return bool(p.get("n"))

        if not any(has(p) for p in (pd, dia, length, weight, hardness)) and tri is None:
            return None

        values: Dict[str, Any] = {}
        if has(dia):
            values[QC_FINAL_MEAN_DIAMETER] = _num(dia.get("mean"))
            values[QC_FINAL_SD_DIAMETER] = _num(dia.get("sd_samp"))
        if has(pd):
            values[QC_FINAL_MEAN_PD] = _num(pd.get("mean"))
            values[QC_FINAL_SD_PD] = _num(pd.get("sd_samp"))
        if has(length):
            values[QC_FINAL_MEAN_LENGTH] = _num(length.get("mean"))
            values[QC_FINAL_SD_LENGTH] = _num(length.get("sd_samp"))
        if has(hardness):
            values[QC_FINAL_MEAN_HARDNESS] = _num(hardness.get("mean"))
            values[QC_FINAL_SD_HARDNESS] = _num(hardness.get("sd_samp"))
        if has(weight):
            scale = float(weight.get("report_scale") or 1.0)
            values[QC_FINAL_MEAN_WEIGHT] = _scaled_num(weight.get("mean"), scale)
            values[QC_FINAL_SD_WEIGHT] = _scaled_num(weight.get("sd_samp"), scale)
        if tri is not None:
            values[QC_FINAL_MEAN_TRIACETIN] = _num(tri)
        values[QC_FINAL_TESTED_RODS] = int(summary.get("rods_total") or 0)
        values[QC_FINAL_REJECTED_RODS] = int(summary.get("rods_rejected") or 0)
        status = _STATUS_MAP.get(str(summary.get("status")))
        if status:
            values[QC_FINAL_QUALITY_STATUS] = status
        return values


def normalize_product_name(name: str) -> str:
    """Lowercase, comma->dot, drop parenthesised suffixes, collapse spaces."""
    n = (name or "").lower().replace(",", ".")
    n = re.sub(r"\([^)]*\)", "", n)
    return re.sub(r"\s+", " ", n).strip()


def _name_matches(move: Dict[str, Any], target: str) -> bool:
    """True when the move's product name matches the normalized report name."""
    prod = move.get("product_id") or []
    name = normalize_product_name(str(prod[1] if isinstance(prod, (list, tuple)) and len(prod) > 1 else ""))
    if not name or not target:
        return False
    return name == target or name in target or target in name


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if (f != f or f in (float("inf"), float("-inf"))) else f


def _scaled_num(value: Any, scale: float) -> Optional[float]:
    """Scale a numeric value by ``scale`` and round to 4 decimals (else None)."""
    f = _num(value)
    return None if f is None else round(f * scale, 4)


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

