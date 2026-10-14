"""Pure run-selection rule used by live ingestion, relink and the resolver."""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import shift_resolver as sr

T0 = datetime(2026, 10, 10, 6, 0, tzinfo=timezone.utc)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def run(rid, seq, mo, start, end=None):
    return SimpleNamespace(
        id=rid, seq=seq, mo_ref=mo,
        started_at=at(start), ended_at=None if end is None else at(end),
    )


class NoLabelTests(unittest.TestCase):
    def setUp(self):
        self.runs = [run(1, 1, "A", 0, 120), run(2, 2, "B", 120)]

    def test_picks_run_active_at_timestamp(self):
        self.assertEqual(sr.pick_run(self.runs, at(30))[0].id, 1)
        self.assertEqual(sr.pick_run(self.runs, at(200))[0].id, 2)

    def test_boundary_belongs_to_the_new_run(self):
        self.assertEqual(sr.pick_run(self.runs, at(120))[0].id, 2)

    def test_grace_after_close_uses_last_run(self):
        closed = [run(1, 1, "A", 0, 120)]
        self.assertEqual(sr.pick_run(closed, at(130))[0].id, 1)

    def test_before_any_run_is_unassigned(self):
        self.assertIsNone(sr.pick_run(self.runs, at(-5))[0])


class LabelTests(unittest.TestCase):
    def test_label_selects_that_mo(self):
        runs = [run(1, 1, "A", 0, 120), run(2, 2, "B", 120)]
        run_, status = sr.pick_run(runs, at(130), "A")
        self.assertEqual((run_.id, status), (1, sr.LINK_LINKED))

    def test_unknown_label_is_mismatch_not_silently_dropped(self):
        runs = [run(1, 1, "A", 0)]
        run_, status = sr.pick_run(runs, at(10), "TYPO")
        self.assertIsNone(run_)
        self.assertEqual(status, sr.LINK_MO_MISMATCH)

    def test_same_mo_twice_prefers_the_active_one(self):
        runs = [run(1, 1, "A", 0, 60), run(2, 2, "B", 60, 120), run(3, 3, "A", 120)]
        self.assertEqual(sr.pick_run(runs, at(150), "A")[0].id, 3)
        self.assertEqual(sr.pick_run(runs, at(30), "A")[0].id, 1)

    def test_same_mo_twice_falls_back_to_nearest(self):
        runs = [run(1, 1, "A", 0, 60), run(2, 2, "B", 60, 120), run(3, 3, "A", 120, 180)]
        # timestamp inside B, label A: closest A run in time wins (run 1 ends at 60, run 3 starts at 120)
        self.assertEqual(sr.pick_run(runs, at(70), "A")[0].id, 1)
        self.assertEqual(sr.pick_run(runs, at(115), "A")[0].id, 3)

    def test_label_whitespace_is_ignored(self):
        runs = [run(1, 1, "A", 0)]
        self.assertEqual(sr.pick_run(runs, at(5), "  A ")[0].id, 1)


if __name__ == "__main__":
    unittest.main()
