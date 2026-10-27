"""Pure evaluation rules for operator manual QC checks (no DB / framework imports).

Operator weighings are entered in any common form (grams total for
``sample_rods`` rods, mg per rod, grams per rod, mg total) and are normalised to
grams per rod before being compared with the spec limits. Values outside the
3x-tolerance band are marked ``rejected`` (dropped from statistics).

Overall status of one check:
  * ``FAIL``  - any measured value outside its limits, or any visual toggle FAIL
  * ``PASS``  - at least one assessed item and nothing failed
  * ``None``  - nothing could be assessed (no limits, toggles not checked)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from app.quality_stats import ParamSpec

DEFAULT_SAMPLE_RODS = 10

# A single filter rod never weighs more than a few grams. A weight spec whose
# nominal is above this and that carries a ``report_scale`` > 1 is already
# expressed in report units (g / 100 rods, as written by the Odoo importer) and
# must be divided by the scale to get back to g per rod.
_MAX_PLAUSIBLE_ROD_WEIGHT_G = 5.0


def weight_limits_per_rod(spec: Optional[ParamSpec]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Return ``(nominal, lower, upper)`` of a weight spec in grams per rod."""
    if spec is None:
        return None, None, None
    factor = 1.0
    if spec.report_scale and spec.report_scale > 1 and spec.nominal is not None \
            and spec.nominal > _MAX_PLAUSIBLE_ROD_WEIGHT_G:
        factor = 1.0 / spec.report_scale
    def conv(v: Optional[float]) -> Optional[float]:
        return None if v is None else v * factor
    return conv(spec.nominal), conv(spec.lower), conv(spec.upper)


# Broad per-rod detection band (grams). Wider than the 300-700 mg spec so a real
# outlier (e.g. 720 mg) is still DETECTED and then rejected by the 3x-tolerance
# rule instead of being reported as "unparseable"; narrow enough that the four
# unit bands stay disjoint for realistic sample sizes (>= 5 rods).
_PER_ROD_MIN_G = 0.2   # 200 mg
_PER_ROD_MAX_G = 1.0   # 1000 mg

# No-spec disambiguation priority: the most common operator entries first.
_UNIT_PRIORITY = {"g_total": 0, "mg_per_rod": 1, "g_per_rod": 2, "mg_total": 3}


@dataclass(frozen=True)
class NormalizedWeight:
    """Result of interpreting a raw operator weight entry."""

    ok: bool
    per_rod_g: Optional[float]
    total_g: Optional[float]
    unit: Optional[str]
    error: Optional[str] = None


def _parse_number(raw: Any) -> Optional[float]:
    """Parse a numeric string/float; comma decimal separator and g/mg suffix OK."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip().replace(" ", "").replace(",", ".")
        text = re.sub(r"(?i)(g|mg)$", "", text)
        try:
            value = float(text)
        except ValueError:
            return None
    return None if math.isnan(value) or math.isinf(value) else value


def normalize_manual_weight(
    raw: Any,
    sample_rods: Optional[int],
    spec: Optional[ParamSpec] = None,
) -> NormalizedWeight:
    """Interpret a raw operator weight entry into grams per rod.

    The operator may type the same physical result several ways (a filter rod is
    300-700 mg, i.e. 0.3-0.7 g):

      * ``6,67``  -> 6.67 g total for ``sample_rods`` rods (default 10)
      * ``667``   -> 667 mg per rod
      * ``33,8``  -> 33.8 g total for 50 rods
      * ``6670``  -> 6670 mg total for 10 rods

    Returns the canonical per-rod grams and ``total_g`` (= per-rod g x rods). The
    rod count is essential: the same digits mean different things for 10 vs 50
    rods. ``ok`` is False (with ``error``) when the value is ambiguous.
    """
    value = _parse_number(raw)
    if value is None:
        return NormalizedWeight(False, None, None, None, "Enter a valid weight number")
    rods = sample_rods if (sample_rods and sample_rods > 0) else DEFAULT_SAMPLE_RODS

    candidates = [
        ("g_per_rod", value),
        ("mg_per_rod", value / 1000.0),
        ("g_total", value / rods),
        ("mg_total", value / (1000.0 * rods)),
    ]
    plausible = [
        (unit, per_rod)
        for unit, per_rod in candidates
        if _PER_ROD_MIN_G <= per_rod <= _PER_ROD_MAX_G
    ]
    if not plausible:
        return NormalizedWeight(False, None, None, None, _ambiguity_message(value, rods, spec))

    if len(plausible) > 1:
        nominal, _, _ = weight_limits_per_rod(spec)
        if nominal is not None:
            plausible.sort(key=lambda item: abs(item[1] - nominal))
        else:
            plausible.sort(key=lambda item: _UNIT_PRIORITY.get(item[0], 9))

    unit, per_rod = plausible[0]
    return NormalizedWeight(True, per_rod, per_rod * rods, unit, None)


def _ambiguity_message(value: float, rods: int, spec: Optional[ParamSpec]) -> str:
    lo_mg, hi_mg = 300.0, 700.0
    if spec is not None:
        _, lower, upper = weight_limits_per_rod(spec)
        if lower is not None:
            lo_mg = lower * 1000.0
        if upper is not None:
            hi_mg = upper * 1000.0
    lo_g = round(lo_mg * rods / 1000.0, 2)
    hi_g = round(hi_mg * rods / 1000.0, 2)
    return (
        f"Couldn't interpret weight {value} for {rods} rods. Expected either "
        f"{lo_g}-{hi_g} g total for {rods} rods or {int(lo_mg)}-{int(hi_mg)} mg "
        f"per rod. Check the rod count."
    )


def _bounds_status(value: float, lower: Optional[float], upper: Optional[float]) -> Optional[str]:
    if lower is None and upper is None:
        return None
    if lower is not None and value < lower:
        return "FAIL"
    if upper is not None and value > upper:
        return "FAIL"
    return "PASS"


def evaluate(
    specs: Mapping[str, ParamSpec],
    *,
    sample_weight: Optional[float],
    sample_rods: Optional[int],
    length_mm: Optional[float],
    hardness: Optional[float],
    glue_seam_ok: Optional[bool],
    cut_quality_ok: Optional[bool],
    visual_appearance_ok: Optional[bool],
    triacetin_pct: Optional[float] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return ``(verdicts, overall_status)`` for one manual check."""
    rods = sample_rods if (sample_rods and sample_rods > 0) else DEFAULT_SAMPLE_RODS
    verdicts: Dict[str, Any] = {}
    statuses = []

    if sample_weight is not None:
        spec = specs.get("weight")
        norm = normalize_manual_weight(sample_weight, rods, spec)
        if norm.ok:
            per_rod = norm.per_rod_g
            value = round(norm.total_g, 6)
        else:
            # Unparseable / ambiguous: keep the legacy interpretation (total
            # grams) so the verdict still exposes the offending value, and
            # surface the reason for the route to reject the check.
            per_rod = sample_weight / rods
            value = sample_weight
        nominal, lower, upper = weight_limits_per_rod(spec)
        status = _bounds_status(per_rod, lower, upper)

        # 3x-tolerance rejection band (matches the station rod-rejection rule),
        # computed from the same g/rod limits used for PASS/FAIL.
        reject_low = None
        reject_high = None
        if spec is not None:
            multiplier = spec.reject_multiplier
            if multiplier is not None and nominal is not None:
                reject_low = None if lower is None else nominal - multiplier * (nominal - lower)
                reject_high = None if upper is None else nominal + multiplier * (upper - nominal)
        rejected = (
            (reject_low is not None and per_rod < reject_low)
            or (reject_high is not None and per_rod > reject_high)
        )

        verdicts["weight"] = {
            "value": value,
            "sample_rods": rods,
            "per_rod": round(per_rod, 5),
            "unit": norm.unit,
            "target": nominal, "lower": lower, "upper": upper,
            "reject_low": reject_low, "reject_high": reject_high,
            "rejected": rejected,
            "status": status,
        }
        if norm.error:
            verdicts["weight"]["error"] = norm.error
        statuses.append(status)

    if length_mm is not None:
        spec = specs.get("length")
        lower = spec.lower if spec else None
        upper = spec.upper if spec else None
        status = _bounds_status(length_mm, lower, upper)
        verdicts["length"] = {
            "value": length_mm,
            "target": spec.nominal if spec else None,
            "lower": lower, "upper": upper, "status": status,
        }
        statuses.append(status)

    if hardness is not None:
        spec = specs.get("hardness")
        lower = spec.lower if spec else None
        upper = spec.upper if spec else None
        status = _bounds_status(hardness, lower, upper)
        verdicts["hardness"] = {
            "value": hardness,
            "target": spec.nominal if spec else None,
            "lower": lower, "upper": upper, "status": status,
        }
        statuses.append(status)

    if triacetin_pct is not None:
        spec = specs.get("triacetin")
        lower = spec.lower if spec else None
        upper = spec.upper if spec else None
        status = _bounds_status(triacetin_pct, lower, upper)
        verdicts["triacetin"] = {
            "value": triacetin_pct,
            "target": spec.nominal if spec else None,
            "lower": lower, "upper": upper, "status": status,
        }
        statuses.append(status)

    for key, flag in (
        ("glue_seam", glue_seam_ok),
        ("cut_quality", cut_quality_ok),
        ("visual_appearance", visual_appearance_ok),
    ):
        if flag is None:
            continue
        status = "PASS" if flag else "FAIL"
        verdicts[key] = {"status": status}
        statuses.append(status)

    assessed = [s for s in statuses if s is not None]
    if "FAIL" in assessed:
        return verdicts, "FAIL"
    if assessed:
        return verdicts, "PASS"
    return verdicts, None
