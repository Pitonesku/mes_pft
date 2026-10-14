"""Unit tests for the measurements.db backfill helpers (no DB needed).

Run from backend/:
    python -m unittest tests.test_etl_backfill -v
"""

import sqlite3
import unittest

from app.scripts import etl_backfill


class TimeWindowTests(unittest.TestCase):
    def test_unbounded(self):
        self.assertEqual(etl_backfill.time_window(), (None, None))

    def test_until_is_inclusive_of_whole_day(self):
        lower, upper = etl_backfill.time_window("2026-06-10", "2026-10-02")
        self.assertEqual(lower, "2026-06-10 00:00:00")
        self.assertEqual(upper, "2026-10-03 00:00:00")

    def test_month_rollover(self):
        self.assertEqual(etl_backfill.time_window(until="2026-09-30")[1], "2026-10-01 00:00:00")


class WindowedGroupsTests(unittest.TestCase):
    def _con(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE measurements (instrument_id, maker, batch_id, time, rod_no)")
        rows = [
            ("i", "1", "B1", "2026-06-09 23:59:59", 1),   # before since
            ("i", "1", "B1", "2026-06-10 00:00:00", 1),   # first included
            ("i", "1", "B2", "2026-10-02 22:50:48", 1),   # last day, included
            ("i", "1", "B3", "2026-10-03 00:00:00", 1),   # after until
        ]
        con.executemany("INSERT INTO measurements VALUES (?,?,?,?,?)", rows)
        return con

    def test_window_filters_groups(self):
        groups = etl_backfill.load_measurement_groups(self._con(), "2026-06-10", "2026-10-02")
        self.assertEqual(sorted(k[2] for k in groups),
                         ["2026-06-10 00:00:00", "2026-10-02 22:50:48"])

    def test_no_window_loads_everything(self):
        self.assertEqual(len(etl_backfill.load_measurement_groups(self._con())), 4)


if __name__ == "__main__":
    unittest.main()
