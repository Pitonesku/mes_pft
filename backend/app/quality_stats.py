"""
Quality statistics for one production run (one Manufacturing Order within a shift).

Pure Python, no database and no framework imports, so it can be unit-tested in
isolation and reused by the shift-close aggregation, the certificate renderer and
the Odoo payload builder.

Rules implemented (taken from the Grafana quality dashboard and the customer
certificates E050 / H087):

* Limits are a nominal plus a lower and an upper limit. They may be asymmetric
  (certificate: pressure drop 325, limits 310..350) and either limit may be
  missing (certificate: hardness has a lower limit only).
* Rod rejection (dashboard "3x tolerance" rule): when a parameter has a
  ``reject_multiplier`` m, a rod is rejected if its value is outside
  ``nominal - m*(nominal-lower) .. nominal + m*(upper-nominal)``.
  A rejected rod is dropped from EVERY statistic of the run (the dashboard drops
  the whole rod, not one column) and is only counted.
* "Out of spec" differs from "rejected": a rod outside the lower/upper limit but
  inside the rejection band stays in mean / SD and lowers the pass rate.
* Both sample SD (n-1: instrument and certificates) and population SD (old
  dashboard) are returned. ``sd_samp`` is None when fewer than 2 rods exist.
* Hardness and length are not measured by the station: they report NOT_MEASURED
  unless a manual value is passed to ``certificate_rows``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_NOT_MEASURED = "NOT_MEASURED"
STATUS_NO_DATA = "NO_DATA"


@dataclass(frozen=True)
class ParamSpec:
    """Acceptance limits for one parameter, in the *measurement* unit.

    ``report_scale`` / ``report_unit`` / ``decimals`` only affect
    ``certificate_rows`` (weight is measured in g per rod but certified in g per
    100 rods, so report_scale is 100).
    """

    parameter: str
    nominal: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    reject_multiplier: Optional[float] = None
    report_unit: str = ""
    report_scale: float = 1.0
    decimals: int = 3

    def reject_bounds(self) -> Tuple[Optional[float], Optional[float]]:
        """Return (low, high) of the rejection band; a side is None when open."""
        if self.reject_multiplier is None or self.nominal is None:
            return None, None
        low = None if self.lower is None else self.nominal - self.reject_multiplier * (self.nominal - self.lower)
        high = None if self.upper is None else self.nominal + self.reject_multiplier * (self.upper - self.nominal)
        return low, high


def _num(value: Any) -> Optional[float]:
    """Convert a raw value (float, Decimal, numeric string) to float, else None."""
    if value is None:
        return None
    try:
        if isinstance(value, str):
            f = float(value.replace(" ", "").replace(",", "."))
        else:
            f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _describe(values: Sequence[float]) -> Dict[str, Optional[float]]:
    n = len(values)
    mean = math.fsum(values) / n
    ss = math.fsum((v - mean) ** 2 for v in values)
    return {
        "n": n,
        "mean": mean,
        "sd_pop": math.sqrt(ss / n),
        "sd_samp": math.sqrt(ss / (n - 1)) if n > 1 else None,
        "min": min(values),
        "max": max(values),
    }


def overall_status(parameters: Mapping[str, Mapping[str, Any]]) -> str:
    """Worst parameter status; NO_DATA when nothing was measured at all."""
    statuses = [p.get("status") for p in parameters.values()]
    if STATUS_FAIL in statuses:
        return STATUS_FAIL
    if STATUS_WARN in statuses:
        return STATUS_WARN
    if STATUS_PASS in statuses:
        return STATUS_PASS
    return STATUS_NO_DATA


def compute_run_stats(
    rods: Sequence[Mapping[str, Any]],
    specs: Mapping[str, ParamSpec],
    last_n: Optional[int] = None,
) -> Dict[str, Any]:
    """Aggregate the rods of one run.

    ``rods`` must be in chronological order. Each rod is a mapping keyed by
    parameter name (``pd``, ``weight``, ``diameter`` ...); missing or non-numeric
    values are ignored for that parameter only.

    ``last_n`` reproduces the dashboard's rolling window: only the last N rods are
    considered, and rejected rods still count towards N (as in the old SQL).
    """
    window = list(rods)
    if last_n is not None and last_n > 0:
        window = window[-last_n:]

    kept = [r for r in window if not _is_rejected(r, specs)]

    parameters: Dict[str, Dict[str, Any]] = {}
    for name, spec in specs.items():
        values = [v for v in (_num(r.get(name)) for r in kept) if v is not None]
        entry: Dict[str, Any] = {"nominal": spec.nominal, "lower": spec.lower, "upper": spec.upper}
        if not values:
            entry.update({"status": STATUS_NOT_MEASURED, "n": 0})
        else:
            entry.update(_describe(values))
            out_of_spec = sum(
                1
                for v in values
                if (spec.lower is not None and v < spec.lower) or (spec.upper is not None and v > spec.upper)
            )
            entry["out_of_spec"] = out_of_spec
            entry["pass_rate"] = 1.0 - out_of_spec / len(values)
            entry["status"] = _param_status(entry["mean"], out_of_spec, spec)
        parameters[name] = entry

    return {
        "rods_total": len(window),
        "rods_rejected": len(window) - len(kept),
        "rods_used": len(kept),
        "status": overall_status(parameters),
        "parameters": parameters,
    }


def _scaled(value: Optional[float], spec: ParamSpec) -> Optional[float]:
    return None if value is None else round(value * spec.report_scale, spec.decimals)


def certificate_rows(
    stats: Mapping[str, Any],
    specs: Mapping[str, ParamSpec],
    manual: Optional[Mapping[str, Mapping[str, Optional[float]]]] = None,
    sd_kind: str = "samp",
) -> List[Dict[str, Any]]:
    """Build the parameter table of the quality certificate, one row per spec.

    * Values are converted to report units (``report_scale``) and rounded.
    * ``sd_kind`` is ``"samp"`` (n-1, default) or ``"pop"``.
    * ``manual`` supplies hand-entered results (hardness, length: not measured by
      the station) as ``{"hardness": {"mean": 84.4, "sd": None}}``, already in
      report units. It is used only when a parameter has no measured data, so a
      measurement can never be silently overwritten.
    """
    if sd_kind not in ("samp", "pop"):
        raise ValueError("sd_kind must be 'samp' or 'pop'")
    manual = manual or {}
    rows: List[Dict[str, Any]] = []
    for name, spec in specs.items():
        measured = stats.get("parameters", {}).get(name, {})
        row: Dict[str, Any] = {
            "parameter": name,
            "unit": spec.report_unit,
            "nominal": _scaled(spec.nominal, spec),
            "lower": _scaled(spec.lower, spec),
            "upper": _scaled(spec.upper, spec),
        }
        if measured.get("n"):
            row.update(
                {
                    "mean": _scaled(measured["mean"], spec),
                    "sd": _scaled(measured.get(f"sd_{sd_kind}"), spec),
                    "n": measured["n"],
                    "source": "measured",
                    "status": measured["status"],
                }
            )
        elif name in manual:
            m = manual[name]
            row.update(
                {"mean": m.get("mean"), "sd": m.get("sd"), "n": None,
                 "source": "manual", "status": STATUS_NOT_MEASURED}
            )
        else:
            row.update({"mean": None, "sd": None, "n": 0, "source": "not_measured",
                        "status": STATUS_NOT_MEASURED})
        rows.append(row)
    return rows



def _is_rejected(rod: Mapping[str, Any], specs: Mapping[str, ParamSpec]) -> bool:
    for name, spec in specs.items():
        low, high = spec.reject_bounds()
        if low is None and high is None:
            continue
        value = _num(rod.get(name))
        if value is None:
            continue
        if (low is not None and value < low) or (high is not None and value > high):
            return True
    return False


def _param_status(mean: float, out_of_spec: int, spec: ParamSpec) -> str:
    if (spec.lower is not None and mean < spec.lower) or (spec.upper is not None and mean > spec.upper):
        return STATUS_FAIL
    return STATUS_WARN if out_of_spec > 0 else STATUS_PASS
