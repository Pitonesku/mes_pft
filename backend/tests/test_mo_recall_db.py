"""Tests for the safe MO recall guardrails (services/odoo/recall.py)."""

import unittest
from datetime import datetime, timezone

from app import models
from app.services.odoo.recall import MoRecallError, recall_mo
from tests.db_support import DbTestCase

MO = "RECALL-TEST-MO"


def _now():
    return datetime.now(timezone.utc)


class MoRecallTests(DbTestCase):
    def _fresh_po(self):
        po = models.PurchaseOrder(
            po_number=f"PO-{MO}", odoo_mo_name=MO, odoo_mo_id=None,
            target_qty=1000, produced_qty=0, source="odoo", sync_mode="full",
            diameter=7.72, length=108, pd=325, cu=0, weight=66.0, box_type=4700,
            acetate_type="", paper_type="", pva_glue_type="", hm_glue_type="",
            triacetin_type="",
        )
        self.db.add(po)
        self.db.flush()
        return po

    def _run(self, po, *, ended=True, end_counter=None, machine=None):
        run = models.ProductionRun(
            shift_id=self.make_shift(machine).id, seq=1, po_id=po.id, mo_ref=MO,
            machine_id=(machine or self.m1).id, started_at=_now(),
            ended_at=_now() if ended else None,
            status="CLOSED" if ended else "OPEN",
            end_counter=end_counter,
        )
        self.db.add(run)
        self.db.flush()
        return run

    def test_missing_mo_ref_is_400(self):
        with self.assertRaises(MoRecallError) as cm:
            recall_mo(self.db, {})
        self.assertEqual(cm.exception.status_code, 400)

    def test_open_run_blocks_with_409(self):
        self._run(self._fresh_po(), ended=False)
        with self.assertRaises(MoRecallError) as cm:
            recall_mo(self.db, {"mo_ref": MO})
        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("open on machine", cm.exception.detail)

    def test_end_counter_blocks_with_409(self):
        self._run(self._fresh_po(), ended=True, end_counter=100)
        with self.assertRaises(MoRecallError) as cm:
            recall_mo(self.db, {"mo_ref": MO})
        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("Production data", cm.exception.detail)

    def test_manual_check_blocks_with_409(self):
        run = self._run(self._fresh_po(), ended=True)
        self.db.add(models.ManualQualityCheck(
            shift_id=run.shift_id, mo_id=run.id, machine_id=run.machine_id,
            po_id=run.po_id, mo_ref=MO, operator_id=self.user.id, sample_rods=10))
        self.db.flush()
        with self.assertRaises(MoRecallError) as cm:
            recall_mo(self.db, {"mo_ref": MO})
        self.assertEqual(cm.exception.status_code, 409)

    def test_measurement_blocks_with_409(self):
        run = self._run(self._fresh_po(), ended=True)
        sample = models.QualitySample(
            shift_id=run.shift_id, run_id=run.id, machine_id=run.machine_id,
            produced_at=_now(), link_status="NO_SHIFT", link_source="auto",
            kind="PRODUCTION", sample_id="test-sample")
        self.db.add(sample)
        self.db.flush()
        self.db.add(models.QualityMeasurement(
            sample_id=sample.id, shift_id=run.shift_id, run_id=run.id,
            machine_id=run.machine_id, measured_at=_now(), rod_no=1))
        self.db.flush()
        with self.assertRaises(MoRecallError) as cm:
            recall_mo(self.db, {"mo_ref": MO})
        self.assertEqual(cm.exception.status_code, 409)

    def test_unstarted_mo_archives(self):
        po = self._fresh_po()
        result = recall_mo(self.db, {"mo_ref": MO})
        self.assertTrue(result["recalled"])
        self.assertEqual(result["po_id"], po.id)
        self.db.refresh(po)
        self.assertTrue(po.is_archived)
        self.assertTrue(po.is_hidden)
        self.assertEqual(po.odoo_state, "recalled")
        self.assertEqual(po.sync_mode, "link_only")


if __name__ == "__main__":
    unittest.main()
