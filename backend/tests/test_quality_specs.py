
"""Unit tests for the quality-spec selection rule (no cross-order borrowing)."""

import unittest
from types import SimpleNamespace

from app import v2_routes
from app.services.odoo import reconcile  # noqa: F401 - ensure package import path works
from app.services import aggregation


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def order_by(self, *a):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, rows=None, run_rows=None):
        self._spec_rows = rows or []
        self._run_rows = run_rows or []

    def query(self, model):
        if getattr(model, "__name__", "") == "ProductionRun":
            return _Q(self._run_rows)
        return _Q(self._spec_rows)


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

    def test_all_view_uses_most_recent_order_spec(self):
        spec = self._spec()
        run = SimpleNamespace(po_id=27)
        db = _DB(rows=[spec], run_rows=[run])
        specs, missing = v2_routes._specs_for_context(db, None, po_id=None, shift_id=None)
        self.assertEqual(list(specs.keys()), ["pd"])
        self.assertFalse(missing)

    def test_all_view_without_any_run_stays_missing(self):
        db = _DB(rows=[self._spec()], run_rows=[])
        specs, missing = v2_routes._specs_for_context(db, None, po_id=None, shift_id=None)
        self.assertEqual(specs, {})
        self.assertTrue(missing)


class WeightSpecNormalizationTests(unittest.TestCase):
    def test_weight_mg_per_rod_scale_1000_normalizes_to_g_per_rod(self):
        spec = SimpleNamespace(
            parameter="weight", nominal=666.0, lower_limit=646.0, upper_limit=686.0,
            reject_multiplier=3, report_unit="mg", report_scale=1000, decimals=3,
        )
        specs = aggregation.build_param_specs([spec])
        w = specs["weight"]
        self.assertAlmostEqual(w.nominal, 0.666, places=3)
        self.assertAlmostEqual(w.lower, 0.646, places=3)
        self.assertAlmostEqual(w.upper, 0.686, places=3)
        self.assertEqual(w.report_scale, 1000.0)
        self.assertEqual(w.report_unit, "mg")
        low, high = w.reject_bounds()
        self.assertAlmostEqual(low, 0.606, places=3)
        self.assertAlmostEqual(high, 0.726, places=3)


if __name__ == "__main__":
    unittest.main()
