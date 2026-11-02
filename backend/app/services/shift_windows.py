"""Fixed shift windows for quality-control viewing.

Measurement visibility must not depend on fragile tablet shift sessions: every
timestamp maps deterministically onto one of the configured fixed windows
(by default 06:00-14:00 / 14:00-22:00 / 22:00-06:00), so rods recorded while a
session was re-opened late - or under a different session - still appear under
the correct shift. Pure module (no DB/env imports) for unit-testability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import List, Optional, Sequence, Tuple, Union

from zoneinfo import ZoneInfo

# (name, start "HH:MM", end "HH:MM") - supplied by the caller from the shifts table.
Template = Tuple[str, str, str]


@dataclass
class FixedWindow:
    name: str
    start: datetime   # inclusive, tz-aware
    end: datetime     # exclusive, tz-aware


def _to_min(hhmm: str) -> int:
    parts = hhmm.strip().split(":")
    h = int(parts[0]) if parts else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    return h * 60 + m


def _combine(day, minutes: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(minutes // 60, minutes % 60), tzinfo=tz)


def _tzinfo(tz, when):
    if tz is None:
        if when.tzinfo is None:
            raise ValueError("tz required when 'when' is naive")
        return when.tzinfo
    return tz if isinstance(tz, ZoneInfo) else ZoneInfo(tz)


def window_for(
    templates: Sequence[Template],
    when: datetime,
    tz: Optional[Union[ZoneInfo, str]] = None,
) -> Optional[FixedWindow]:
    """The fixed window containing ``when``, or None (no template matches)."""
    tzinfo = _tzinfo(tz, when)
    local = when.astimezone(tzinfo) if when.tzinfo else when.replace(tzinfo=tzinfo)
    for name, s_hhmm, e_hhmm in templates:
        s_min, e_min = _to_min(s_hhmm), _to_min(e_hhmm)
        day = local.date()
        if s_min < e_min:
            start = _combine(day, s_min, tzinfo)
            end = _combine(day, e_min, tzinfo)
        else:
            # Overnight window (e.g. 22:00 -> 06:00): times before the end time
            # belong to the window that started the previous day.
            end_today = _combine(day, e_min, tzinfo)
            if local < end_today:
                day -= timedelta(days=1)
            start = _combine(day, s_min, tzinfo)
            end = _combine(day + timedelta(days=1), e_min, tzinfo)
        if start <= local < end:
            return FixedWindow(name, start, end)
    return None


def window_for_label(
    templates: Sequence[Template],
    label: str,
    on: datetime,
    tz: Optional[Union[ZoneInfo, str]] = None,
) -> Optional[FixedWindow]:
    """The window of the named fixed shift relative to ``on``.

    If ``on`` falls inside that shift's window, the containing window is
    returned; otherwise the one starting on ``on``'s date (day shifts) or the
    one ending on ``on``'s date (overnight shifts).
    """
    tzinfo = _tzinfo(tz, on)
    current = window_for(templates, on, tzinfo)
    if current is not None and current.name == label:
        return current
    local = on.astimezone(tzinfo) if on.tzinfo else on.replace(tzinfo=tzinfo)
    for name, s_hhmm, e_hhmm in templates:
        if name != label:
            continue
        s_min, e_min = _to_min(s_hhmm), _to_min(e_hhmm)
        day = local.date()
        if s_min < e_min:
            return FixedWindow(name, _combine(day, s_min, tzinfo), _combine(day, e_min, tzinfo))
        # Overnight: prefer the window that started yesterday when we are
        # already past its end (i.e. before 06:00 today).
        end_today = _combine(day, e_min, tzinfo)
        if local < end_today:
            day -= timedelta(days=1)
        return FixedWindow(name, _combine(day, s_min, tzinfo), _combine(day + timedelta(days=1), e_min, tzinfo))
    return None


def windows_for_day(
    templates: Sequence[Template],
    on: datetime,
    tz: Optional[Union[ZoneInfo, str]] = None,
) -> List[FixedWindow]:
    """All fixed windows for ``on``'s plant-local day (chronological order)."""
    tzinfo = _tzinfo(tz, on)
    local = on.astimezone(tzinfo) if on.tzinfo else on.replace(tzinfo=tzinfo)
    out: List[FixedWindow] = []
    for name, s_hhmm, e_hhmm in templates:
        s_min, e_min = _to_min(s_hhmm), _to_min(e_hhmm)
        day = local.date()
        if s_min >= e_min:
            # Overnight shift: started on the previous date.
            day -= timedelta(days=1)
        start = _combine(day, s_min, tzinfo)
        end = _combine(day + timedelta(days=1) if s_min >= e_min else day, e_min, tzinfo)
        out.append(FixedWindow(name, start, end))
    out.sort(key=lambda w: w.start)
    return out
