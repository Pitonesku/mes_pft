"""Regression: the order consolidated quality is a grand mean, not an average of averages."""

import unittest

from app import models
from app.services import aggregation, shift_lifecycle as lc
from tests.db_support import DbTestCase


class OrderSummaryGrandMeanTests(DbTestCase):
    def _run(self, shift, po, machine):
        run = models.ProductionRun(
            shift_id=shift.id, seq=1, po_id=po.id, mo_ref=po.po_number,
            machine_id=machine.id, started_at=lc.utcnow(), ended_at=lc.utcnow(),
            status="CLOSED",
        )
        self.db.add(run)
        self.db.flush()
        return run

    def test_manual_hardness_is_grand_mean_across_runs(self):
        po = self.po_a
        self.db.add(models.QualitySpec(
            scope="po", po_id=po.id, parameter="hardness",
            nominal=82, lower_limit=None, upper_limit=None, report_unit="%", decimals=1))
        self.db.flush()

        s1 = self.make_shift(self.m1)
        r1 = self._run(s1, po, self.m1)
        s2 = self.make_shift(self.m2)
        r2 = self._run(s2, po, self.m2)

        # Run 1: three checks (50, 60, 70). Run 2: one check (100).
        for h in (50.0, 60.0, 70.0):
            self.db.add(models.ManualQualityCheck(
                shift_id=s1.id, mo_id=r1.id, machine_id=r1.machine_id,
                po_id=po.id, mo_ref=po.po_number, operator_id=self.user.id,
                sample_rods=10, hardness=h))
        self.db.add(models.ManualQualityCheck(
            shift_id=s2.id, mo_id=r2.id, machine_id=r2.machine_id,
            po_id=po.id, mo_ref=po.po_number, operator_id=self.user.id,
            sample_rods=10, hardness=100.0))
        self.db.flush()

        summary = aggregation.compute_order_summary(self.db, po.id)
        by_param = {r["parameter"]: r for r in summary["certificate"]}
        hardness = by_param.get("hardness")
        self.assertIsNotNone(hardness)
        # Grand mean (sum/count) = 70, NOT the average of per-run means (60, 100 -> 80).
        self.assertAlmostEqual(hardness["mean"], 70.0, places=6)
        self.assertEqual(hardness["n"], 4)


if __name__ == "__main__":
    unittest.main()
