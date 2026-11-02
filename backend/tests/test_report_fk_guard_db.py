"""Report insert FK guards: a stale client run_id/shift_id must never fail the
insert (production_reports_run_id_fkey) and lose the whole report."""

import unittest

from app import legacy_routes
from tests.db_support import DbTestCase


class ReportFkGuardTests(DbTestCase):
    def test_stale_ids_are_dropped(self):
        p = {"run_id": 99999999, "shift_id": 99999999, "parent_report_id": 99999999}
        legacy_routes._sanitize_report_fk_hints(p, self.db)
        self.assertIsNone(p["run_id"])
        self.assertIsNone(p["shift_id"])
        self.assertIsNone(p["parent_report_id"])

    def test_valid_ids_survive(self):
        shift = self.make_shift()
        p = {"run_id": None, "shift_id": shift.id, "parent_report_id": None}
        legacy_routes._sanitize_report_fk_hints(p, self.db)
        self.assertEqual(p["shift_id"], shift.id)
        self.assertIsNone(p["run_id"])


if __name__ == "__main__":
    unittest.main()