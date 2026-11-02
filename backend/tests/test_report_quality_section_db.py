"""Telegram Quality section for production reports: per-order windows, whole
shift for a single order, SD colours from quality_settings."""

import unittest
from datetime import datetime, timedelta, timezone

from app import models
from app.services import report_quality
from tests.db_support import DbTestCase


class ReportQualitySectionTests(DbTestCase):
    def _mk_run(self, shift, po, seq, start, end):
        r = models.ProductionRun(
            shift_id=shift.id, seq=seq, po_id=po.id, mo_ref=po.mo_number,
            machine_id=shift.machine_id, started_at=start, ended_at=end,
            status="CLOSED")
        self.db.add(r)
        self.db.flush()
        return r

    def _mk_rod(self, machine, run, ts, pd, dia, rod_no=1, run_linked=True):
        s = models.QualitySample(
            machine_id=machine.id, produced_at=ts,
            mo_ref="", sample_id="LBL-1",
            link_status="LINKED", kind="PRODUCTION")
        self.db.add(s)
        self.db.flush()
        m = models.QualityMeasurement(
            sample_id=s.id, shift_id=run.shift_id,
            run_id=run.id if run_linked else None,
            machine_id=machine.id, measured_at=ts, rod_no=rod_no,
            pd=pd, diameter=dia)
        self.db.add(m)
        self.db.flush()
        return m

    def _report(self, run, machine, mo, sync_at):
        rep = models.ProductionReport(
            report_date="2020-06-01", shift_name="Shift 2",
            machine_name=machine.name, operator_name="t", mo_number=mo,
            boxes_produced=1, waste_kg=0, run_id=run.id, shift_id=run.shift_id,
            sync_at=sync_at)
        self.db.add(rep)
        self.db.flush()
        return rep

    def test_two_orders_each_gets_its_own_window(self):
        shift = self.make_shift(self.m1)
        t0 = datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc)
        run_a = self._mk_run(shift, self.po_a, 1, t0, t0 + timedelta(hours=4))
        run_b = self._mk_run(shift, self.po_b, 2, t0 + timedelta(hours=4), t0 + timedelta(hours=8))
        # order A rods 14:10-14:20, order B rods 18:10-18:20
        self._mk_rod(self.m1, run_a, t0 + timedelta(minutes=10), 300, 7.70)
        self._mk_rod(self.m1, run_a, t0 + timedelta(minutes=20), 304, 7.74)
        self._mk_rod(self.m1, run_b, t0 + timedelta(hours=4, minutes=10), 400, 7.80)
        self._mk_rod(self.m1, run_b, t0 + timedelta(hours=4, minutes=20), 408, 7.84)

        rep_a = self._report(run_a, self.m1, self.po_a.mo_number, t0 + timedelta(hours=4))
        sec = report_quality.quality_section_text(self.db, rep_a)
        self.assertIsNotNone(sec)
        self.assertIn("Mean PD: 302.00", sec)
        self.assertIn("Mean Dia: 7.7200", sec)
        self.assertIn("SD PD: 2.83", sec)
        self.assertIn("SD Dia: 0.0283", sec)
        self.assertNotIn("400", sec)  # order B rods must not leak in

    def test_single_order_covers_whole_shift(self):
        shift = self.make_shift(self.m1)
        t0 = datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc)
        run = self._mk_run(shift, self.po_a, 1, t0, t0 + timedelta(hours=8))
        self._mk_rod(self.m1, run, t0 + timedelta(hours=1), 300, 7.70)
        self._mk_rod(self.m1, run, t0 + timedelta(hours=7), 306, 7.76)
        rep = self._report(run, self.m1, self.po_a.mo_number, t0 + timedelta(hours=8))
        sec = report_quality.quality_section_text(self.db, rep)
        self.assertIn("Mean PD: 303.00", sec)
        self.assertIn("SD PD: 4.24", sec)

    def test_no_run_omits_section(self):
        rep = models.ProductionReport(
            report_date="2020-06-01", shift_name="Shift 2",
            machine_name=self.m1.name, operator_name="t", mo_number="X",
            boxes_produced=1, waste_kg=0, run_id=None, shift_id=None,
            sync_at=datetime.now(timezone.utc))
        self.db.add(rep)
        self.db.flush()
        self.assertIsNone(report_quality.quality_section_text(self.db, rep))

    def test_sd_colours(self):
        shift = self.make_shift(self.m1)
        t0 = datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc)
        run = self._mk_run(shift, self.po_a, 1, t0, t0 + timedelta(hours=4))
        # PD sd 0.71 (< 12 -> green); DIA values spread to ~0.01485 (yellow band)
        self._mk_rod(self.m1, run, t0 + timedelta(minutes=10), 300, 7.7195)
        self._mk_rod(self.m1, run, t0 + timedelta(minutes=20), 301, 7.7405)
        rep = self._report(run, self.m1, self.po_a.mo_number, t0 + timedelta(hours=4))
        sec = report_quality.quality_section_text(self.db, rep)
        self.assertIn("SD PD: 0.71 \U0001F7E2", sec)     # green circle
        self.assertIn("SD Dia: 0.0148 \U0001F7E1", sec)  # yellow circle
        for line in sec.splitlines():
            if line.startswith("Mean"):
                self.assertNotIn("\U0001F7E2", line)
                self.assertNotIn("\U0001F7E1", line)
                self.assertNotIn("\U0001F534", line)

    def test_label_matched_rods_are_included(self):
        shift = self.make_shift(self.m1)
        t0 = datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc)
        run = self._mk_run(shift, self.po_a, 1, t0, t0 + timedelta(hours=4))
        self._mk_rod(self.m1, run, t0 + timedelta(minutes=10), 300, 7.70)
        # a rod without run_id whose sample carries the order label still counts
        s = models.QualitySample(machine_id=self.m1.id, produced_at=t0,
                                 mo_ref="", sample_id=self.po_a.mo_number,
                                 link_status="FIXED_WINDOW", kind="PRODUCTION")
        self.db.add(s)
        self.db.flush()
        self.db.add(models.QualityMeasurement(
            sample_id=s.id, shift_id=run.shift_id, run_id=None,
            machine_id=self.m1.id, measured_at=t0 + timedelta(minutes=30),
            rod_no=2, pd=306, diameter=7.76))
        self.db.flush()
        rep = self._report(run, self.m1, self.po_a.mo_number, t0 + timedelta(hours=4))
        sec = report_quality.quality_section_text(self.db, rep)
        self.assertIn("Mean PD: 303.00", sec)  # (300+306)/2 -> both rods included
        self.assertIn("SD PD: 4.24", sec)

    def test_three_orders_in_one_shift(self):
        # 101 14:00-16:00, 102 16:00-18:00, 103 18:00-20:00 on the same shift.
        shift = self.make_shift(self.m1)
        t0 = datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc)
        pos = [self.po_a, self.po_b, None]
        third = models.PurchaseOrder(mo_number="T-103", target_qty=1000,
                                     cu=0, weight=0, box_type=1, acetate_type="a",
                                     paper_type="p", pva_glue_type="v", hm_glue_type="h",
                                     triacetin_type="t", diameter=7.7, length=108, pd=320)
        self.db.add(third)
        self.db.flush()
        runs = []
        for i, po in enumerate([self.po_a, self.po_b, third]):
            runs.append(self._mk_run(shift, po, i + 1, t0 + timedelta(hours=2 * i),
                                     t0 + timedelta(hours=2 * (i + 1))))
        # rods per order: 300/302 | 400/406 | 500/506
        self._mk_rod(self.m1, runs[0], t0 + timedelta(minutes=10), 300, 7.70)
        self._mk_rod(self.m1, runs[0], t0 + timedelta(minutes=20), 302, 7.72)
        self._mk_rod(self.m1, runs[1], t0 + timedelta(hours=2, minutes=10), 400, 7.80)
        self._mk_rod(self.m1, runs[1], t0 + timedelta(hours=2, minutes=20), 406, 7.86)
        self._mk_rod(self.m1, runs[2], t0 + timedelta(hours=4, minutes=10), 500, 7.90)
        self._mk_rod(self.m1, runs[2], t0 + timedelta(hours=4, minutes=20), 506, 7.96)
        rep = self._report(runs[1], self.m1, self.po_b.mo_number, t0 + timedelta(hours=4))
        sec = report_quality.quality_section_text(self.db, rep)
        self.assertIn("Mean PD: 403.00", sec)   # only order 102's rods
        self.assertIn("SD PD: 4.24", sec)
        self.assertNotIn("Mean PD: 300", sec)
        self.assertNotIn("Mean PD: 500", sec)

    def test_boundary_rod_belongs_to_next_order(self):
        shift = self.make_shift(self.m1)
        t0 = datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc)
        run_a = self._mk_run(shift, self.po_a, 1, t0, t0 + timedelta(hours=2))
        run_b = self._mk_run(shift, self.po_b, 2, t0 + timedelta(hours=2), t0 + timedelta(hours=4))
        # a rod measured exactly at the switch instant: belongs to order B
        self._mk_rod(self.m1, run_b, t0 + timedelta(hours=2), 400, 7.80)
        rep_a = self._report(run_a, self.m1, self.po_a.mo_number, t0 + timedelta(hours=2))
        sec_a = report_quality.quality_section_text(self.db, rep_a)
        self.assertIsNone(sec_a)  # nothing in order A's window
        rep_b = self._report(run_b, self.m1, self.po_b.mo_number, t0 + timedelta(hours=4))
        sec_b = report_quality.quality_section_text(self.db, rep_b)
        self.assertIn("Mean PD: 400.00", sec_b)

    def test_late_sync_clamped_to_run_end(self):
        shift = self.make_shift(self.m1)
        t0 = datetime(2020, 6, 1, 12, 0, tzinfo=timezone.utc)
        run_a = self._mk_run(shift, self.po_a, 1, t0, t0 + timedelta(hours=2))
        self._mk_run(shift, self.po_b, 2, t0 + timedelta(hours=2), t0 + timedelta(hours=4))
        self._mk_rod(self.m1, run_a, t0 + timedelta(minutes=10), 300, 7.70)
        # a later rod of the SAME order label, run-less, after run A ended
        s = models.QualitySample(machine_id=self.m1.id, produced_at=t0,
                                 mo_ref="", sample_id=self.po_a.mo_number,
                                 link_status="FIXED_WINDOW", kind="PRODUCTION")
        self.db.add(s)
        self.db.flush()
        self.db.add(models.QualityMeasurement(
            sample_id=s.id, shift_id=run_a.shift_id, run_id=None,
            machine_id=self.m1.id, measured_at=t0 + timedelta(hours=4, minutes=10),
            rod_no=2, pd=310, diameter=7.80))
        self.db.flush()
        # report A synced very late (during the next orders) without an original timestamp
        rep = self._report(run_a, self.m1, self.po_a.mo_number, t0 + timedelta(hours=5))
        sec = report_quality.quality_section_text(self.db, rep)
        self.assertIn("Mean PD: 300.00", sec)
        self.assertIn("SD PD: \u2014", sec)  # single rod -> no SD
        self.assertNotIn("310", sec)


if __name__ == "__main__":
    unittest.main()