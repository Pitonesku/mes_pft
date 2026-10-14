"""Pure rules for assigning quality rods/samples to a production run (MO).

No DB or framework imports, so it is unit-testable. A shift can hold several legacy
production reports (one per MO), each with its own start/stop time. A measurement
belongs to the MO whose report time window contains the measurement time.

Tie-break: when the windows of two or more different MOs contain the measurement
(identical or overlapping time entries), the station label (the PO number typed in
the quality station) decides, but only if it equals exactly one of the candidate MOs.
Otherwise the measurement is left unassigned for manual review.
"""

import re
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

GRACE = timedelta(minutes=15)

REASON_WINDOW = "window"
REASON_LABEL = "label_tiebreak"
REASON_NONE = "outside_all_windows"
REASON_AMBIGUOUS = "ambiguous_overlap"

_TIME_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*$")


def _parse_hm(text: str) -> Optional[Tuple[int, int]]:
    m = _TIME_RE.match(text or "")
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if hour > 24 or minute > 59:
        return None
    return hour, minute


def parse_time_range(text: Optional[str]) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """Parse '06:00 - 11:45', '6 - 14', '8:00 - 14:00', ' - 20:00'.

    Returns ``(start_hm, end_hm)``; a missing side is ``None`` (the caller falls back
    to the shift bound). Returns ``(None, None)`` when nothing usable is found.
    """
    if not text or "-" not in text:
        return None, None
    left, _, right = text.partition("-")
    return _parse_hm(left), _parse_hm(right)


def report_window(
    time_range: Optional[str],
    shift_start: datetime,
    shift_end: datetime,
) -> Optional[Tuple[datetime, datetime]]:
    """Absolute ``(start, end)`` of a report inside its shift.

    ``shift_start`` / ``shift_end`` must be aware datetimes in the plant timezone.
    A missing start/end falls back to the shift bound. Returns ``None`` when the
    range is unusable (both sides missing).
    """
    start_hm, end_hm = parse_time_range(time_range)
    if start_hm is None and end_hm is None:
        return None

    def at(base: datetime, hm: Tuple[int, int]) -> datetime:
        hour, minute = hm
        day = base.replace(hour=0, minute=0, second=0, microsecond=0)
        return day + timedelta(hours=hour, minutes=minute)

    t0 = at(shift_start, start_hm) if start_hm else shift_start
    # Overnight shift: a start time earlier than the shift start is after midnight.
    if start_hm and t0 < shift_start - timedelta(hours=3):
        t0 += timedelta(days=1)
    t1 = at(shift_start, end_hm) if end_hm else shift_end
    while t1 <= t0:
        t1 += timedelta(days=1)
    return t0, t1


def resolve_po(
    measured_at: datetime,
    label: Optional[str],
    windows: Iterable[Tuple[str, datetime, datetime]],
    grace: timedelta = GRACE,
) -> Tuple[Optional[str], str]:
    """Pick the PO number for one measurement. Returns ``(po_number, reason)``."""
    hits: List[str] = []
    for po, t0, t1 in windows:
        if t0 <= measured_at <= t1 + grace and po not in hits:
            hits.append(po)
    if len(hits) == 1:
        return hits[0], REASON_WINDOW
    if not hits:
        return None, REASON_NONE
    clean = (label or "").strip()
    if clean in hits:
        return clean, REASON_LABEL
    return None, REASON_AMBIGUOUS


def summarize(results: Iterable[Tuple[Optional[str], str]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for po, reason in results:
        key = reason if po is None else "assigned_" + reason
        out[key] = out.get(key, 0) + 1
    return out
