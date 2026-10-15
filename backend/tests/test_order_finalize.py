"""Tests for cumulative order production rollup + finalization."""

import unittest
import uuid

from app import models
from app.services import aggregation, order_finalize
from tests.db_support import DbTestCase


def _fresh_po(db):
    po = models.PurchaseOrder(
        po_number=f"TEST-{uuid.uuid4().hex[:10]}",
        diameter=7.72, length=108, pd=325, cu=0, weight=66.0, box_type=4700,
        target_qty=1_000_000, produced_qty=0, source="local",
        acetate_type="", paper_type="", pva_glue_type="", hm_glue_type="", triacetin_type="",
    )
    db.add(po)
    db.flush()
    return po


class OrderProductionSummaryTests(DbTestCase):
    def _report(self, shift, po, boxes, rods, waste=0.0, **materials):
        rep = self.make_report(shift, po)
        rep.boxes_produced = boxes
        rep.produced_rods = rods
        rep.waste_kg = waste
        for k, v in materials.items():
            setattr(rep, k, v)
        self.db.flush()
        return rep

    def test_sums_boxes_rods_waste_and_materials(self):
        po = _fresh_po(self.db)
        s = self.make_shift()
        self._report(s, po, 10, 47000, 1.5, total_acetate=2.0, total_paper=3.0,
                     total_pva=0.5, total_hm=0.25, total_triacetin=0.75)
        self._report(s, po, 5, 23500, 0.5, total_acetate=1.0, total_paper=1.5,
                     total_pva=0.25, total_hm=0.1, total_triacetin=0.3)

        out = aggregation.compute_order_production_summary(self.db, po.id)

        self.assertEqual(out["report_count"], 2)
        self.assertEqual(out["total_boxes"], 15)
        self.assertEqual(out["total_rods"], 70500)
        self.assertAlmostEqual(out["total_waste_kg"], 2.0)
        self.assertAlmostEqual(out["materials"]["acetate"], 3.0)
        self.assertAlmostEqual(out["materials"]["paper"], 4.5)
        self.assertAlmostEqual(out["materials"]["pva"], 0.75)
        self.assertAlmostEqual(out["materials"]["hm"], 0.35)
        self.assertAlmostEqual(out["materials"]["triacetin"], 1.05)

    def test_excludes_obsolete_and_deleted(self):
        po = _fresh_po(self.db)
        s = self.make_shift()
        self._report(s, po, 10, 47000)
        obsolete = self.make_report(s, po, status="obsolete")
        obsolete.boxes_produced = 99
        obsolete.produced_rods = 999999
        deleted = self.make_report(s, po, is_deleted=True)
        deleted.boxes_produced = 99
        deleted.produced_rods = 999999
        self.db.flush()

        out = aggregation.compute_order_production_summary(self.db, po.id)

        self.assertEqual(out["total_boxes"], 10)
        self.assertEqual(out["total_rods"], 47000)


class FinalizeOrderTests(DbTestCase):
    def test_finalize_marks_completed_and_snapshots(self):
        po = _fresh_po(self.db)
        s = self.make_shift()
        rep = self.make_report(s, po)
        rep.boxes_produced = 10
        rep.produced_rods = 47000
        rep.waste_kg = 1.0
        self.db.flush()

        out = order_finalize.finalize_order(self.db, po, actor="test", push_odoo=False)

        self.assertEqual(out["completion_status"], "completed")
        self.assertEqual(po.completion_status, "completed")
        self.assertEqual(po.final_boxes, 10)
        self.assertEqual(po.final_rods, 47000)
        self.assertIsNotNone(po.final_materials)
        self.assertIsNotNone(po.final_quality)
        self.assertGreater(out.get("pdf_bytes_len", 0), 0)

    def test_auto_finalize_when_target_reached(self):
        po = _fresh_po(self.db)
        po.target_qty = 47000
        self.db.flush()
        s = self.make_shift()
        rep = self.make_report(s, po)
        rep.produced_rods = 47000
        self.db.flush()

        ran = order_finalize.maybe_auto_finalize(self.db, po, actor="test")

        self.assertTrue(ran)
        self.assertEqual(po.completion_status, "completed")
        self.assertTrue(po.is_hidden)

    def test_auto_finalize_skips_below_target(self):
        po = _fresh_po(self.db)
        po.target_qty = 100000
        self.db.flush()
        s = self.make_shift()
        rep = self.make_report(s, po)
        rep.produced_rods = 47000
        self.db.flush()

        ran = order_finalize.maybe_auto_finalize(self.db, po, actor="test")

        self.assertFalse(ran)
        self.assertEqual(po.completion_status, "active")

    def test_auto_finalize_idempotent_after_completion(self):
        po = _fresh_po(self.db)
        po.target_qty = 47000
        po.completion_status = "completed"
        self.db.flush()
        s = self.make_shift()
        rep = self.make_report(s, po)
        rep.produced_rods = 47000
        self.db.flush()

        ran = order_finalize.maybe_auto_finalize(self.db, po, actor="test")

        self.assertFalse(ran)


if __name__ == "__main__":
    unittest.main()

