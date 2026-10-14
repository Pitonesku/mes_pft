"""Unit tests for the report-time-window rule that assigns rods to an MO."""

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services import run_assignment as ra

TZ = ZoneInfo("Europe/Budapest")


def dt(h, m=0, day=4):
    return datetime(2026, 8, day, h, m, tzinfo=TZ)


MORNING = (dt(6), dt(14))


class ParseTests(unittest.TestCase):
    def test_parse_loose_formats(self):
        self.assertEqual(ra.parse_time_range("06:00 - 11:45"), ((6, 0), (11, 45)))
        self.assertEqual(ra.parse_time_range("6 - 14"), ((6, 0), (14, 0)))
        self.assertEqual(ra.parse_time_range("8:00 - 14:00"), ((8, 0), (14, 0)))
        self.assertEqual(ra.parse_time_range(" - 20:00"), (None, (20, 0)))
        self.assertEqual(ra.parse_time_range("garbage"), (None, None))
        self.assertEqual(ra.parse_time_range(None), (None, None))

    def test_window_missing_side_falls_back_to_shift_bound(self):
        t0, t1 = ra.report_window(" - 11:45", *MORNING)
        self.assertEqual((t0, t1), (dt(6), dt(11, 45)))

    def test_window_unusable_returns_none(self):
        self.assertIsNone(ra.report_window("n/a", *MORNING))

    def test_overnight_window_rolls_over_midnight(self):
        s0, s1 = dt(22), dt(6, day=5)
        t0, t1 = ra.report_window("22:00 - 06:00", s0, s1)
        self.assertEqual(t0, dt(22))
        self.assertEqual(t1, dt(6, day=5))
        t0, t1 = ra.report_window("01:00 - 05:00", s0, s1)
        self.assertEqual((t0, t1), (dt(1, day=5), dt(5, day=5)))


class ResolveTests(unittest.TestCase):
    def setUp(self):
        # 04 Aug M2: G080 06:00-11:45 then H081 12:10-14:00
        self.m2 = [("G080", dt(6), dt(11, 45)), ("H081", dt(12, 10), dt(14))]
        # 04 Aug M1: both reports say 06:00-14:00
        self.m1 = [("G080", dt(6), dt(14)), ("H081", dt(6), dt(14))]

    def test_non_overlapping_windows_pick_by_time(self):
        self.assertEqual(ra.resolve_po(dt(9), "H081", self.m2), ("G080", ra.REASON_WINDOW))
        self.assertEqual(ra.resolve_po(dt(13), "G080", self.m2), ("H081", ra.REASON_WINDOW))

    def test_window_beats_station_label(self):
        po, reason = ra.resolve_po(dt(13), "G080", self.m2)
        self.assertEqual(po, "H081")

    def test_grace_after_end(self):
        self.assertEqual(ra.resolve_po(dt(11, 55), "", self.m2)[0], "G080")
        self.assertIsNone(ra.resolve_po(dt(12, 1), "", self.m2)[0])

    def test_overlap_uses_label_tiebreak(self):
        self.assertEqual(ra.resolve_po(dt(8), "G080", self.m1), ("G080", ra.REASON_LABEL))
        self.assertEqual(ra.resolve_po(dt(11), "H081", self.m1), ("H081", ra.REASON_LABEL))

    def test_overlap_with_unknown_label_stays_unassigned(self):
        self.assertEqual(ra.resolve_po(dt(8), "G081", self.m1), (None, ra.REASON_AMBIGUOUS))
        self.assertEqual(ra.resolve_po(dt(8), None, self.m1), (None, ra.REASON_AMBIGUOUS))

    def test_outside_every_window(self):
        self.assertEqual(ra.resolve_po(dt(20), "G080", self.m2), (None, ra.REASON_NONE))

    def test_same_po_twice_is_not_ambiguous(self):
        wins = [("H081", dt(6), dt(14)), ("H081", dt(6), dt(14))]
        self.assertEqual(ra.resolve_po(dt(9), "", wins), ("H081", ra.REASON_WINDOW))

    def test_summarize(self):
        res = [("G080", ra.REASON_WINDOW), (None, ra.REASON_NONE), ("H081", ra.REASON_LABEL)]
        self.assertEqual(
            ra.summarize(res),
            {"assigned_window": 1, "outside_all_windows": 1, "assigned_label_tiebreak": 1},
        )


if __name__ == "__main__":
    unittest.main()
