"""Supervisor corrections of closed runs (see tests/db_support.py)."""

import unittest

from app import models
from app.services import run_corrections, shift_lifecycle as lc
from tests.db_support import DbTestCase


class ReassignTests(DbTestCase):
    def _closed_run(self):
        s = self.make_shift()
        run = lc.start_first_run(self.db, s, self.po_a)
        check = models.ManualQualityCheck(
            shift_id=s.id, mo_id=run.id, machine_id=run.machine_id, po_id=run.po_id,
            mo_ref=run.mo_ref, operator_id=self.user.id, sample_rods=10)
        report = self.make_report(s, self.po_a, run_id=run.id, produced_rods=1000,
                                  verification_status="approved")
        self.db.add(check)
        lc.close_shift_runs(self.db, s, lc.utcnow())
        s.ended_at = lc.utcnow()
        self.db.flush()
        return s, run, check, report

    def _reassign(self, run, **kw):
        args = dict(po=self.po_b, machine_id=None, reason="wrong MO selected", allow_synced=False)
        args.update(kw)
        return run_corrections.reassign_run(self.db, run, self.user, **args)

    def test_cascades_to_checks_and_reports_and_is_audited(self):
        s, run, check, report = self._closed_run()
        res = self._reassign(run, machine_id=self.m2.id)
        self.assertEqual((run.po_id, run.machine_id), (self.po_b.id, self.m2.id))
        self.assertEqual((check.po_id, check.mo_ref, check.machine_id),
                         (self.po_b.id, self.po_b.po_number, self.m2.id))
        self.assertEqual((report.po_number, report.machine_name), (self.po_b.po_number, self.m2.name))
        self.assertEqual(report.verification_status, "pending")    # must be re-approved
        self.assertEqual((res["checks_updated"], res["reports_updated"]), (1, 1))
        log = self.db.query(models.RunChangeLog).filter_by(run_id=run.id).one()
        self.assertEqual(log.reason, "wrong MO selected")
        self.assertEqual(self.db.query(models.ReportEditLog).filter_by(report_id=report.id).count(), 1)

    def test_requires_a_reason(self):
        _, run, _, _ = self._closed_run()
        with self.assertRaises(lc.LifecycleError) as ctx:
            self._reassign(run, reason="  ")
        self.assertEqual(ctx.exception.status, 400)

    def test_synced_run_needs_an_admin(self):
        _, run, _, _ = self._closed_run()
        run.odoo_sync_status = "synced"
        with self.assertRaises(lc.LifecycleError) as ctx:
            self._reassign(run)
        self.assertEqual(ctx.exception.status, 409)
        self._reassign(run, allow_synced=True)
        self.assertEqual(run.po_id, self.po_b.id)

    def test_active_run_cannot_be_reassigned(self):
        run = lc.start_first_run(self.db, self.make_shift(), self.po_a)
        with self.assertRaises(lc.LifecycleError) as ctx:
            self._reassign(run)
        self.assertEqual(ctx.exception.status, 409)

    def test_marks_latest_shift_summary_stale(self):
        s, run, _, _ = self._closed_run()
        summary = models.ShiftSummary(shift_id=s.id, version=1, payload={}, is_stale=False)
        self.db.add(summary)
        self.db.flush()
        self._reassign(run)
        self.assertTrue(summary.is_stale)


if __name__ == "__main__":
    unittest.main()
