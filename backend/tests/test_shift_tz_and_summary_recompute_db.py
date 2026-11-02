"""A7 + A9 regression tests (real DB, rolled back).

A9: naive timestamps from tablets are interpreted as PLANT-LOCAL, not UTC.
A7: the stale-summary recompute writes a new version and clears the flags.
"""

import unittest
from datetime import datetime, timezone

from app import models, v2_routes as v2
from app.services import aggregation
from tests.db_support import DbTestCase


class ShiftTimezoneTests(DbTestCase):
    def _open(self, started_at, plant_tz="Europe/Budapest"):
        return v2.open_shift(
            v2.ShiftOpen(machine_id=self.m1.id, po_id=self.po_a.id,
                         shift_name="A9-TEST", started_at=started_at, plant_tz=plant_tz),
            db=self.db, current_user=self.user,
        )

    def test_naive_started_at_is_plant_local(self):
        # 13 Oct 2026 is CEST (UTC+2): 18:00 local -> 16:00 UTC.
        opened = self._open(datetime(2026, 10, 13, 18, 0, 0))
        shift = self.db.query(models.ShiftSession).get(opened["id"])
        self.assertEqual(shift.started_at, datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc))

    def test_aware_started_at_passes_through(self):
        aware = datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc)
        opened = self._open(aware)
        shift = self.db.query(models.ShiftSession).get(opened["id"])
        self.assertEqual(shift.started_at, aware)

    def test_naive_ended_at_is_plant_local(self):
        aware_start = datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc)
        opened = self._open(aware_start)
        # naive CEST 18:00 = 16:00 UTC
        v2.close_shift(opened["id"], v2.ShiftClose(ended_at=datetime(2026, 10, 13, 18, 0)),
                       db=self.db, current_user=self.user, idempotency_key=None)
        shift = self.db.query(models.ShiftSession).get(opened["id"])
        self.assertEqual(shift.ended_at, datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc))


class SummaryRecomputeTests(DbTestCase):
    def _open_and_close(self):
        opened = v2.open_shift(
            v2.ShiftOpen(machine_id=self.m1.id, po_id=self.po_a.id,
                         shift_name="A7-TEST",
                         started_at=datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc)),
            db=self.db, current_user=self.user,
        )
        v2.close_shift(opened["id"], v2.ShiftClose(), db=self.db,
                       current_user=self.user, idempotency_key=None)
        return opened["id"]

    def test_recompute_stale_summary_bumps_version_and_clears_flags(self):
        shift_id = self._open_and_close()
        rows = (self.db.query(models.ShiftSummary)
                .filter_by(shift_id=shift_id).order_by(models.ShiftSummary.version).all())
        self.assertEqual(len(rows), 1)
        rows[0].is_stale = True
        self.db.commit()

        done = aggregation.recompute_stale_summaries(self.db)
        self.db.commit()

        self.assertEqual([d["shift_id"] for d in done], [shift_id])
        self.assertEqual(done[0]["version"], 2)
        rows = (self.db.query(models.ShiftSummary)
                .filter_by(shift_id=shift_id).order_by(models.ShiftSummary.version).all())
        self.assertEqual([r.version for r in rows], [1, 2])
        self.assertTrue(all(not r.is_stale for r in rows))
        self.assertEqual(rows[1].payload["idempotency_key"], f"mes:shift:{shift_id}:v2")

    def test_recompute_is_idempotent_when_nothing_stale(self):
        shift_id = self._open_and_close()
        self.assertEqual(aggregation.recompute_stale_summaries(self.db), [])
        rows = (self.db.query(models.ShiftSummary).filter_by(shift_id=shift_id).all())
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
