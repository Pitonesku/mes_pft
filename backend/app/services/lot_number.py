"""Factory lot-number convention: ``DDMMYYM#`` (pure, no DB/framework imports).

Example: a shift that started on 31 July 2026 on machine M1 -> ``310726M1``.
The date is the local plant date of the shift START (so a night shift that runs past
midnight keeps the date it started on).
"""

import re
from datetime import datetime
from typing import Optional
from app.config import get_plant_timezone

PLANT_TZ = get_plant_timezone()

_MACHINE_RE = re.compile(r"(\d+)")


def lot_number(shift_start: Optional[datetime], machine_name: Optional[str]) -> Optional[str]:
    """Return ``DDMMYYM#`` or ``None`` when the start time / machine number is unknown."""
    if shift_start is None:
        return None
    m = _MACHINE_RE.search(machine_name or "")
    if not m:
        return None
    start = shift_start
    if start.tzinfo is not None:
        start = start.astimezone(PLANT_TZ)
    return f"{start:%d%m%y}M{int(m.group(1))}"
