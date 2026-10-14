"""End-to-end operator flow through the real v2 route functions (rolled back afterwards)."""

import unittest

from fastapi import HTTPException

from app import models, v2_routes as v2
from tests.db_support import DbTestCase


class OperatorFlowTests(DbTestCase):
    def _open(self, machine, po, **kw):
        return v2.open_shift(
            v2.ShiftOpen(machine_id=machine.id, po_id=po.id, shift_name="TEST-ONLY", **kw),
            db=self.db, current_user=self.user)

    def _check(self, shift_id, **kw):
        return v2.submit_manual_check(v2.ManualCheckPayload(shift_id=shift_id, **kw),
                                      db=self.db, current_user=self.user)

    def test_full_shift_with_mo_switch_machine_change_and_qc(self):
        opened = self._open(self.m1, self.po_a)
        shift_id, run1 = opened["id"], opened["run"]
        self.assertEqual((run1["seq"], run1["machine_id"], run1["mo_ref"]),
                         (1, self.m1.id, self.po_a.po_number))

        # the server binds the check to the open run, whatever mo_id the client sends
        c1 = self._check(shift_id, mo_id=999999, glue_seam_ok=True, notes="ok")
        self.assertEqual((c1["run_id"], c1["mo_ref"], c1["machine_id"]),
                         (run1["id"], self.po_a.po_number, self.m1.id))

        sw = v2.switch_mo(shift_id, v2.SwitchMoPayload(po_id=self.po_b.id, end_counter=5000),
                          db=self.db, current_user=self.user)
        self.assertEqual((sw["seq"], sw["mo_ref"], sw["changed"]), (2, self.po_b.po_number, True))
        c2 = self._check(shift_id, cut_quality_ok=False)
        self.assertEqual((c2["mo_ref"], c2["overall_status"]), (self.po_b.po_number, "FAIL"))

        # the whole shift timeline stays visible, grouped by MO
        allc = v2.list_manual_checks(shift_id=shift_id, db=self.db, current_user=self.user)
        self.assertEqual({c["mo_ref"] for c in allc}, {self.po_a.po_number, self.po_b.po_number})

        moved = v2.change_machine(shift_id, v2.ChangeMachinePayload(machine_id=self.m2.id, end_counter=900),
                                  db=self.db, current_user=self.user)
        self.assertEqual((moved["machine_id"], moved["run"]["machine_id"], moved["run"]["seq"]),
                         (self.m2.id, self.m2.id, 3))
        self.assertEqual(self._check(shift_id, visual_appearance_ok=True)["machine_id"], self.m2.id)

        summary = v2.close_shift(shift_id, v2.ShiftClose(), db=self.db, current_user=self.user,
                                 idempotency_key=None)
        runs = summary["runs"]
        self.assertEqual([r["mo_ref"] for r in runs],
                         [self.po_a.po_number, self.po_b.po_number, self.po_b.po_number])
        self.assertEqual([r["machine_id"] for r in runs], [self.m1.id, self.m1.id, self.m2.id])
        self.assertEqual([r["manual_checks"]["count"] for r in runs], [1, 1, 1])
        self.assertEqual(runs[1]["manual_checks"]["failed"], 1)
        self.assertEqual(
            self.db.query(models.ProductionRun).filter_by(shift_id=shift_id, ended_at=None).count(), 0)

        with self.assertRaises(HTTPException) as ctx:      # a closed shift refuses new checks
            self._check(shift_id, notes="late")
        self.assertIn(ctx.exception.status_code, (404, 409))

    def test_takeover_frees_the_machine_for_the_next_shift(self):
        first = self._open(self.m1, self.po_a)
        second = self._open(self.m1, self.po_b, takeover=True)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(
            self.db.query(models.ProductionRun).filter_by(shift_id=first["id"], ended_at=None).count(), 0)

    def test_machine_already_open_without_takeover_is_409(self):
        self._open(self.m1, self.po_a)
        with self.assertRaises(HTTPException) as ctx:
            self._open(self.m1, self.po_b)
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()

