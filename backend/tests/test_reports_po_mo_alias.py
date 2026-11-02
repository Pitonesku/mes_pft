"""Regression: legacy report endpoints must expose BOTH ``po_number`` (legacy
clients/schemas) and ``mo_number`` (column) after migration 0030 renamed the
column. Without the alias, GET /api/reports failed response validation with
500 ('Field required' at response[i].po_number)."""

import unittest

from app import legacy_routes
from tests.db_support import DbTestCase


class ReportsPoMoAliasTests(DbTestCase):
    def test_get_reports_rows_expose_po_number_alias(self):
        shift = self.make_shift()
        self.make_report(shift, self.po_a)
        rows = legacy_routes.get_reports(
            start_date="2026-10-09", end_date="2026-10-11", db=self.db)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("po_number", row)
            self.assertIn("mo_number", row)
            self.assertEqual(row["po_number"], row["mo_number"])

    def test_last_by_machine_exposes_po_number_alias(self):
        shift = self.make_shift()
        self.make_report(shift, self.po_a)
        row = legacy_routes.get_last_report_by_machine(
            machine_name=self.m1.name, db=self.db)
        self.assertEqual(row["po_number"], row["mo_number"])

    def test_get_report_by_id_exposes_po_number_alias(self):
        shift = self.make_shift()
        rep = self.make_report(shift, self.po_a)
        self.db.flush()
        row = legacy_routes.get_report_by_id(rep.id, db=self.db)
        self.assertEqual(row["po_number"], row["mo_number"])


if __name__ == "__main__":
    unittest.main()