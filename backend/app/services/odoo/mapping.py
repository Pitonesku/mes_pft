"""Guided MES material <-> Odoo product mapping (Phase 1).

Name matching only ever produces *suggestions*; a mapping is written solely by an
explicit confirm call (``confirm_mapping``). Existing links are never overwritten
without ``force`` (invariant #2: additive only).

Matching strategy (v2, after the real-data audit):
  * acetate    - compare the grade code (e.g. ``3.0Y30000``), ignoring HK/weights
  * paper      - compare width mm + bobbin length m (e.g. ``27mm / 6000m``)
  * glue       - compare the product code (e.g. ``5067-1``), fallback tokens
  * triacetin  - no key; manual pick only (names never overlap)
  * everything else gets a token-overlap fallback with a minimum score, and
    products Odoo cannot classify never rank unless they share real tokens.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app import models
from app.services.odoo.client import OdooClient, _id_ref
from app.services.odoo.inbound import _classify_material, normalize_material_name

MAPPABLE_CATEGORIES = ("acetate", "paper", "triacetin", "glue")

_GRADE_RE = re.compile(r"\b(\d+(?:[.,]\d+)?[yY]\d+)")
_PAPER_SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*mm\s*/\s*(\d+)\s*m", re.IGNORECASE)
_GLUE_CODE_RE = re.compile(r"\b(\d{2,6}-\d)\b")

# Fallback score below which a suggestion is considered noise and dropped.
MIN_SCORE = 0.5


def _normalize_grade(grade: str) -> str:
    return grade.lower().replace(",", ".").rstrip("hk").strip()


def _paper_key(name: str) -> Optional[Tuple[str, str]]:
    m = _PAPER_SIZE_RE.search(name or "")
    if not m:
        return None
    return m.group(1).replace(",", "."), m.group(2)


def _glue_key(name: str) -> Optional[str]:
    m = _GLUE_CODE_RE.search(name or "")
    return m.group(1) if m else None


def _material_key(category: str, name: str) -> Optional[Any]:
    """Category-specific identity extracted from a material/product name."""
    cat = _normalize_category(category)
    if cat == "acetate":
        m = _GRADE_RE.search(name or "")
        return ("acetate", _normalize_grade(m.group(1))) if m else None
    if cat == "paper":
        key = _paper_key(name)
        return ("paper", key) if key else None
    if cat == "glue":
        code = _glue_key(name)
        return ("glue", code) if code else None
    return None  # triacetin etc: no reliable key


def score_match(local_name: str, odoo_name: str) -> float:
    """0..1 similarity of two normalized names (token overlap, containment boost)."""
    a = normalize_material_name(local_name or "")
    b = normalize_material_name(odoo_name or "")
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    # Containment boost only for non-trivial names: "del" must never score 0.8
    # against "delfort ..." (found in the real-data audit).
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        jaccard = max(jaccard, 0.8)
    return round(jaccard, 3)


def suggest_for_material(
    material: models.MaterialDictionary,
    products: List[Dict[str, Any]],
    limit: int = 3,
    min_score: float = MIN_SCORE,
) -> List[Dict[str, Any]]:
    """Rank Odoo products for one local material; empty list when nothing fits."""
    cat = _normalize_category(material.category or "")
    mat_key = _material_key(cat, material.type_name or "")
    ranked: List[Dict[str, Any]] = []
    for prod in products:
        name = str(prod.get("display_name") or prod.get("name") or "")
        pcat = _classify_material(name)
        if pcat is not None and _normalize_category(pcat) != cat:
            continue
        pkey = _material_key(cat, name)

        if mat_key is not None and pkey is not None and mat_key == pkey:
            score = 1.0
        elif cat == "paper" and mat_key and pkey:
            width, length = mat_key
            pwidth, plength = pkey
            score = 0.7 if width == pwidth else 0.0
            if score and length == plength:
                score = 1.0
        else:
            score = score_match(material.type_name or "", name)

        # Unclassified Odoo products must earn their place with real tokens.
        if pcat is None and score < 0.5:
            continue
        if score >= min_score:
            ranked.append({
                "odoo_product_id": int(prod["id"]),
                "name": name,
                "uom_id": _id_ref(prod.get("uom_id")),
                "score": score,
            })
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked[:limit]


def _normalize_category(category: str) -> str:
    c = (category or "").lower()
    # MES categories are coldGlue / hotMelt; Odoo classification is 'glue'.
    if c in ("coldglue", "hotmelt", "pva", "hm", "pva_glue", "hm_glue"):
        return "glue"
    if c.startswith("glue"):
        return "glue"
    return c


def fetch_candidate_products(client: OdooClient, limit: int = 2000) -> List[Dict[str, Any]]:
    # 'display_name' is not a stored field: ordering by it raises on Odoo 18.
    return client.search_read(
        "product.product",
        [["active", "=", True]],
        ["id", "display_name", "uom_id"],
        limit=limit,
        order="name asc",
    )


def list_products(
    client: OdooClient,
    category: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Manual-picker feed: Odoo products, optionally filtered by category/name.

    Includes the UoM name and category so the UI can warn about unit mismatches
    (e.g. paper consumed in bobbins vs a product sold in kg).
    """
    products = fetch_candidate_products(client)
    wanted = _normalize_category(category) if category else None
    needle = (q or "").strip().lower()
    rows: List[Dict[str, Any]] = []
    for p in products:
        name = str(p.get("display_name") or p.get("name") or "")
        pcat = _classify_material(name)
        if wanted and (pcat is None or _normalize_category(pcat) != wanted):
            continue
        if needle and needle not in name.lower():
            continue
        rows.append({"id": int(p["id"]), "name": name, "uom_id": _id_ref(p.get("uom_id"))})
        if len(rows) >= limit:
            break

    uom_ids = {r["uom_id"] for r in rows if r.get("uom_id")}
    uom_info: Dict[int, Dict[str, str]] = {}
    if uom_ids:
        uoms = client.search_read(
            "uom.uom", [["id", "in", list(uom_ids)]], ["id", "name", "category_id"], limit=500
        )
        cat_ids = {_id_ref(u.get("category_id")) for u in uoms if _id_ref(u.get("category_id"))}
        cat_names: Dict[int, str] = {}
        if cat_ids:
            cats = client.search_read(
                "uom.category", [["id", "in", list(cat_ids)]], ["id", "name"], limit=200
            )
            cat_names = {int(c["id"]): str(c.get("name") or "") for c in cats}
        uom_info = {
            int(u["id"]): {
                "name": str(u.get("name") or ""),
                "category": cat_names.get(_id_ref(u.get("category_id")) or 0, ""),
            }
            for u in uoms
        }

    for r in rows:
        info = uom_info.get(r["uom_id"], {})
        r["uom_name"] = info.get("name", "")
        r["uom_category"] = info.get("category", "")
    return rows


def build_mapping_overview(
    session: Session,
    products: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Local materials with link state + suggestions; unmapped BOM components."""
    materials = (
        session.query(models.MaterialDictionary)
        .filter((models.MaterialDictionary.is_hidden.is_(None)) | (models.MaterialDictionary.is_hidden.is_(False)))
        .order_by(models.MaterialDictionary.category, models.MaterialDictionary.type_name)
        .all()
    )
    rows = []
    for m in materials:
        rows.append({
            "material_id": m.id,
            "category": m.category,
            "type_name": m.type_name,
            "odoo_product_id": m.odoo_product_id,
            "odoo_uom_id": m.odoo_uom_id,
            "source": m.source,
            "mapped": m.odoo_product_id is not None,
            "suggestions": (
                [] if (m.odoo_product_id is not None or products is None)
                else suggest_for_material(m, products)
            ),
        })

    unmapped = (
        session.query(models.ProductionRunComponent)
        .filter(models.ProductionRunComponent.material_id.is_(None))
        .all()
    )
    seen = set()
    unmapped_components = []
    for c in unmapped:
        key = (c.category, c.product_name)
        if key in seen:
            continue
        seen.add(key)
        unmapped_components.append({"category": c.category, "product_name": c.product_name})

    return {
        "materials": rows,
        "unmapped_components": unmapped_components,
        "mapped_count": sum(1 for r in rows if r["mapped"]),
        "total": len(rows),
    }


def confirm_mapping(
    session: Session,
    material_id: int,
    odoo_product_id: Optional[int],
    odoo_uom_id: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Explicitly link (or, with ``odoo_product_id=None`` and force, unlink) a material."""
    material = session.get(models.MaterialDictionary, material_id)
    if material is None:
        raise ValueError(f"Material {material_id} not found")

    if odoo_product_id is None:
        if not force:
            raise ValueError("force=true is required to remove a mapping")
        material.odoo_product_id = None
        material.odoo_uom_id = None
        session.commit()
        return {"material_id": material.id, "odoo_product_id": None}

    if material.odoo_product_id not in (None, int(odoo_product_id)) and not force:
        raise ValueError(
            f"Material {material_id} is already mapped to Odoo product "
            f"{material.odoo_product_id}; pass force=true to change it"
        )
    clash = (
        session.query(models.MaterialDictionary)
        .filter(
            models.MaterialDictionary.odoo_product_id == int(odoo_product_id),
            models.MaterialDictionary.id != material.id,
        )
        .first()
    )
    if clash is not None and not force:
        raise ValueError(
            f"Odoo product {odoo_product_id} is already mapped to material {clash.id}"
        )

    material.odoo_product_id = int(odoo_product_id)
    if odoo_uom_id is not None:
        material.odoo_uom_id = int(odoo_uom_id)
    material.source = "odoo"
    session.commit()
    return {
        "material_id": material.id,
        "odoo_product_id": material.odoo_product_id,
        "odoo_uom_id": material.odoo_uom_id,
    }
