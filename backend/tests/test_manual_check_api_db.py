"""Manual QC check endpoints: validation, idempotency, void, permissions."""

import unittest

from fastapi import HTTPException

from app import v2_routes as v2
from tests.db_support import DbTestCase


class ManualCheckApiTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.opened = v2.open_shift(
            v2.ShiftOpen(machine_id=self.m1.id, po_id=self.po_a.id, shift_name="TEST-ONLY"),
            db=self.db, current_user=self.user)
        self.shift_id = self.opened["id"]

    def _check(self, **kw):
        return v2.submit_manual_check(v2.ManualCheckPayload(shift_id=self.shift_id, **kw),
                                      db=self.db, current_user=self.user)

    def test_nothing_to_record_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            self._check()
        self.assertEqual(ctx.exception.status_code, 422)

    def test_unchecked_toggles_are_stored_as_null_not_ok(self):
        c = self._check(notes="just a note")
        self.assertIsNone(c["glue_seam_ok"])
        self.assertIsNone(c["overall_status"])

    def test_weight_is_grams_per_ten_rods(self):
        c = self._check(sample_weight=6.6)
        self.assertEqual(c["sample_rods"], 10)
        self.assertAlmostEqual(c["verdicts"]["weight"]["per_rod"], 0.66)

    def test_offline_resubmission_is_idempotent(self):
        a = self._check(glue_seam_ok=True, client_check_id="dev1-0001")
        b = self._check(glue_seam_ok=True, client_check_id="dev1-0001")
        self.assertEqual(a["id"], b["id"])
        self.assertTrue(b.get("duplicate"))

    def test_void_keeps_the_row_but_hides_it(self):
        c = self._check(glue_seam_ok=True)
        v2.void_manual_check(c["id"], v2.VoidCheckPayload(reason="typo"), db=self.db, current_user=self.user)
        self.assertEqual(v2.list_manual_checks(shift_id=self.shift_id, db=self.db, current_user=self.user), [])
        shown = v2.list_manual_checks(shift_id=self.shift_id, include_voided=True, db=self.db,
                                      current_user=self.user)
        self.assertEqual((len(shown), shown[0]["voided"]), (1, True))

    def test_void_needs_a_reason(self):
        c = self._check(glue_seam_ok=True)
        with self.assertRaises(HTTPException) as ctx:
            v2.void_manual_check(c["id"], v2.VoidCheckPayload(reason=" "), db=self.db, current_user=self.user)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_reassign_is_supervisor_only(self):
        v2.stop_shift(self.shift_id, db=self.db, current_user=self.user)
        plain = type("U", (), {"username": "op", "role": None, "can_edit_report": False, "id": 0})()
        with self.assertRaises(HTTPException) as ctx:
            v2.reassign_run(self.opened["run"]["id"],
                            v2.ReassignRunPayload(po_id=self.po_b.id, reason="fix"),
                            db=self.db, current_user=plain)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_manager_may_reassign(self):
        v2.stop_shift(self.shift_id, db=self.db, current_user=self.user)
        role = type("R", (), {"role_name": "manager", "can_edit_report": False})()
        mgr = type("U", (), {"username": "boss", "role": role, "can_edit_report": False,
                             "id": self.user.id})()
        out = v2.reassign_run(self.opened["run"]["id"],
                              v2.ReassignRunPayload(po_id=self.po_b.id, reason="wrong MO"),
                              db=self.db, current_user=mgr)
        self.assertEqual(out["run"]["po_id"], self.po_b.id)

    def test_triacetin_fallback_is_computed_and_stored(self):
        c = self._check(triacetin_wet_mg=720.0, triacetin_dry_mg=660.0, triacetin_rods=10)
        self.assertAlmostEqual(c["triacetin_pct"], 9.09, places=2)
        self.assertIn("triacetin", c["verdicts"])
        self.assertAlmostEqual(c["verdicts"]["triacetin"]["value"], 9.09, places=2)

    def test_triacetin_needs_positive_dry_weight(self):
        with self.assertRaises(HTTPException) as ctx:
            self._check(triacetin_wet_mg=720.0, triacetin_dry_mg=0.0)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_machine_manual_test_config_roundtrip(self):
        cfg = v2.get_machine_manual_test_config(self.m1.id, db=self.db, current_user=self.user)
        self.assertEqual(
            [p["key"] for p in cfg["parameters"]],
            ["weight", "length", "hardness", "glue_seam", "cut_quality",
             "visual_cleanness", "triacetin"],
        )
        v2.update_machine_manual_test_config(
            self.m1.id,
            v2.ManualTestConfigPayload(
                config={"weight": {"is_visible": False, "is_required": True}},
                reminder_interval_minutes=15,
            ),
            db=self.db, current_user=self.user)
        cfg2 = v2.get_machine_manual_test_config(self.m1.id, db=self.db, current_user=self.user)
        weight = next(p for p in cfg2["parameters"] if p["key"] == "weight")
        self.assertFalse(weight["is_visible"])
        self.assertTrue(weight["is_required"])
        self.assertEqual(cfg2["reminder_interval_minutes"], 15)

    def test_machine_manual_test_config_unknown_machine_404(self):
        with self.assertRaises(HTTPException) as ctx:
            v2.get_machine_manual_test_config(999999, db=self.db, current_user=self.user)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_machine_manual_tests_endpoint(self):
        self._check(length_mm=108.0, hardness=84.0,
                    triacetin_wet_mg=720.0, triacetin_dry_mg=660.0, triacetin_rods=10)
        out = v2.machine_manual_tests(self.m1.id, db=self.db)
        self.assertEqual(out["run_id"], self.opened["run"]["id"])
        self.assertEqual(out["mo_ref"], self.po_a.po_number)
        self.assertEqual(len(out["config"]["parameters"]), 7)
        self.assertEqual(len(out["checks"]), 1)
        row = out["checks"][0]
        self.assertIsNone(row["weight_mg"])
        self.assertAlmostEqual(row["length_mm"], 108.0, places=2)
        self.assertAlmostEqual(row["triacetin_pct"], 9.09, places=2)

    def test_machine_manual_tests_unknown_machine_404(self):
        with self.assertRaises(HTTPException) as ctx:
            v2.machine_manual_tests(999999, db=self.db)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_dashboard_summary_includes_last_manual_test_at(self):
        self._check(glue_seam_ok=True)
        summary = v2.dashboard_summary(db=self.db)
        machine = next(m for m in summary["machines"] if m["machine_id"] == self.m1.id)
        self.assertIsNotNone(machine["last_manual_test_at"])


if __name__ == "__main__":
    unittest.main()

