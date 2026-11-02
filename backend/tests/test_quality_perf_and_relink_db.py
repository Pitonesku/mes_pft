"""QC overview performance + relink rules.

* The heavy certificate-style ``report`` payload (compute_order_summary took
  ~13 s for a large PO) is computed only on demand (include_report/include_raw).
* The relink sweep processes only samples that carry an order (mo_ref).
* /quality/unlinked-summary exposes the true totals behind the (capped) card.
"""

import unittest
from datetime import datetime, timezone
from unittest import mock

from app import models, v2_routes
from tests.db_support import DbTestCase


def _mk_sample(db, machine, mo_ref, ts):
    s = models.QualitySample(
        machine_id=machine.id, produced_at=ts, mo_ref=mo_ref,
        link_status="NO_SHIFT", kind="PRODUCTION", sample_id="X1")
    db.add(s)
    db.flush()
    return s


class QualityOverviewReportOnDemandTests(DbTestCase):
    def _call(self, **kw):
        defaults = dict(
            machine=None, po_id=None, shift_id=None, report_id=None, date=None,
            shift_name=None, window="rods", window_value=50, page=1, page_size=50,
            fmt="json", include_raw=False, fixed_shift=None, include_report=False,
            db=self.db)
        defaults.update(kw)
        return v2_routes.quality_overview(**defaults)

    def test_report_not_computed_by_default(self):
        with mock.patch.object(v2_routes, "_quality_report_payload") as heavy:
            out = self._call(po_id=self.po_a.id, window="rods")
        heavy.assert_not_called()
        self.assertIsNone(out["report"])

    def test_report_computed_with_include_report(self):
        with mock.patch.object(v2_routes, "_quality_report_payload", return_value={"x": 1}) as heavy:
            out = self._call(po_id=self.po_a.id, window="rods", include_report=True)
        heavy.assert_called_once()
        self.assertEqual(out["report"], {"x": 1})

    def test_report_computed_with_include_raw(self):
        with mock.patch.object(v2_routes, "_quality_report_payload", return_value={"x": 2}) as heavy:
            out = self._call(po_id=self.po_a.id, window="rods", include_raw=True)
        heavy.assert_called_once()
        self.assertEqual(out["report"], {"x": 2})


class RelinkOrderOnlyTests(DbTestCase):
    def setUp(self):
        super().setUp()
        # Park every pre-existing unlinked sample so counts are deterministic.
        self.db.query(models.QualitySample).filter(
            models.QualitySample.shift_id.is_(None)
        ).update({"shift_id": None, "link_status": "PARKED"}, synchronize_session=False)
        self.admin = self.user

    def test_summary_splits_with_and_without_order(self):
        ts = datetime(2018, 3, 3, 10, 0, tzinfo=timezone.utc)
        before = self._summary()
        _mk_sample(self.db, self.m1, "", ts)
        _mk_sample(self.db, self.m1, "2610/110", ts)
        after = self._summary()
        self.assertEqual(after["without_order"], before["without_order"] + 1)
        self.assertEqual(after["with_order"], before["with_order"] + 1)

    def _summary(self):
        with mock.patch.object(v2_routes, "_require_superadmin", return_value=None):
            return v2_routes.unlinked_summary(db=self.db, current_user=self.admin)

    def test_relink_skips_samples_without_order(self):
        ts = datetime(2018, 3, 3, 10, 0, tzinfo=timezone.utc)
        no_order = _mk_sample(self.db, self.m1, "", ts)
        with mock.patch.object(v2_routes, "_require_superadmin", return_value=None):
            res = v2_routes.relink_unlinked(db=self.db, current_user=self.admin)
        self.db.refresh(no_order)
        self.assertIsNone(no_order.shift_id)
        self.assertGreaterEqual(res["without_order"], 1)
        self.assertEqual(res["relinked"], 0)


if __name__ == "__main__":
    unittest.main()