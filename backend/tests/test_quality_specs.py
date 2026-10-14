
"""Unit tests for the quality-spec selection rule (no cross-order borrowing)."""

import unittest
from types import SimpleNamespace

from app import v2_routes
from app.services.odoo import reconcile  # noqa: F401 - ensure package import path works


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._rows


class _DB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, model):
        return _Q(self._rows)


class SpecsForContextTests(unittest.TestCase):
    def _spec(self, parameter="pd", nominal=325.0):
        return SimpleNamespace(
            parameter=parameter, nominal=nominal, lower_limit=310.0, upper_limit=345.0,
            reject_multiplier=3, report_unit="mm WG", report_scale=1, decimals=1,
        )

    def test_selected_po_with_specs_returns_them_not_missing(self):
        db = _DB(rows=[self._spec()])
        specs, missing = v2_routes._specs_for_context(db, None, po_id=27, shift_id=None)
        self.assertEqual(list(specs.keys()), ["pd"])
        self.assertFalse(missing)

    def test_selected_po_without_specs_marks_missing_and_does_not_borrow(self):
        db = _DB(rows=[])
        specs, missing = v2_routes._specs_for_context(db, None, po_id=27, shift_id=None)
        self.assertEqual(specs, {})
        self.assertTrue(missing)


if __name__ == "__main__":
    unittest.main()
