"""Fixed-window fallback linking: samples falling in the gap between shift
sessions (e.g. an auto-closed session and a late re-opened one) are linked to
the session of the fixed shift their timestamp belongs to."""

import unittest
from datetime import datetime, timezone

from app import models
from app.services import shift_resolver
from tests.db_support import DbTestCase


class FixedWindowLinkingTests(DbTestCase):
    def _session(self, name, started, ended, machine):
        s = models.ShiftSession(
            machine_id=machine.id, operator_id=self.user.id,
            shift_name=name, started_at=started, ended_at=ended,
            status="IN_PROGRESS")
        self.db.add(s)
        self.db.flush()
        return s

    def test_gap_timestamp_links_to_fixed_window_session(self):
        # Replicates production 2026-11-02 M2: Shift 1 closed at 13:00 UTC,
        # Shift 2 re-opened at 19:23 UTC - a rod at 17:25 UTC has no covering
        # session. It must link to the Shift 2 session of that day (the fixed
        # window 14:00-22:00), not stay NO_SHIFT forever.
        # 10:00 UTC = 11:00 local -> fixed window Shift 1 (06:00-14:00 local).
        ts = datetime(2020, 1, 1, 10, 0, tzinfo=timezone.utc)
        s = self._session(
            "Shift 1", datetime(2020, 1, 1, 12, 30, tzinfo=timezone.utc), None, self.m2)
        shift_id, status = shift_resolver.resolve_shift(self.db, self.m2.id, ts)
        self.assertEqual(shift_id, s.id)
        self.assertEqual(status, shift_resolver.LINK_FIXED_WINDOW)

    def test_no_matching_session_stays_no_shift(self):
        ts = datetime(2019, 5, 5, 10, 0, tzinfo=timezone.utc)
        shift_id, status = shift_resolver.resolve_shift(self.db, self.m2.id, ts)
        self.assertIsNone(shift_id)
        self.assertEqual(status, shift_resolver.LINK_NO_SHIFT)


if __name__ == "__main__":
    unittest.main()