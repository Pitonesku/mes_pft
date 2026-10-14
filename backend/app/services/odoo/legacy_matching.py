"""Pure matching of operator shift reports to the Manufacturing Orders of an Odoo
backorder chain (no DB / Odoo imports, unit-tested).

Each shift report's ``produced_rods`` equals the quantity of exactly one backorder
(the shift's completion posted in Odoo). The match key is therefore the exact rod
quantity; anything that is not a clean one-to-one pair is returned for manual review
instead of being guessed.
"""

from collections import defaultdict
from typing import Any, Dict, List, Tuple


def match_reports_to_mos(
    reports: List[Dict[str, Any]],
    mos: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """``reports``: ``{"id", "rods", "date", "machine", "shift"}`` (date/machine/shift
    optional); ``mos``: ``{"id", "name", "rods", "state", "seq"}`` (seq optional).

    Rules:
    1. Exact duplicate reports (same date+machine+shift+rods) collapse to one — a shift
       report submitted several times must not be treated as several shifts.
    2. One report <-> one MO by exact rod quantity.
    3. N reports <-> N MOs sharing one quantity are paired deterministically: reports by
       (machine, date, id), MOs by backorder sequence (M1 -> lower seq, M2 -> higher seq).
    4. Anything else is returned for manual review, never guessed.

    Returns ``{"pairs", "ambiguous", "unmatched_reports", "unmatched_mos", "deduped"}``.
    """
    seen: Dict[tuple, int] = {}
    deduped_reports: List[Dict[str, Any]] = []
    dedup_count = 0
    for r in reports:
        key = (r.get("date"), r.get("machine"), r.get("shift"), int(round(r["rods"])))
        if key in seen:
            dedup_count += 1
            continue
        seen[key] = r["id"]
        deduped_reports.append(r)

    done = [m for m in mos if m.get("state") == "done"]
    by_qty_mo: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for m in done:
        by_qty_mo[int(round(m["rods"]))].append(m)
    by_qty_rep: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in deduped_reports:
        by_qty_rep[int(round(r["rods"]))].append(r)

    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    ambiguous: List[Dict[str, Any]] = []
    used_mo = set()
    used_rep = set()
    for qty, reps in by_qty_rep.items():
        cands = by_qty_mo.get(qty, [])
        if len(reps) == 1 and len(cands) == 1:
            pairs.append((reps[0], cands[0]))
            used_rep.add(reps[0]["id"])
            used_mo.add(cands[0]["id"])
        elif len(reps) == len(cands) and len(reps) > 1:
            reps_sorted = sorted(reps, key=lambda r: (r.get("machine") or "",
                                                      r.get("date") or "", r["id"]))
            cands_sorted = sorted(cands, key=lambda m: (m.get("seq") or 0, m["id"]))
            for r, m in zip(reps_sorted, cands_sorted):
                pairs.append((r, m))
                used_rep.add(r["id"])
                used_mo.add(m["id"])
        elif reps and cands:
            ambiguous.append({
                "rods": qty,
                "reports": [r["id"] for r in reps],
                "mos": [m["name"] for m in cands],
            })
            used_rep.update(r["id"] for r in reps)
            used_mo.update(m["id"] for m in cands)
    return {
        "pairs": pairs,
        "ambiguous": ambiguous,
        "unmatched_reports": [r for r in deduped_reports if r["id"] not in used_rep],
        "unmatched_mos": [m for m in done if m["id"] not in used_mo],
        "deduped": dedup_count,
    }


def csv_rows(rods: List[Dict[str, Any]]) -> List[List[Any]]:
    """Rod dicts -> CSV rows (header first) for the Odoo measurements attachment."""
    header = ["measured_at", "rod_no", "machine", "diameter", "pd", "weight",
              "ovality", "roundness", "shape", "hardness"]
    out: List[List[Any]] = [header]
    for r in rods:
        out.append([r.get(k) if r.get(k) is not None else "" for k in header])
    return out
