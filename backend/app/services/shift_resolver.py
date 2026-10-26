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
from typing import Optional, Sequence, Tuple

from sqlalchemy import exists
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

    # A shift may move between machines, so a rod belongs to the shift whose RUN was
    # active on this machine at ``ts`` (production_runs.machine_id), not to
    # ``shift.machine_id`` (which only names the machine the shift is on *now*).
    run = (
        session.query(models.ProductionRun)
        .filter(
            models.ProductionRun.machine_id == machine_id,
            models.ProductionRun.started_at <= ts,
        )
        .filter(
            (models.ProductionRun.ended_at.is_(None)) | (models.ProductionRun.ended_at > ts)
        )
        .order_by(models.ProductionRun.started_at.desc())
        .first()
    )
    if run:
        return run.shift_id, LINK_LINKED

    # Legacy shifts that have no machine-bearing run: exact containment on the shift.
    shift = (
        session.query(models.ShiftSession)
        .filter(
            models.ShiftSession.machine_id == machine_id,
            models.ShiftSession.started_at <= ts,
            ~_has_machine_run(),
        )
        .filter(
            (models.ShiftSession.ended_at.is_(None)) | (models.ShiftSession.ended_at > ts)
        )
        .order_by(models.ShiftSession.started_at.desc())
        .first()
    )
    if shift:
        return shift.id, LINK_LINKED

    # Grace window: the latest run on this machine that ended within ``grace`` of ts
    # (QC samples pulled right after a close / machine change).
    grace_end = ts - timedelta(minutes=grace_minutes)
    run = (
        session.query(models.ProductionRun)
        .filter(
            models.ProductionRun.machine_id == machine_id,
            models.ProductionRun.ended_at.isnot(None),
            models.ProductionRun.ended_at <= ts,
            models.ProductionRun.ended_at >= grace_end,
        )
        .order_by(models.ProductionRun.ended_at.desc())
        .first()
    )
    if run:
        return run.shift_id, LINK_LINKED_GRACE

    shift = (
        session.query(models.ShiftSession)
        .filter(
            models.ShiftSession.machine_id == machine_id,
            models.ShiftSession.ended_at.isnot(None),
            models.ShiftSession.ended_at <= ts,
            models.ShiftSession.ended_at >= grace_end,
            ~_has_machine_run(),
        )
        .order_by(models.ShiftSession.ended_at.desc())
        .first()
    )
    if shift:
        return shift.id, LINK_LINKED_GRACE

    return None, LINK_NO_SHIFT


def _has_machine_run():
    """Correlated EXISTS: the shift owns at least one run that records a machine."""
    return exists().where(
        models.ProductionRun.shift_id == models.ShiftSession.id,
        models.ProductionRun.machine_id.isnot(None),
    )


def pick_run(runs: Sequence, ts: datetime, mo_ref: Optional[str] = None, sample_id: Optional[str] = None) -> Tuple[Optional[object], str]:
    """Pure run-selection rule over a shift's runs (objects with ``id``, ``seq``,
    ``mo_ref``, ``started_at``, ``ended_at``). Returns ``(run, link_status)``.

    * no station label -> the run active at ``ts`` (or, in the post-close grace
      window, the last run);
    * a label -> the run with that MO; when the shift has several runs of the same
      MO (A -> B -> A) the one active at ``ts``, else the nearest in time;
    * a label no run of the shift carries -> ``(None, MO_MISMATCH)`` so the rod
      stays visible for review instead of polluting another MO's statistics.
    """
    ordered = sorted(runs, key=lambda r: r.seq)

    def active_at() -> Optional[object]:
        hit = None
        for r in ordered:
            if r.started_at is not None and _as_utc(r.started_at) > ts:
                continue
            if r.ended_at is not None and _as_utc(r.ended_at) <= ts:
                continue
            hit = r
        if hit is None and ordered:
            last = ordered[-1]
            if last.ended_at is not None and _as_utc(last.ended_at) <= ts:
                hit = last  # grace window after close
        return hit

    label = (mo_ref or "").strip()
    if not label and sample_id:
        # Guarded fallback: the station "Sample ID" doubles as the MO number only
        # when it actually names one of the runs in this shift. Free-form labels
        # (e.g. "I099" while producing J099) keep the time-based fallback instead
        # of surfacing a spurious MO_MISMATCH.
        sid = (sample_id or "").strip()
        if any((r.mo_ref or "").strip() == sid for r in ordered):
            label = sid
    if not label:
        run = active_at()
        return run, LINK_LINKED

    candidates = [r for r in ordered if (r.mo_ref or "").strip() == label]
    if not candidates:
        return None, LINK_MO_MISMATCH
    if len(candidates) == 1:
        return candidates[0], LINK_LINKED
    current = active_at()
    if current is not None and current in candidates:
        return current, LINK_LINKED

    def distance(r) -> float:
        start = _as_utc(r.started_at) if r.started_at else ts
        end = _as_utc(r.ended_at) if r.ended_at else ts
        if ts < start:
            return (start - ts).total_seconds()
        if ts > end:
            return (ts - end).total_seconds()
        return 0.0

    return min(candidates, key=distance), LINK_LINKED


def resolve_run(
    session: Session,
    shift_id: int,
    timestamp: datetime,
    mo_ref: Optional[str] = None,
    machine_id: Optional[int] = None,
    sample_id: Optional[str] = None,
) -> Tuple[Optional[int], str]:
    """Return (run_id, link_status) for a measurement within a shift.

    ``machine_id`` restricts the choice to runs recorded on that machine, which
    matters once a shift has moved between machines. ``sample_id`` is a guarded
    fallback MO label used only when ``mo_ref`` is empty (see ``pick_run``)."""
    ts = _as_utc(timestamp)
    query = session.query(models.ProductionRun).filter(models.ProductionRun.shift_id == shift_id)
    if machine_id is not None:
        query = query.filter(
            (models.ProductionRun.machine_id == machine_id) | (models.ProductionRun.machine_id.is_(None))
        )
    run, status = pick_run(query.all(), ts, mo_ref, sample_id=sample_id)
    return (run.id if run is not None else None), status


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
