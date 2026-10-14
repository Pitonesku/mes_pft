"""Shift / run lifecycle against the real schema (see tests/db_support.py)."""

import unittest


from app import models
from app.services import shift_lifecycle as lc
from tests.db_support import DbTestCase


class SwitchMoTests(DbTestCase):
    # D1: the old code hard-coded seq=1 and violated UNIQUE (shift_id, seq)
    def test_switch_creates_next_seq_and_closes_previous(self):
        s = self.make_shift()
        r1 = lc.start_first_run(self.db, s, self.po_a)
        r2, changed = lc.switch_mo(self.db, s, self.user.id, self.po_b, end_counter=123456)
        self.assertTrue(changed)
        self.assertEqual((r1.seq, r2.seq), (1, 2))
        self.assertEqual(r1.status, "CLOSED")
        self.assertEqual(float(r1.end_counter), 123456.0)          # D7
        self.assertEqual((r2.po_id, r2.machine_id), (self.po_b.id, self.m1.id))
        self.assertGreater(r2.started_at, s.started_at)            # D2
        self.assertEqual(r1.ended_at, r2.started_at)
        self.assertEqual(lc.active_run(self.db, s.id).id, r2.id)

    def test_switch_to_same_mo_is_a_noop(self):
        s = self.make_shift()
        r1 = lc.start_first_run(self.db, s, self.po_a)
        r2, changed = lc.switch_mo(self.db, s, self.user.id, self.po_a)
        self.assertFalse(changed)
        self.assertEqual(r1.id, r2.id)

    def test_switch_is_audited(self):
        s = self.make_shift()
        lc.start_first_run(self.db, s, self.po_a)
        r2, _ = lc.switch_mo(self.db, s, self.user.id, self.po_b)
        log = self.db.query(models.RunChangeLog).filter_by(run_id=r2.id).all()
        self.assertEqual([c.action for c in log], ["SWITCH_MO"])
        self.assertEqual(log[0].new_values["po_id"], self.po_b.id)

    def test_switch_on_closed_shift_is_rejected(self):
        s = self.make_shift()
        lc.start_first_run(self.db, s, self.po_a)
        s.ended_at = lc.utcnow()
        with self.assertRaises(lc.LifecycleError) as ctx:
            lc.switch_mo(self.db, s, self.user.id, self.po_b)
        self.assertEqual(ctx.exception.status, 409)

    def test_new_run_snapshot_has_parameters_key(self):        # D5
        r = lc.start_first_run(self.db, self.make_shift(), self.po_a)
        self.assertIn("parameters", r.spec_snapshot)
        self.assertEqual(r.spec_snapshot["pd"], float(self.po_a.pd))


class ChangeMachineTests(DbTestCase):
    def test_keeps_shift_open_and_moves_the_run(self):
        s = self.make_shift()
        r1 = lc.start_first_run(self.db, s, self.po_a)
        r2 = lc.change_machine(self.db, s, self.user.id, self.m2.id, end_counter=777)
        self.assertIsNone(s.ended_at)
        self.assertEqual(s.machine_id, self.m2.id)
        self.assertEqual((r1.machine_id, r2.machine_id), (self.m1.id, self.m2.id))
        self.assertEqual(r2.po_id, self.po_a.id)                   # same MO carried over
        self.assertEqual(r1.status, "CLOSED")
        self.assertEqual(float(r1.end_counter), 777.0)

    def test_rejects_busy_machine(self):
        s = self.make_shift(self.m1)
        lc.start_first_run(self.db, s, self.po_a)
        other = self.make_shift(self.m2)
        lc.start_first_run(self.db, other, self.po_b)
        with self.assertRaises(lc.LifecycleError) as ctx:
            lc.change_machine(self.db, s, self.user.id, self.m2.id)
        self.assertEqual(ctx.exception.status, 409)

    def test_rejects_same_machine(self):
        s = self.make_shift()
        lc.start_first_run(self.db, s, self.po_a)
        with self.assertRaises(lc.LifecycleError):
            lc.change_machine(self.db, s, self.user.id, self.m1.id)


class CloseTests(DbTestCase):
    def test_close_shift_runs_leaves_no_open_run(self):          # D3
        s = self.make_shift()
        lc.start_first_run(self.db, s, self.po_a)
        lc.close_shift_runs(self.db, s, lc.utcnow())
        self.assertIsNone(lc.active_run(self.db, s.id))

    def test_start_closes_orphaned_run_from_an_ended_shift(self):
        # A run left open by an older build (shift auto-closed without closing its
        # run) must not block a new start on the same machine (one_open_run_per_machine).
        ghost = self.make_shift(self.m1)
        ghost_run = lc.start_first_run(self.db, ghost, self.po_a)
        ghost.ended_at = lc.utcnow()          # shift ends, run (wrongly) stays open
        self.db.flush()
        # The busy check would flag the orphan, but a new start must self-heal it
        # instead of erroring (the machine has no genuinely active shift).
        self.assertIsNotNone(lc.machine_busy(self.db, self.m1.id))
        fresh = self.make_shift(self.m1)
        run = lc.start_first_run(self.db, fresh, self.po_b)      # must still work
        self.assertEqual(run.machine_id, self.m1.id)
        self.db.flush()
        # ghost run got closed at the ghost shift's end
        self.assertEqual(ghost_run.status, "CLOSED")
        self.assertIsNotNone(ghost_run.ended_at)
        self.assertEqual(lc.active_run(self.db, fresh.id).id, run.id)

class ReportLinkTests(DbTestCase):
    def test_links_by_mo_when_client_ids_are_missing(self):
        s = self.make_shift()
        lc.start_first_run(self.db, s, self.po_a)
        r2, _ = lc.switch_mo(self.db, s, self.user.id, self.po_b)
        rep = self.make_report(s, self.po_a)
        run = lc.link_report_to_run(self.db, rep)
        self.assertEqual(run.mo_ref, self.po_a.po_number)          # MO-A, not the active MO-B
        self.assertEqual((rep.run_id, run.report_id), (run.id, rep.id))
        self.assertNotEqual(run.id, r2.id)

    def test_ignores_client_run_with_a_different_mo(self):
        s = self.make_shift()
        lc.start_first_run(self.db, s, self.po_a)
        r2, _ = lc.switch_mo(self.db, s, self.user.id, self.po_b)
        rep = self.make_report(s, self.po_a, run_id=r2.id)         # stale context points at MO-B
        self.assertEqual(lc.link_report_to_run(self.db, rep).mo_ref, self.po_a.po_number)

    def test_report_without_matching_run_is_left_unlinked(self):
        s = self.make_shift()
        lc.start_first_run(self.db, s, self.po_a)
        rep = self.make_report(s, self.po_b)
        self.assertIsNone(lc.link_report_to_run(self.db, rep))
        self.assertIsNone(rep.run_id)


if __name__ == "__main__":
    unittest.main()

