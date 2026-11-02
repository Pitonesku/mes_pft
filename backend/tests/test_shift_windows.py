"""Fixed shift windows: 06-14 / 14-22 / 22-06 mapping (pure, no DB)."""

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services import shift_windows

TZ = ZoneInfo("Europe/Budapest")
TEMPLATES = [("Shift 1", "06:00", "14:00"), ("Shift 2", "14:00", "22:00"), ("Shift 3", "22:00", "06:00")]


def at(h: int, m: int, day: int = 10, month: int = 11, year: int = 2026):
    return datetime(year, month, day, h, m, tzinfo=TZ)


class FixedWindowTests(unittest.TestCase):
    def test_day_windows(self):
        self.assertEqual(shift_windows.window_for(TEMPLATES, at(7, 0)).name, "Shift 1")
        self.assertEqual(shift_windows.window_for(TEMPLATES, at(13, 59)).name, "Shift 1")
        self.assertEqual(shift_windows.window_for(TEMPLATES, at(14, 0)).name, "Shift 2")
        self.assertEqual(shift_windows.window_for(TEMPLATES, at(21, 59)).name, "Shift 2")

    def test_overnight_window(self):
        w = shift_windows.window_for(TEMPLATES, at(22, 0))
        self.assertEqual(w.name, "Shift 3")
        self.assertEqual(w.start, at(22, 0))
        self.assertEqual(w.end, at(6, 0, day=11))
        # 05:30 belongs to the window that started yesterday 22:00.
        w2 = shift_windows.window_for(TEMPLATES, at(5, 30, day=11))
        self.assertEqual(w2.name, "Shift 3")
        self.assertEqual(w2.start, at(22, 0, day=10))
        self.assertEqual(w2.end, at(6, 0, day=11))

    def test_window_bounds_inclusive_start_exclusive_end(self):
        w = shift_windows.window_for(TEMPLATES, at(14, 0))
        self.assertIsNotNone(w)
        self.assertEqual(shift_windows.window_for(TEMPLATES, at(22, 0)).name, "Shift 3")

    def test_measurement_visibility_ignores_session(self):
        # A rod measured at 20:23 falls in Shift 2's fixed window regardless of
        # when any tablet session was opened.
        w = shift_windows.window_for(TEMPLATES, at(20, 23))
        self.assertEqual(w.name, "Shift 2")
        self.assertEqual(w.start, at(14, 0))
        self.assertEqual(w.end, at(22, 0))

    def test_window_for_label(self):
        w = shift_windows.window_for_label(TEMPLATES, "Shift 2", at(10, 0))
        self.assertEqual(w.start, at(14, 0))
        self.assertEqual(w.end, at(22, 0))
        w2 = shift_windows.window_for_label(TEMPLATES, "Shift 3", at(5, 0, day=11))
        self.assertEqual(w2.start, at(22, 0, day=10))
        self.assertEqual(w2.end, at(6, 0, day=11))

    def test_windows_for_day(self):
        ws = shift_windows.windows_for_day(TEMPLATES, at(12, 0, day=11))
        self.assertEqual([w.name for w in ws], ["Shift 3", "Shift 1", "Shift 2"])
        self.assertEqual(ws[0].start, at(22, 0, day=10))
        self.assertEqual(ws[-1].end, at(22, 0, day=11))


if __name__ == "__main__":
    unittest.main()
