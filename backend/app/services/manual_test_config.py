"""Per-machine manual QC test configuration (pure, no DB / framework imports).

Each manual quality parameter carries two flags:

  * ``is_visible``  - show the field to the operator
  * ``is_required`` - block submission when the field is empty

The stored ``machines.manual_test_config`` JSONB is optional and may be partial;
the effective config is always the factory default merged with what is stored.
Keeping this module pure lets the operator app mirror the exact same defaults
and lets unit tests run without a database.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Canonical, ordered list of manual QC parameters. ``kind`` drives the operator
# UI: "weight" (grams for N rods), "numeric" (mm / %), "toggle" (OK/FAIL) and
# "triacetin" (wet mg / dry mg / rods -> computed %).
PARAMETERS: List[Dict[str, str]] = [
    {"key": "weight", "label": "Weight", "kind": "weight"},
    {"key": "length", "label": "Length", "kind": "numeric"},
    {"key": "hardness", "label": "Hardness", "kind": "numeric"},
    {"key": "glue_seam", "label": "Glue Seam", "kind": "toggle"},
    {"key": "cut_quality", "label": "Cut Quality", "kind": "toggle"},
    {"key": "visual_cleanness", "label": "Visual Cleanness", "kind": "toggle"},
    {"key": "triacetin", "label": "Triacetin", "kind": "triacetin"},
]

PARAMETER_KEYS: List[str] = [p["key"] for p in PARAMETERS]


def default_config() -> Dict[str, Dict[str, bool]]:
    """Factory default: every parameter visible, none required."""
    return {key: {"is_visible": True, "is_required": False} for key in PARAMETER_KEYS}


def effective_config(stored: Any) -> Dict[str, Dict[str, bool]]:
    """Merge a (possibly partial/None) stored config over the defaults."""
    base = default_config()
    if isinstance(stored, dict):
        for key, flags in stored.items():
            if key not in base or not isinstance(flags, dict):
                continue
            merged = dict(base[key])
            if isinstance(flags.get("is_visible"), bool):
                merged["is_visible"] = flags["is_visible"]
            if isinstance(flags.get("is_required"), bool):
                merged["is_required"] = flags["is_required"]
            base[key] = merged
    return base


def sanitize_config(raw: Any) -> Dict[str, Dict[str, bool]]:
    """Keep only valid keys/boolean flags for storage (empty dict when none)."""
    clean: Dict[str, Dict[str, bool]] = {}
    if isinstance(raw, dict):
        for key, flags in raw.items():
            if key not in PARAMETER_KEYS or not isinstance(flags, dict):
                continue
            entry: Dict[str, bool] = {}
            if isinstance(flags.get("is_visible"), bool):
                entry["is_visible"] = flags["is_visible"]
            if isinstance(flags.get("is_required"), bool):
                entry["is_required"] = flags["is_required"]
            if entry:
                clean[key] = entry
    return clean
