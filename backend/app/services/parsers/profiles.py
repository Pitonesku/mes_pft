"""Per-station parser profile resolution.

A station may emit files with a different column order or a different set of
parameters (e.g. no weight, hardness instead). ``station_profiles`` rows hold the
overrides keyed by a station identifier; the effective mapping is resolved here
and handed to ``QuantumCsvParser``.

Resolution priority (first match wins): instrument_id -> maker -> team, all
scoped by ``source``. No match -> the built-in Quantum Neo default.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app import models
from app.quality_stats import _describe
from app.services.parsers.quantum_csv import ParsedSample, parse_bytes

_MATCH_PRIORITY = ("instrument_id", "maker", "team")


def resolve_profile(
    session: Session,
    source: str,
    instrument_id: str = "",
    maker: str = "",
    team: str = "",
) -> Optional[models.StationProfile]:
    """Return the best-matching StationProfile row, or None."""
    values = {"instrument_id": instrument_id, "maker": maker, "team": team}
    for key in _MATCH_PRIORITY:
        value = (values.get(key) or "").strip()
        if not value:
            continue
        profile = (
            session.query(models.StationProfile)
            .filter(
                models.StationProfile.source == source,
                models.StationProfile.match_key == key,
                models.StationProfile.match_value == value,
            )
            .first()
        )
        if profile is not None:
            return profile
    return None


def profile_to_parser_kwargs(profile: Optional[models.StationProfile]) -> Dict[str, Any]:
    """Build the subset of QuantumCsvParser kwargs a profile overrides."""
    if profile is None:
        return {}
    kwargs: Dict[str, Any] = {}
    if profile.data_start_row is not None:
        kwargs["data_start_row"] = profile.data_start_row
    if profile.encoding:
        kwargs["encoding"] = profile.encoding
    if profile.metadata_map:
        kwargs["metadata_map"] = dict(profile.metadata_map)
    if profile.column_map:
        kwargs["column_map"] = {k: v for k, v in profile.column_map.items()}
    custom_fields = getattr(profile, "custom_fields", None)
    if custom_fields:
        kwargs["custom_fields"] = list(custom_fields)
    if profile.mo_field:
        kwargs["mo_field"] = profile.mo_field
    return kwargs


def parse_file_with_profile(
    session: Session,
    data: bytes,
    source: str = "quantum_neo",
    default_mo_field: str = "batch_description",
) -> Tuple[ParsedSample, Optional[models.StationProfile]]:
    """Parse station bytes, applying the per-station profile when one matches.

    A first pass parses with defaults to learn the station identifiers; a second
    pass re-parses with the profile overrides when a profile exists. Files are
    small (hundreds of rods), so the double parse is negligible.
    """
    first = parse_bytes(data, mo_field=default_mo_field)
    profile = resolve_profile(session, source, first.instrument_id, first.maker, first.team)
    if profile is None:
        return first, None
    kwargs = profile_to_parser_kwargs(profile)
    kwargs.setdefault("mo_field", default_mo_field)
    return parse_bytes(data, **kwargs), profile


def compute_custom_metrics(sample: ParsedSample, profile) -> Optional[Dict[str, Any]]:
    """Aggregate configured custom fields into ``{label: {n, mean, sd_samp, sd_pop, min, max, unit}}``.

    Pure aggregation over the already-parsed rods; the values were captured per
    rod into ``Rod.extra`` during parsing using each field's column index.
    """
    fields = getattr(profile, "custom_fields", None) if profile is not None else None
    if not fields:
        return None
    out: Dict[str, Any] = {}
    for cf in fields:
        if not isinstance(cf, dict):
            continue
        label = (cf.get("label") or "").strip()
        if not label:
            continue
        values = [r.extra.get(label) for r in sample.rods if r.extra.get(label) is not None]
        if not values:
            continue
        agg = _describe(values)
        agg["unit"] = cf.get("unit") or ""
        out[label] = agg
    return out or None
