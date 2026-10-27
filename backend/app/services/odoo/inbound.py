"""Inbound Odoo -> MES: fetch open manufacturing orders and link them to local
production runs / purchase orders without touching existing production data."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app import models
from app.services import aggregation
from app.services.odoo.client import OdooClient, OdooError, QC_SPEC_PARAMS, _id_ref

logger = logging.getLogger(__name__)


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


OPEN_MO_STATES = ("confirmed", "progress", "to_close")

# Filter-rod material groups that are synced from the Odoo BOM. Everything else
# (packaging, labels, adhesives unrelated to the rod itself) is intentionally
# dropped — "not full BOM required, only direct filter rod materials".
_DIRECT_MATERIAL_GROUPS = ("acetate", "paper", "triacetin", "glue")

_GROUP_KEYWORDS = {
    "acetate": ("acetate", "tow", "cerdia", "monoacetate"),
    "paper": ("paper", "plug wrap", "plugwrap", "tipping"),
    "triacetin": ("triacetin", "plasticizer", "plasticiser"),
    "glue": ("glue", "pva", "hm ", "hot melt", "adhesive", "seam"),
}


def _classify_material(name: str) -> Optional[str]:
    """Map a raw Odoo BOM product name to a direct filter-rod material group.

    Returns the canonical category (``acetate``/``paper``/``triacetin``/``glue``)
    or ``None`` when the component is not a direct filter-rod material.
    """
    n = (name or "").lower()
    if not n:
        return None
    for category in _DIRECT_MATERIAL_GROUPS:
        if category in n:
            return category
    for category, keywords in _GROUP_KEYWORDS.items():
        if any(k in n for k in keywords):
            return category
    return None


def _qty_pieces(qty: float, uom_name: str) -> float:
    """Best-effort conversion of a component qty to reference pieces.

    Components are usually in weight (kg) for acetate tow / glue / triacetin and
    length (m) for paper, so no piece conversion is applied — the raw qty and UoM
    are preserved. This helper only normalises an explicit thousand/million UoM.
    """
    u = (uom_name or "").lower()
    if "million" in u or "mio" in u or u in ("m", "m pcs", "mio pcs"):
        return float(qty) * 1_000_000.0
    if "thousand" in u or "1000" in u or "kilo" in u or u in ("k", "k pcs") or u.startswith("k "):
        return float(qty) * 1_000.0
    return float(qty)


def handle_mo_event(
    session: Session, event: Dict[str, Any], client: Optional[OdooClient] = None
) -> Dict[str, Any]:
    """Create/update the MES side of a Manufacturing Order pushed from Odoo.

    Idempotent by ``mo_id``: re-pushing the same MO updates the order + filtered
    BOM without creating duplicates or touching existing production data.

    Steps:
      1. Upsert ``PurchaseOrder`` (po_number = origin or MO name) + spec columns.
      2. Upsert ``QualitySpec`` rows (scope ``po``) from the spec payload.
      3. Upsert ``ProductionRunComponent`` rows from the filtered BOM.
    """
    mo_id = int(event.get("mo_id") or 0)
    if not mo_id:
        raise ValueError("mo_id is required")

    name = str(event.get("name") or "").strip()
    origin = str(event.get("origin") or "").strip()
    root_name = str(event.get("root_name") or "").strip()
    root_mo_id = event.get("root_mo_id")
    po_number = origin or root_name or name or f"MO-{mo_id}"

    spec = event.get("spec") or {}

    effective_root_id = int(root_mo_id) if root_mo_id else mo_id
    state = str(event.get("state") or "")
    is_open = state in OPEN_MO_STATES
    print(
        f"[Odoo] inbound mo-event: mo_id={mo_id} name={name!r} state={state!r} "
        f"root_mo_id={effective_root_id} origin={origin!r} is_open={is_open}"
    )

    if state in ("done", "cancel"):
        return _handle_state_event(session, event, effective_root_id, state)

    # 1. Upsert the order. Identity = root Odoo MO id (stable); po_number is only
    #    a display/legacy key, so two MOs of one sales order never collide.
    po = (
        session.query(models.PurchaseOrder)
        .filter(models.PurchaseOrder.odoo_mo_id == effective_root_id)
        .first()
    )
    if po is None:
        po = (
            session.query(models.PurchaseOrder)
            .filter(models.PurchaseOrder.po_number == po_number)
            .first()
        )
        if po is not None and po.odoo_mo_id not in (None, effective_root_id):
            # Same number but already linked to a different MO: keep both.
            po_number = f"{po_number} [{root_name or name or effective_root_id}]"
            po = None
    created = po is None
    if created:
        po = models.PurchaseOrder(
            po_number=po_number,
            diameter=0.0, length=0.0, pd=0.0, cu=0, weight=0.0, box_type=0,
            acetate_type="", paper_type="", pva_glue_type="", hm_glue_type="",
            triacetin_type="", target_qty=0, produced_qty=0,
            # A brand-new order from an open MO is posted back to Odoo; legacy
            # local orders keep 'link_only' until an admin promotes them.
            sync_mode="full" if is_open else "link_only",
        )
        session.add(po)
        session.flush()

    target_pcs = _qty_pieces(
        float(event.get("product_qty") or 0), str(event.get("product_uom_name") or "")
    )
    if target_pcs:
        po.target_qty = int(round(target_pcs))

    spec = _resolve_spec(session, client, mo_id, event.get("product_id"), spec, po)
    _apply_po_spec(po, spec)
    # Top-level box_type (rods per box from the Base Packaging) is authoritative;
    # spec['box_type'] remains the fallback handled inside _apply_po_spec.
    if event.get("box_type") is not None:
        po.box_type = int(event["box_type"])
    _apply_material_types(po, event.get("bom") or [])
    po.source = "odoo"  # this MO was synced from Odoo
    po.odoo_mo_id = effective_root_id
    po.odoo_mo_name = root_name or name
    if is_open:
        po.odoo_current_mo_id = mo_id  # the MO shifts must currently post to
        po.odoo_state = "open"

    # 2. QualitySpec rows (scope po).
    _upsert_po_specs(session, po, spec)

    # 3. Filtered BOM components.
    session.query(models.ProductionRunComponent).filter(
        models.ProductionRunComponent.po_id == po.id
    ).delete(synchronize_session=False)
    for seq, comp in enumerate(event.get("bom") or []):
        product_name = str(comp.get("product_name") or "").strip()
        category = comp.get("category") or _classify_material(product_name)
        if category not in _DIRECT_MATERIAL_GROUPS:
            continue  # drop non-direct components (full BOM filtered out)
        session.add(
            models.ProductionRunComponent(
                po_id=po.id,
                seq=seq,
                category=category,
                product_name=product_name or f"{category} (MO-{mo_id})",
                product_qty=float(comp.get("product_qty") or 0),
                product_uom=comp.get("product_uom") or None,
                odoo_bom_line_id=int(comp["odoo_bom_line_id"]) if comp.get("odoo_bom_line_id") else None,
                material_id=_match_material(session, category, product_name, comp.get("odoo_product_id")),
            )
        )

    session.commit()
    return {
        "mo_id": mo_id,
        "po_id": po.id,
        "po_number": po.po_number,
        "created": created,
        "sync_mode": po.sync_mode,
        "components": len(event.get("bom") or []),
    }


def _handle_state_event(
    session: Session, event: Dict[str, Any], root_id: int, state: str
) -> Dict[str, Any]:
    """Handle a ``done`` / ``cancel`` MO event without touching spec or BOM.

    A ``done`` MO may just be a partial completion whose backorder is still open,
    and a cancelled MO may be one of several in the chain, so the event only marks
    the order ``check``; the reconciler reads the whole chain and sets the real
    state. Unknown orders are ignored (nothing is created from a dead MO).
    """
    mo_id = int(event.get("mo_id") or 0)
    po = (
        session.query(models.PurchaseOrder)
        .filter(models.PurchaseOrder.odoo_mo_id == root_id)
        .first()
    )
    if po is None:
        return {"mo_id": mo_id, "ignored": True, "reason": "order not known to MES", "state": state}
    if po.odoo_state != "cancel" and po.odoo_state != "done":
        po.odoo_state = "check"
    session.commit()
    return {"mo_id": mo_id, "po_id": po.id, "state": state, "odoo_state": po.odoo_state}


def _resolve_spec(
    session: Session,
    client: Optional[OdooClient],
    mo_id: int,
    product_id: Any,
    webhook_spec: Optional[Dict[str, Any]],
    po,
) -> Dict[str, Any]:
    """Resolve QC target params/tolerances with a 3-level fallback.

    1. Webhook spec / current MO fields (Level 1).
    2. Odoo product template defaults (Level 2).
    3. MES global defaults (Level 3: PO nominal columns + factory tolerances).
    """
    spec: Dict[str, Any] = dict(webhook_spec or {})

    # Level 1 + Level 2: authoritative Odoo MO / product target fields.
    if client is not None and mo_id:
        try:
            odoo_spec, sources = client.resolve_mo_product_spec(mo_id, product_id)
            logger.info("Odoo spec sources for MO %s: %s", mo_id, sources)
        except OdooError as exc:
            logger.warning("Odoo spec fallback read failed for MO %s: %s", mo_id, exc)
            odoo_spec = {}
        for param in QC_SPEC_PARAMS:
            if _f(spec.get(param)) not in (None, 0.0):
                continue
            nominal = _f(odoo_spec.get(param))
            if nominal not in (None, 0.0):
                spec[param] = nominal
                tol = _f(odoo_spec.get(f"{param}_tolerance"))
                if tol not in (None, 0.0):
                    spec[f"{param}_tolerance"] = tol

    # Self-heal the backorder MO in Odoo so its UI no longer shows zeros.
    if client is not None and mo_id and product_id is not None:
        try:
            client.fill_mo_spec_from_product(mo_id, product_id)
        except OdooError as exc:
            logger.warning("Odoo backorder spec self-heal failed for MO %s: %s", mo_id, exc)

    return _fill_global_fallback(session, spec, po)


def _fill_global_fallback(session: Session, spec: Dict[str, Any], po) -> Dict[str, Any]:
    """Level 3: fill remaining gaps from PO nominal columns + MES global defaults."""
    glob = aggregation.global_spec_defaults(session)
    po_nominals = {
        "diameter": getattr(po, "diameter", None),
        "pd": getattr(po, "pd", None),
        "weight": getattr(po, "weight", None),
        "length": getattr(po, "length", None),
        "hardness": None,
    }
    for param in QC_SPEC_PARAMS:
        nominal = _f(spec.get(param))
        if nominal in (None, 0.0):
            nominal = _f(po_nominals.get(param))
        if nominal in (None, 0.0):
            nominal = _f((glob.get(param) or {}).get("nominal"))
        if nominal not in (None, 0.0):
            spec[param] = nominal
        tol = _f(spec.get(f"{param}_tolerance"))
        if tol in (None, 0.0):
            tol = _f((glob.get(param) or {}).get("tolerance"))
        if tol is not None:
            spec[f"{param}_tolerance"] = tol
    # Normalize: a zero nominal/tolerance means "missing" (Odoo returns 0.0 for
    # unset fields), so never leave 0.0 in the resolved spec.
    for param in QC_SPEC_PARAMS:
        if _f(spec.get(param)) in (None, 0.0):
            spec[param] = None
        if _f(spec.get(f"{param}_tolerance")) in (None, 0.0):
            spec[f"{param}_tolerance"] = None
    return spec


def _apply_po_spec(po, spec: Dict[str, Any]) -> None:
    """Map the Odoo spec payload onto the PurchaseOrder spec columns (best-effort)."""
    if spec.get("diameter") is not None:
        po.diameter = _f(spec.get("diameter"))
    if spec.get("length") is not None:
        po.length = _f(spec.get("length"))
    if spec.get("pd") is not None:
        po.pd = _f(spec.get("pd"))
    if spec.get("cu") is not None:
        po.cu = int(spec.get("cu"))
    if spec.get("weight") is not None:
        po.weight = _f(spec.get("weight"))
    if spec.get("box_type") is not None:
        po.box_type = int(spec.get("box_type"))
    if spec.get("triacetin") is not None:
        po.triacetin = _f(spec.get("triacetin"))
    if spec.get("triacetin_tolerance") is not None:
        po.triacetin_tolerance = _f(spec.get("triacetin_tolerance"))


def _apply_material_types(po, bom: List[Dict[str, Any]]) -> None:
    """Map filtered BOM components onto the PO's material type columns.

    Best-effort: fills the legacy per-material type fields so a newly created
    PO is never left with NULL/NOT-NULL-invalid values. Glue is split into PVA
    vs hot-melt by keyword.
    """
    for comp in bom:
        name = str(comp.get("product_name") or "").strip()
        if not name:
            continue
        category = comp.get("category") or _classify_material(name)
        if category == "acetate" and not po.acetate_type:
            po.acetate_type = name
        elif category == "paper" and not po.paper_type:
            po.paper_type = name
        elif category == "triacetin" and not po.triacetin_type:
            po.triacetin_type = name
        elif category == "glue":
            low = name.lower()
            if ("hm" in low or "hot melt" in low or "hotmelt" in low) and not po.hm_glue_type:
                po.hm_glue_type = name
            elif not po.pva_glue_type:
                po.pva_glue_type = name


_DIAMETER_TOLERANCE_MAX = 0.1  # mm; a filter-rod diameter spec is ~±0.03 mm


def _default_diameter_tolerance(session: Session) -> float:
    """Factory default diameter tolerance, used when Odoo sends an implausible one."""
    row = session.query(models.QualitySettings).first()
    if row is not None and row.diameter_tolerance is not None:
        try:
            return float(row.diameter_tolerance)
        except (TypeError, ValueError):
            pass
    return 0.03


def _upsert_po_specs(session: Session, po, spec: Dict[str, Any]) -> None:
    """Upsert per-PO QualitySpec rows for the parameters present in the spec."""
    for parameter in ("diameter", "pd", "weight", "length", "hardness", "triacetin"):
        nominal = spec.get(parameter)
        if nominal is None:
            continue
        nominal = _f(nominal)
        if nominal in (None, 0.0):
            continue
        tol = _f(spec.get(f"{parameter}_tolerance"))
        if tol == 0.0:
            tol = None
        # Guard against a 10x data-entry error in Odoo's free-form
        # ``x_qc_diameter_tolerance`` (0.3 instead of 0.03): anything above
        # 0.1 mm is implausible for a filter rod and falls back to the factory
        # default instead of silently widening the limits by an order of magnitude.
        if parameter == "diameter" and tol is not None and tol > _DIAMETER_TOLERANCE_MAX:
            default_tol = _default_diameter_tolerance(session)
            logger.warning(
                "Ignoring implausible diameter tolerance %.4f for PO %s "
                "(> %.2f mm); using factory default %.3f",
                tol, getattr(po, "po_number", po.id), _DIAMETER_TOLERANCE_MAX, default_tol,
            )
            tol = default_tol
        lower = None if tol is None else nominal - tol
        upper = None if tol is None else nominal + tol
        row = (
            session.query(models.QualitySpec)
            .filter(
                models.QualitySpec.scope == "po",
                models.QualitySpec.po_id == po.id,
                models.QualitySpec.parameter == parameter,
            )
            .first()
        )
        if row is None:
            row = models.QualitySpec(scope="po", po_id=po.id, parameter=parameter)
            session.add(row)
        row.nominal = nominal
        row.lower_limit = lower
        row.upper_limit = upper
        if parameter == "weight":
            # Odoo reports filter-rod weight in mg/rod (e.g. 666 mg). Store it in
            # report units with scale 1000 so build_param_specs divides back to
            # g/rod (0.666) and the rejection bounds match the measurement.
            row.report_unit = "mg"
            row.report_scale = 1000
        elif parameter == "triacetin":
            row.report_unit = "%"
            row.report_scale = 1
            row.decimals = 2


_FILLER_TOKENS = ("tow", "kg", "glue", "cold glue", "acetate", "filter", "rod", "hot melt", "hotmelt")


def normalize_material_name(name: str) -> str:
    """Normalize a material/product name for fuzzy matching.

    Lowercases, maps commas to dots, strips whitespace and descriptive filler
    tokens (tow, kg, glue, ...) plus parenthesised weights/specs, so e.g.
    ``Cerdia Acetate Tow 3,0Y30000HK (560kg)`` and ``Cerdia 3.0Y30000`` compare
    on their meaningful core.
    """
    if not name:
        return ""
    n = name.lower()
    n = n.replace(",", ".")
    n = re.sub(r"\([^)]*\)", "", n)  # drop (560kg) style suffixes
    for tok in _FILLER_TOKENS:
        n = re.sub(rf"\b{re.escape(tok)}\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _match_material(
    session: Session,
    category: str,
    product_name: str,
    odoo_product_id: Optional[int] = None,
) -> Optional[int]:
    """Match a component to material_dictionary using normalized names.

    Persists ``material_dictionary.odoo_product_id`` when a confident match is
    found so the Materials view and edit dialogs can resolve the Odoo product.
    Returns the matched local material id, or None.
    """
    if not product_name:
        return None
    target = normalize_material_name(product_name)
    if not target:
        return None
    rows = session.query(models.MaterialDictionary).filter(
        models.MaterialDictionary.category == category
    ).all()
    best = None
    exact = False
    for row in rows:
        local = normalize_material_name(row.type_name or "")
        if not local:
            continue
        if local == target:
            best, exact = row, True
            break
        if best is None and (local in target or target in local):
            best = row
    # Only an EXACT normalized match may persist the Odoo link. A fuzzy match is
    # used for display/lot tracking but must be confirmed by an admin through the
    # mapping API (services/odoo/mapping.py) before it is stored.
    if exact and odoo_product_id and best.odoo_product_id is None:
        best.odoo_product_id = int(odoo_product_id)
        best.source = "odoo"
    return best.id if best is not None else None


def _f(value) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f


_FILTER_ROD_RE = re.compile(
    r'(?P<diameter>\d+(?:[.,]\d+)?)\s*[*\-–—xX]\s*(?P<length>\d+)\s+PD\s*(?P<pressure>\d+)',
    re.IGNORECASE,
)


def _parse_odoo_spec(product_name: Optional[str]) -> Optional[Dict[str, float]]:
    """Parse diameter/length/pd from an Odoo product name (e.g. 7,72*108 PD325)."""
    if not product_name:
        return None
    m = _FILTER_ROD_RE.search(product_name)
    if not m:
        return None
    return {
        "diameter": float(m.group("diameter").replace(",", ".")),
        "length": float(m.group("length")),
        "pd": float(m.group("pressure")),
    }


def sync_orders(
    session: Session,
    client: OdooClient,
    scope: str = "active",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Pull root Manufacturing Orders from Odoo and link them to local orders.

    Resolves the root MO (backorders are skipped via ``backorder_sequence == 0``),
    auto-matches by Odoo ``name``/``origin`` against the local ``mo_number``
    (legacy ``po_number``), and non-destructively stamps the Odoo link + source.

    Returns ``{linked_existing, created_new, unmatched}``. Unmatched entries are
    resolved interactively by the client via the link-order endpoint.
    """
    domain: List[List[Any]] = [["backorder_sequence", "=", 0]]
    now = datetime.now(timezone.utc)

    if scope == "active":
        domain.append(["state", "in", ["confirmed", "progress"]])
    elif scope in ("7d", "30d"):
        days = 7 if scope == "7d" else 30
        since = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        domain.append(["date_planned_start", ">=", since])
    elif scope == "custom":
        if date_from:
            domain.append(["date_planned_start", ">=", date_from])
        if date_to:
            domain.append(["date_planned_start", "<=", date_to])
        else:
            domain.append(["state", "in", ["confirmed", "progress"]])
    else:
        domain.append(["state", "in", ["confirmed", "progress"]])

    mos = client.search_read(
        "mrp.production",
        domain,
        ["id", "name", "state", "product_qty", "origin", "backorder_sequence",
         "date_planned_start", "product_id"],
        limit=500,
    )

    linked = 0
    unmatched: List[Dict[str, Any]] = []
    for mo in mos:
        mo_id = int(mo["id"])
        name = str(mo.get("name") or "").strip()
        origin = str(mo.get("origin") or "").strip()

        po = None
        if name:
            po = session.query(models.PurchaseOrder).filter(
                models.PurchaseOrder.po_number == name
            ).first()
        if po is None and origin:
            po = session.query(models.PurchaseOrder).filter(
                models.PurchaseOrder.po_number == origin
            ).first()

        if po is not None:
            po.odoo_mo_id = mo_id
            po.odoo_mo_name = name
            po.source = "odoo"
            po.odoo_linked_at = now
            linked += 1
        else:
            product_name = ""
            if isinstance(mo.get("product_id"), (list, tuple)) and len(mo["product_id"]) > 1:
                product_name = str(mo["product_id"][1] or "")
            unmatched.append({
                "odoo_mo_id": mo_id,
                "name": name,
                "origin": origin,
                "product_qty": mo.get("product_qty"),
                "product_name": product_name,
                "spec": _parse_odoo_spec(product_name),
            })

    session.commit()
    return {"linked_existing": linked, "created_new": 0, "unmatched": unmatched}


# Fields read from mrp.production when linking an order. Odoo 18: the UoM field
# is ``product_uom_id`` (``product_uom`` does not exist and fails the whole read).
MO_LINK_FIELDS = [
    "id", "name", "product_qty", "origin", "product_id",
    "backorder_sequence", "procurement_group_id", "product_uom_id",
]


def _box_type_from_odoo(client: OdooClient, product_id: Any) -> Optional[int]:
    """Compute rods-per-box from the finished product's Base Packaging.

    Mirrors mes_integration's ``_box_type_from_base_packaging``: the product UoM is
    ``1000pcs`` (factor 0.001), so ``qty / factor`` yields rods per box
    (e.g. 4.7 / 0.001 = 4700). Returns None when it cannot be resolved.
    """
    if not product_id:
        return None
    pid = int(product_id)
    try:
        pkgs = client.search_read(
            "product.packaging",
            [["product_id", "=", pid], ["is_base_packaging", "=", True]],
            ["qty", "product_uom_id"],
            limit=1,
        )
        if not pkgs:
            return None
        qty = float(pkgs[0].get("qty") or 0)
        uom = pkgs[0].get("product_uom_id")  # XML-RPC Many2one -> [id, name]
        uom_id = int(uom[0]) if isinstance(uom, (list, tuple)) and uom else None
        if not uom_id:
            return None
        uoms = client.search_read("uom.uom", [["id", "=", uom_id]], ["factor"], limit=1)
        factor = float(uoms[0].get("factor") or 0) if uoms else 0.0
        if not qty or not factor:
            return None
        return int(round(qty / factor))
    except Exception:
        return None


def link_order(
    session: Session,
    client: OdooClient,
    odoo_mo_id: int,
    local_mo_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Link an Odoo MO chain to a local order (or create a new one).

    Any MO of a backorder chain may be given: the ROOT MO is resolved and stored,
    so links stay stable across splits. ``odoo_state`` is set from the chain and
    ``sync_mode`` is never changed here (link_only unless promoted explicitly).
    """
    mo = client.search_read(
        "mrp.production",
        [["id", "=", odoo_mo_id]],
        MO_LINK_FIELDS,
        limit=1,
    )
    if not mo:
        raise ValueError(f"Odoo MO {odoo_mo_id} not found")
    mo = mo[0]
    box_type = _box_type_from_odoo(client, mo.get("product_id"))
    name = str(mo.get("name") or "").strip()
    origin = str(mo.get("origin") or "").strip()

    # Resolve the chain root (backorder_sequence 0, or oldest id in the group).
    root = mo
    group_id = _id_ref(mo.get("procurement_group_id"))
    if group_id:
        chain = client.search_read(
            "mrp.production",
            [["procurement_group_id", "=", group_id]],
            ["id", "name", "backorder_sequence"],
        )
        if chain:
            root = min(chain, key=lambda m: (int(m.get("backorder_sequence") or 0), m["id"]))
    root_id = int(root["id"])
    root_name = str(root.get("name") or name)

    status = client.chain_status(root_id)
    state = status.get("state") or "open"
    current = status.get("open_mo_id")

    po = None
    if local_mo_id:
        po = session.get(models.PurchaseOrder, local_mo_id)
        if po is None:
            raise ValueError(f"Local MO {local_mo_id} not found")
    else:
        po_number = origin or name or f"MO-{root_id}"
        po = models.PurchaseOrder(
            po_number=po_number,
            diameter=0.0, length=0.0, pd=0.0, cu=0, weight=0.0, box_type=0,
            acetate_type="", paper_type="", pva_glue_type="", hm_glue_type="",
            triacetin_type="", target_qty=int(float(mo.get("product_qty") or 0)),
            produced_qty=0,
        )
        session.add(po)
        session.flush()

    # Additive only: never silently re-point an existing link or steal an MO.
    if po.odoo_mo_id not in (None, root_id):
        raise ValueError(
            f"Order {po.id} is already linked to Odoo MO {po.odoo_mo_id}"
        )
    taken = (
        session.query(models.PurchaseOrder)
        .filter(
            models.PurchaseOrder.odoo_mo_id == root_id,
            models.PurchaseOrder.id != po.id,
        )
        .first()
    )
    if taken is not None:
        raise ValueError(f"Odoo MO {root_id} is already linked to order {taken.id}")

    po.odoo_mo_id = root_id
    po.odoo_mo_name = root_name
    po.odoo_current_mo_id = int(current) if current else None
    po.odoo_state = state
    po.source = "odoo"
    po.odoo_linked_at = datetime.now(timezone.utc)
    if box_type:
        po.box_type = box_type
    # Linking never enables posting: sync_mode keeps its value (default link_only)
    # and is promoted explicitly via PUT /orders/{id}/sync-mode.
    session.commit()

    return {
        "odoo_mo_id": root_id,
        "local_mo_id": po.id,
        "mo_number": po.po_number,
        "odoo_mo_name": root_name,
        "odoo_state": state,
        "sync_mode": po.sync_mode,
    }
