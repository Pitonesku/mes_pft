"""Manual QC check evaluation: grams per 10 rods, tri-state toggles, spec units."""

import unittest

from app.quality_stats import ParamSpec
from app.services import manual_check_rules as rules


def _weight_spec(nominal, lower, upper, scale=1.0, reject_multiplier=3.0):
    return ParamSpec(parameter="weight", nominal=nominal, lower=lower, upper=upper,
                     report_scale=scale, reject_multiplier=reject_multiplier)


def _eval(specs, **kw):
    base = dict(sample_weight=None, sample_rods=10, length_mm=None, hardness=None,
                glue_seam_ok=None, cut_quality_ok=None, visual_appearance_ok=None)
    base.update(kw)
    return rules.evaluate(specs, **base)


class WeightUnitTests(unittest.TestCase):
    def test_per_rod_spec_compares_grams_per_rod(self):
        specs = {"weight": _weight_spec(0.66, 0.64, 0.68)}
        verdicts, overall = _eval(specs, sample_weight=6.6)      # 6.6 g / 10 rods = 0.66
        self.assertEqual(verdicts["weight"]["status"], "PASS")
        self.assertAlmostEqual(verdicts["weight"]["per_rod"], 0.66)
        self.assertEqual(overall, "PASS")

    def test_out_of_limits_fails(self):
        specs = {"weight": _weight_spec(0.66, 0.64, 0.68)}
        verdicts, overall = _eval(specs, sample_weight=7.2)
        self.assertEqual(verdicts["weight"]["status"], "FAIL")
        self.assertEqual(overall, "FAIL")

    def test_spec_stored_per_100_rods_is_converted_back_to_per_rod(self):
        # The Odoo importer writes weight limits in g / 100 rods (scale 100).
        specs = {"weight": _weight_spec(66.6, 64.4, 68.8, scale=100)}
        verdicts, _ = _eval(specs, sample_weight=6.66)
        self.assertEqual(verdicts["weight"]["status"], "PASS")
        self.assertAlmostEqual(verdicts["weight"]["target"], 0.666)

    def test_scaled_spec_with_small_nominal_is_left_alone(self):
        # nominal 0.62 g with scale 100: already per rod, must not be divided again.
        n, lo, up = rules.weight_limits_per_rod(_weight_spec(0.62, 0.6, 0.64, scale=100))
        self.assertAlmostEqual(n, 0.62)

    def test_custom_sample_size(self):
        specs = {"weight": _weight_spec(0.66, 0.64, 0.68)}
        verdicts, _ = _eval(specs, sample_weight=13.2, sample_rods=20)
        self.assertEqual(verdicts["weight"]["status"], "PASS")

    def test_non_positive_sample_rods_falls_back_to_default(self):
        specs = {"weight": _weight_spec(0.66, 0.64, 0.68)}
        verdicts, _ = _eval(specs, sample_weight=6.6, sample_rods=0)
        self.assertEqual(verdicts["weight"]["sample_rods"], 10)


class WeightNormalizationTests(unittest.TestCase):
    def _norm(self, raw, rods=10, spec=None):
        return rules.normalize_manual_weight(raw, rods, spec)

    def test_comma_total_grams(self):
        n = self._norm("6,67", 10)
        self.assertTrue(n.ok)
        self.assertAlmostEqual(n.per_rod_g, 0.667, places=5)
        self.assertEqual(n.unit, "g_total")

    def test_mg_per_rod(self):
        n = self._norm("667", 10)
        self.assertTrue(n.ok)
        self.assertAlmostEqual(n.per_rod_g, 0.667, places=5)
        self.assertEqual(n.unit, "mg_per_rod")

    def test_large_sample_total_grams(self):
        n = self._norm("33,8", 50)
        self.assertTrue(n.ok)
        self.assertAlmostEqual(n.per_rod_g, 0.676, places=5)
        self.assertEqual(n.unit, "g_total")

    def test_mg_total(self):
        n = self._norm("6670", 10)
        self.assertTrue(n.ok)
        self.assertAlmostEqual(n.per_rod_g, 0.667, places=5)
        self.assertEqual(n.unit, "mg_total")

    def test_grams_per_rod(self):
        n = self._norm("0.667", 10)
        self.assertTrue(n.ok)
        self.assertAlmostEqual(n.per_rod_g, 0.667, places=5)
        self.assertEqual(n.unit, "g_per_rod")

    def test_ambiguous_rod_count_is_rejected(self):
        n = self._norm("33,8", 10)
        self.assertFalse(n.ok)
        self.assertIn("10 rods", n.error)

    def test_garbage_is_not_ok(self):
        self.assertFalse(self._norm("abc", 10).ok)
        self.assertFalse(self._norm("", 10).ok)
        self.assertFalse(self._norm(None, 10).ok)

    def test_total_g_consistent_with_per_rod(self):
        n = self._norm("6,67", 10)
        self.assertAlmostEqual(n.total_g, n.per_rod_g * 10, places=5)


class WeightRejectionTests(unittest.TestCase):
    def test_within_3x_tolerance_is_kept(self):
        specs = {"weight": _weight_spec(0.666, 0.646, 0.686)}
        verdicts, _ = _eval(specs, sample_weight=6.67)  # 0.667 g/rod
        self.assertFalse(verdicts["weight"]["rejected"])
        self.assertEqual(verdicts["weight"]["status"], "PASS")

    def test_out_of_spec_but_within_3x_tolerance_is_fail_not_rejected(self):
        specs = {"weight": _weight_spec(0.666, 0.646, 0.686)}
        # 0.62 g/rod is below lower 0.646 -> FAIL, but inside the 3x band (0.606..0.726).
        verdicts, _ = _eval(specs, sample_weight=6.2)
        self.assertEqual(verdicts["weight"]["status"], "FAIL")
        self.assertFalse(verdicts["weight"]["rejected"])

    def test_beyond_3x_tolerance_is_rejected(self):
        specs = {"weight": _weight_spec(0.666, 0.646, 0.686)}
        # 900 mg/rod -> 9.0 g for 10 rods, far outside the 3x band.
        verdicts, _ = _eval(specs, sample_weight=9.0)
        self.assertTrue(verdicts["weight"]["rejected"])
        self.assertEqual(verdicts["weight"]["status"], "FAIL")

    def test_mg_per_rod_input_is_normalized_then_evaluated(self):
        specs = {"weight": _weight_spec(0.666, 0.646, 0.686)}
        verdicts, _ = _eval(specs, sample_weight=667)  # operator typed mg/rod
        self.assertAlmostEqual(verdicts["weight"]["per_rod"], 0.667, places=5)
        self.assertEqual(verdicts["weight"]["status"], "PASS")
        self.assertEqual(verdicts["weight"]["unit"], "mg_per_rod")


class OverallStatusTests(unittest.TestCase):
    def test_no_limits_and_nothing_checked_is_none(self):
        verdicts, overall = _eval({}, sample_weight=6.6)
        self.assertIsNone(verdicts["weight"]["status"])
        self.assertIsNone(overall)

    def test_unchecked_toggles_are_not_counted_as_pass(self):
        verdicts, overall = _eval({})
        self.assertEqual(verdicts, {})
        self.assertIsNone(overall)

    def test_single_failed_toggle_fails_the_check(self):
        verdicts, overall = _eval({}, glue_seam_ok=True, cut_quality_ok=False)
        self.assertEqual(verdicts["cut_quality"]["status"], "FAIL")
        self.assertEqual(overall, "FAIL")

    def test_all_ok_toggles_pass(self):
        _, overall = _eval({}, glue_seam_ok=True, cut_quality_ok=True, visual_appearance_ok=True)
        self.assertEqual(overall, "PASS")

    def test_length_limits(self):
        specs = {"length": ParamSpec(parameter="length", nominal=108, lower=107.5, upper=108.5)}
        self.assertEqual(_eval(specs, length_mm=108.2)[1], "PASS")
        self.assertEqual(_eval(specs, length_mm=109.0)[1], "FAIL")

    def test_length_without_limits_is_not_assessed(self):
        specs = {"length": ParamSpec(parameter="length", nominal=108)}
        self.assertIsNone(_eval(specs, length_mm=108.2)[1])

    def test_hardness_limits(self):
        specs = {"hardness": ParamSpec(parameter="hardness", nominal=82, lower=82, upper=None)}
        self.assertEqual(_eval(specs, hardness=84.0)[1], "PASS")
        self.assertEqual(_eval(specs, hardness=80.0)[1], "FAIL")

    def test_hardness_without_limits_is_not_assessed(self):
        specs = {"hardness": ParamSpec(parameter="hardness", nominal=82)}
        self.assertIsNone(_eval(specs, hardness=84.0)[1])


if __name__ == "__main__":
    unittest.main()
