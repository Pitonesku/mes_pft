"""
Shift resolution: map an incoming station measurement to an active shift/run.

The algorithm, given ``(machine_id, timestamp)`` (and optionally an MO number):

1. Resolve the machine from a station identifier (e.g. Maker=1) via machine_aliases.
2. Classify non-production samples (calibration / maintenance) by configured rules.
3. Find the shift whose interval contains the timestamp (open shift = open interval).
   A ``grace`` window after ``ended_at`` catches QC samples pulled right after close.
4. Resolve the production run (MO) within that shift, preferring an explicit MO
   number, falling back to the run active at the timestamp.
5. If nothing matches, return shift_id=None so the sample is stored unlinked
   (eligible for a later relink sweep) rather than being dropped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)

LINK_LINKED = "LINKED"
LINK_LINKED_GRACE = "LINKED_GRACE"
LINK_NO_SHIFT = "NO_SHIFT"
LINK_UNRESOLVED_MACHINE = "UNRESOLVED_MACHINE"
LINK_NON_PRODUCTION = "NON_PRODUCTION"
LINK_CLOCK_SKEW = "CLOCK_SKEW"
LINK_MO_MISMATCH = "MO_MISMATCH"

DEFAULT_GRACE_MINUTES = 15
DEFAULT_CLOCK_SKEW_MINUTES = 10


def classify_sample(maker: str) -> Tuple[str, bool]:
    """Classify a station sample by its ``Maker`` field.

    Quantum Neo writes ``Maker = "Other"`` for calibration / maintenance runs.
    Returns ``(kind, is_non_production)``; non-production samples must not be
    linked to an open shift.
    """
    is_non_production = str(maker).strip() == "Other"
    kind = "CALIBRATION" if is_non_production else "PRODUCTION"
    return kind, is_non_production


def resolve_machine(session: Session, source: str, alias_field: str, alias_value: str) -> Optional[int]:
    """Return machines.id for a station identifier, or None."""
    alias = (
        session.query(models.MachineAlias)
        .filter(
            models.MachineAlias.source == source,
            models.MachineAlias.alias_field == alias_field,
            models.MachineAlias.alias_value == alias_value.strip(),
        )
        .first()
    )
    return alias.machine_id if alias else None


def resolve_shift(
    session: Session,
    machine_id: int,
    timestamp: datetime,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
) -> Tuple[Optional[int], str]:
    """Return (shift_id, link_status) for a measurement timestamp.

    Uses interval containment so historical replays and late-arriving files link
    identically to live ingestion. An open shift is an interval with NULL end.
    """
    if machine_id is None:
        return None, LINK_UNRESOLVED_MACHINE

    ts = _as_utc(timestamp)
    if ts is None:
        return None, LINK_NO_SHIFT

    # Clock skew: a timestamp noticeably in the future is suspect.
    if ts > datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_CLOCK_SKEW_MINUTES):
        return None, LINK_CLOCK_SKEW

    # Exact containment.
    shift = (
        session.query(models.ShiftSession)
        .filter(
            models.ShiftSession.machine_id == machine_id,
            models.ShiftSession.started_at <= ts,
        )
        .filter(
            (models.ShiftSession.ended_at.is_(None)) | (models.ShiftSession.ended_at > ts)
        )
        .order_by(models.ShiftSession.started_at.desc())
        .first()
    )
    if shift:
        return shift.id, LINK_LINKED

    # Grace window: latest closed shift whose end is within grace and not followed
    # by another shift starting before ts.
    grace_end = ts - timedelta(minutes=grace_minutes)
    shift = (
        session.query(models.ShiftSession)
        .filter(
            models.ShiftSession.machine_id == machine_id,
            models.ShiftSession.ended_at.isnot(None),
            models.ShiftSession.ended_at <= ts,
            models.ShiftSession.ended_at >= grace_end,
        )
        .order_by(models.ShiftSession.ended_at.desc())
        .first()
    )
    if shift:
        return shift.id, LINK_LINKED_GRACE

    return None, LINK_NO_SHIFT


def resolve_run(
    session: Session,
    shift_id: int,
    timestamp: datetime,
    mo_ref: Optional[str] = None,
) -> Tuple[Optional[int], str]:
    """Return (run_id, link_status) for a measurement within a shift."""
    ts = _as_utc(timestamp)

    if mo_ref:
        run = (
            session.query(models.ProductionRun)
            .filter(
                models.ProductionRun.shift_id == shift_id,
                models.ProductionRun.mo_ref == mo_ref.strip(),
            )
            .first()
        )
        if run:
            return run.id, LINK_LINKED
        return None, LINK_MO_MISMATCH

    run = (
        session.query(models.ProductionRun)
        .filter(
            models.ProductionRun.shift_id == shift_id,
            models.ProductionRun.started_at <= ts,
        )
        .filter(
            (models.ProductionRun.ended_at.is_(None)) | (models.ProductionRun.ended_at > ts)
        )
        .order_by(models.ProductionRun.seq.desc())
        .first()
    )
    return (run.id if run else None), LINK_LINKED


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
