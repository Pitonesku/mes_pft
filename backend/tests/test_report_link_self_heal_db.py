"""Report->run linking self-heal: an order-less report on a shift that ran
exactly ONE order is linked to it and the MO is backfilled additively."""

import unittest
from datetime import datetime, timedelta, timezone

from app import models
from app.services import shift_lifecycle
from tests.db_support import DbTestCase


class ReportLinkSelfHealTests(DbTestCase):
    def _mk_run(self, shift, po, seq):
        start = datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc)
        r = models.ProductionRun(
            shift_id=shift.id, seq=seq, po_id=po.id, mo_ref=po.mo_number,
            machine_id=shift.machine_id, started_at=start,
            ended_at=start + timedelta(hours=2), status="CLOSED")
        self.db.add(r)
        self.db.flush()
        return r

    def _orderless_report(self, shift, machine):
        rep = models.ProductionReport(
            report_date="2020-06-01", shift_name="Shift 2",
            machine_name=machine.name, operator_name="t", mo_number=None,
            boxes_produced=1, waste_kg=0, shift_id=shift.id, run_id=None,
            sync_at=datetime(2020, 6, 1, 14, 0, tzinfo=timezone.utc))
        self.db.add(rep)
        self.db.flush()
        return rep

    def test_single_run_shift_links_and_backfills(self):
        shift = self.make_shift(self.m1)
        run = self._mk_run(shift, self.po_a, 1)
        rep = self._orderless_report(shift, self.m1)
        linked = shift_lifecycle.link_report_to_run(self.db, rep)
        self.assertEqual(linked.id, run.id)
        self.assertEqual(rep.run_id, run.id)
        self.assertEqual(rep.mo_number, self.po_a.mo_number)  # additive backfill
        self.db.flush()
        self.db.refresh(run)
        self.assertEqual(run.report_id, rep.id)

    def test_multi_run_shift_is_not_guessed(self):
        shift = self.make_shift(self.m1)
        self._mk_run(shift, self.po_a, 1)
        self._mk_run(shift, self.po_b, 2)
        rep = self._orderless_report(shift, self.m1)
        linked = shift_lifecycle.link_report_to_run(self.db, rep)
        self.assertIsNone(linked)
        self.assertIsNone(rep.run_id)
        self.assertIsNone(rep.mo_number)

    def test_existing_mo_is_never_overwritten(self):
        shift = self.make_shift(self.m1)
        self._mk_run(shift, self.po_a, 1)
        rep = self._orderless_report(shift, self.m1)
        rep.mo_number = "KEEP-ME"
        self.db.flush()
        linked = shift_lifecycle.link_report_to_run(self.db, rep)
        # different MO than the single run -> no run, and the MO stays untouched
        self.assertIsNone(linked)
        self.assertEqual(rep.mo_number, "KEEP-ME")


if __name__ == "__main__":
    unittest.main()