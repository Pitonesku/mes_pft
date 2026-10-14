"""Pure evaluation rules for operator manual QC checks (no DB / framework imports).

Operator weighings are entered as **grams per ``sample_rods`` rods** (default 10).
The station/statistics engine works per rod, so a manual value is converted to
grams per rod before it is compared with the spec limits.

Overall status of one check:
  * ``FAIL``  - any measured value outside its limits, or any visual toggle FAIL
  * ``PASS``  - at least one assessed item and nothing failed
  * ``None``  - nothing could be assessed (no limits, toggles not checked)
"""

from __future__ import annotations

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
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return ``(verdicts, overall_status)`` for one manual check."""
    rods = sample_rods if (sample_rods and sample_rods > 0) else DEFAULT_SAMPLE_RODS
    verdicts: Dict[str, Any] = {}
    statuses = []

    if sample_weight is not None:
        per_rod = sample_weight / rods
        nominal, lower, upper = weight_limits_per_rod(specs.get("weight"))
        status = _bounds_status(per_rod, lower, upper)
        verdicts["weight"] = {
            "value": sample_weight,
            "sample_rods": rods,
            "per_rod": round(per_rod, 5),
            "target": nominal, "lower": lower, "upper": upper,
            "status": status,
        }
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
