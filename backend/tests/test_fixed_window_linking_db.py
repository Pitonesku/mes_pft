"""Fixed-window linking: a measurement links to its fixed plant shift by clock
time, even when nobody opened a shift session for that window.

* the fixed window wins over the post-close grace window;
* a missing window session is synthesized (source='fixed-window', closed, no
  operator) and reused afterwards - never duplicated;
* the order of a sample is mo_ref OR a Sample ID equal to an existing order.
"""

import unittest
from datetime import datetime, timezone

from app import models
from app.services import shift_resolver
from tests.db_support import DbTestCase


class FixedWindowLinkingTests(DbTestCase):
    def _session(self, name, started, ended, machine, source="tablet"):
        s = models.ShiftSession(
            machine_id=machine.id, operator_id=self.user.id,
            shift_name=name, started_at=started, ended_at=ended,
            status="IN_PROGRESS", source=source)
        self.db.add(s)
        self.db.flush()
        return s

    def test_existing_session_of_the_fixed_window_is_reused(self):
        # 2020-01-01 10:00 UTC = 11:00 Budapest -> Shift 1 (06:00-14:00).
        ts = datetime(2020, 1, 1, 10, 0, tzinfo=timezone.utc)
        s = self._session(
            "Shift 1", datetime(2020, 1, 1, 12, 30, tzinfo=timezone.utc), None, self.m2)
        shift_id, status = shift_resolver.resolve_shift(self.db, self.m2.id, ts)
        self.assertEqual(shift_id, s.id)
        self.assertEqual(status, shift_resolver.LINK_FIXED_WINDOW)

    def test_missing_window_session_is_synthesized_and_reused(self):
        # 2019-05-05 21:49 UTC = 23:49 Budapest (CEST) -> Shift 3 (22:00-06:00),
        # and no Shift 3 session exists at all.
        ts = datetime(2019, 5, 5, 21, 49, tzinfo=timezone.utc)
        shift_id, status = shift_resolver.resolve_shift(self.db, self.m2.id, ts)
        self.assertIsNotNone(shift_id)
        self.assertEqual(status, shift_resolver.LINK_FIXED_WINDOW)
        s = self.db.get(models.ShiftSession, shift_id)
        self.assertEqual(s.shift_name, "Shift 3")
        self.assertEqual(s.source, shift_resolver.FIXED_WINDOW_SOURCE)
        self.assertEqual(s.status, "CLOSED")
        self.assertIsNone(s.operator_id)
        self.assertEqual(s.machine_id, self.m2.id)
        # window: 22:00 local (20:00 UTC) -> 06:00 local next day (04:00 UTC)
        self.assertEqual(s.started_at, datetime(2019, 5, 5, 20, 0, tzinfo=timezone.utc))
        self.assertEqual(s.ended_at, datetime(2019, 5, 6, 4, 0, tzinfo=timezone.utc))
        # a second sample in the same window reuses the same session
        ts2 = datetime(2019, 5, 6, 1, 0, tzinfo=timezone.utc)
        shift_id2, _ = shift_resolver.resolve_shift(self.db, self.m2.id, ts2)
        self.assertEqual(shift_id2, shift_id)

    def test_fixed_window_beats_grace_window(self):
        # A Shift 1 session closed at 14:00 local; a rod at 14:10 local belongs to
        # Shift 2 by the clock (not to Shift 1 via the 15-minute grace window).
        end = datetime(2018, 2, 2, 13, 0, tzinfo=timezone.utc)  # 14:00 Budapest (CET)
        s1 = self._session("Shift 1", datetime(2018, 2, 2, 5, 0, tzinfo=timezone.utc), end, self.m1)
        ts = datetime(2018, 2, 2, 13, 10, tzinfo=timezone.utc)  # 14:10 local
        shift_id, status = shift_resolver.resolve_shift(self.db, self.m1.id, ts)
        self.assertNotEqual(shift_id, s1.id)
        self.assertEqual(status, shift_resolver.LINK_FIXED_WINDOW)
        self.assertEqual(self.db.get(models.ShiftSession, shift_id).shift_name, "Shift 2")


class SyntheticSessionMismatchTests(DbTestCase):
    def test_second_sample_in_synthesized_window_is_not_a_mismatch(self):
        from app import v2_routes

        ts1 = datetime(2017, 4, 4, 21, 0, tzinfo=timezone.utc)  # Shift 3 window
        ts2 = datetime(2017, 4, 4, 22, 0, tzinfo=timezone.utc)
        sid1, _ = shift_resolver.resolve_shift(self.db, self.m1.id, ts1)
        sid2, status2 = shift_resolver.resolve_shift(self.db, self.m1.id, ts2)
        self.assertEqual(sid1, sid2)
        # status may be LINKED (run-less containment branch); the shift has no
        # runs, so an order with no matching run must not be flagged MO_MISMATCH.
        self.assertFalse(v2_routes._shift_has_runs(self.db, sid2))


class SampleOrderRefTests(DbTestCase):
    def test_mo_ref_wins(self):
        self.assertEqual(shift_resolver.sample_order_ref(self.db, " X1 ", "whatever"), "X1")

    def test_sample_id_that_is_an_order_counts(self):
        mo = self.po_a.mo_number
        self.assertEqual(shift_resolver.sample_order_ref(self.db, "", mo), mo)
        self.assertEqual(shift_resolver.sample_order_ref(self.db, None, " " + mo + " "), mo)

    def test_free_label_is_not_an_order(self):
        self.assertEqual(shift_resolver.sample_order_ref(self.db, "", "B027-not-an-order"), "")
        self.assertEqual(shift_resolver.sample_order_ref(self.db, "", ""), "")


if __name__ == "__main__":
    unittest.main()
