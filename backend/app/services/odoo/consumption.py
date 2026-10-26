"""Extract material consumption from verified operator reports (Phase 3 write-back).

Pure functions - no DB, no Odoo - so they are unit-testable and reusable by the
dispatcher. The operator report stores per-batch consumption in ``materials_json``
under five lists: ``acetate_list``, ``paper_list``, ``pva_list``, ``hm_list`` and
``tri_list``. Each item is ``{"type": ..., "batch": ..., "used": float, ...}``.

The raw units are kg for acetate/glue/triacetin and *bobbins* for paper (a bobbin
length such as "6000m" is embedded in the material type name).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# canonical category per materials_json list key
_LIST_TO_CATEGORY = {
    "acetate_list": "acetate",
    "paper_list": "paper",
    "pva_list": "coldGlue",
    "hm_list": "hotMelt",
    "tri_list": "triacetin",
}

_BOB_LENGTH_RE = re.compile(r"/(\d{3,6})\s*m\b", re.IGNORECASE)


def parse_report_consumption(report: Any) -> List[Dict[str, Any]]:
    """Return per-item consumption ``[{category, type_name, used, batch, unit}]``."""
    raw = getattr(report, "materials_json", None)
    if not raw:
        return []
    try:
        import json
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return []

    items: List[Dict[str, Any]] = []
    for key, category in _LIST_TO_CATEGORY.items():
        entries = data.get(key) or []
        unit = "bob" if category == "paper" else "kg"
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("type") or entry.get("material_type") or "").strip()
            used = entry.get("used")
            if used is None:
                try:
                    used = float(entry.get("start", 0) or 0) - float(entry.get("stop", 0) or 0)
                except (TypeError, ValueError):
                    used = 0.0
            try:
                used_f = float(used)
            except (TypeError, ValueError):
                used_f = 0.0
            # Zero is meaningful for the five direct materials: it must be written
            # to Odoo as an explicit 0 so Odoo does NOT auto-consume from the BOM.
            # Negative values are treated as "not reported".
            if used_f < 0:
                continue
            items.append({
                "category": category,
                "type_name": name,
                "used": used_f,
                "unit": unit,
                "batch": str(entry.get("batch") or "").strip(),
            })
    return items


def aggregate_consumption(reports: List[Any]) -> List[Dict[str, Any]]:
    """Sum consumption across all (approved) reports, merging equal type.

    Multi-batch entries of the same material are summed into a single total so
    each material is written to Odoo once (the batch label is kept for reference).
    """
    merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str, str]] = []
    for report in reports:
        for item in parse_report_consumption(report):
            key = (item["category"], item["type_name"], item["unit"])
            if key not in merged:
                order.append(key)
                merged[key] = {"used": 0.0, "batch": item["batch"]}
            merged[key]["used"] += item["used"]
            if not merged[key]["batch"] and item["batch"]:
                merged[key]["batch"] = item["batch"]
    return [
        {
            "category": c,
            "type_name": t,
            "used": merged[(c, t, u)]["used"],
            "unit": u,
            "batch": merged[(c, t, u)]["batch"],
        }
        for (c, t, u) in order
    ]


def bobbin_length_metres(type_name: str) -> Optional[float]:
    """Parse the per-bobbin length (metres) from a paper type name, or None.

    e.g. "Delfort 21.5mm/6000m" -> 6000.0.
    """
    m = _BOB_LENGTH_RE.search(type_name or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None
