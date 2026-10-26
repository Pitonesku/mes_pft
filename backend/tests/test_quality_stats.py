"""Tests for quality_stats. Run from production_api/:  python -m unittest discover -s tests -t ."""

import unittest

from app import quality_stats as qs
from app.quality_stats import ParamSpec

# One real sample file from the quality station (Quantum Neo, 10 rods).
# Footer printed by the instrument: PD mean 322.7 / SD 9.452,
# diameter mean 7.744 / SD 0.012, weight mean 0.6641 / SD 0.006.
STATION_RODS = [
    {"pd": pd, "weight": w, "diameter": d}
    for pd, w, d in [
        (322, 0.664, 7.74), (322, 0.662, 7.74), (317, 0.662, 7.74), (335, 0.669, 7.73),
        (314, 0.660, 7.76), (310, 0.656, 7.76), (336, 0.674, 7.74), (325, 0.666, 7.74),
        (333, 0.670, 7.73), (313, 0.658, 7.76),
    ]
]

# Limits taken from the customer certificates (E050 / H087).
CERT_SPECS = {
    "diameter": ParamSpec("diameter", 7.72, 7.69, 7.75, reject_multiplier=3, report_unit="mm", decimals=3),
    "pd": ParamSpec("pd", 325, 310, 350, reject_multiplier=3, report_unit="mm WG", decimals=1),
    "weight": ParamSpec("weight", 0.666, 0.651, 0.681, report_unit="g/100", report_scale=100, decimals=1),
    "hardness": ParamSpec("hardness", 82, 82, None, report_unit="%", decimals=1),
}
PD_ONLY = {"pd": CERT_SPECS["pd"]}


class StationFooterAgreement(unittest.TestCase):
    """Our numbers must match what the instrument itself prints."""

    def setUp(self):
        self.stats = qs.compute_run_stats(STATION_RODS, CERT_SPECS)

    def test_pd_matches_footer(self):
        pd = self.stats["parameters"]["pd"]
        self.assertAlmostEqual(pd["mean"], 322.7, places=6)
        self.assertAlmostEqual(pd["sd_samp"], 9.452, places=3)
        self.assertEqual((pd["min"], pd["max"]), (310, 336))

    def test_diameter_matches_footer(self):
        d = self.stats["parameters"]["diameter"]
        self.assertAlmostEqual(d["mean"], 7.744, places=6)
        self.assertAlmostEqual(d["sd_samp"], 0.012, delta=0.0005)

    def test_weight_matches_footer(self):
        w = self.stats["parameters"]["weight"]
        self.assertAlmostEqual(w["mean"], 0.6641, places=6)
        self.assertAlmostEqual(w["sd_samp"], 0.006, delta=0.0005)

    def test_population_sd_relates_to_sample_sd(self):
        pd = self.stats["parameters"]["pd"]
        self.assertLess(pd["sd_pop"], pd["sd_samp"])
        self.assertAlmostEqual(pd["sd_pop"] / pd["sd_samp"], (9 / 10) ** 0.5, places=9)


class RejectionRule(unittest.TestCase):
    def test_bounds_for_symmetric_limits(self):
        # Dashboard default: target 320, tolerance 20, rejection at 3 tolerances.
        self.assertEqual(ParamSpec("pd", 320, 300, 340, reject_multiplier=3).reject_bounds(), (260, 380))

    def test_bounds_follow_asymmetric_limits(self):
        self.assertEqual(CERT_SPECS["pd"].reject_bounds(), (280, 400))

    def test_no_rejection_without_multiplier(self):
        self.assertEqual(ParamSpec("weight", 0.666, 0.651, 0.681).reject_bounds(), (None, None))

    def test_rejected_rod_is_removed_from_all_parameters(self):
        rods = STATION_RODS + [{"pd": 500, "weight": 0.9, "diameter": 7.74}]
        stats = qs.compute_run_stats(rods, CERT_SPECS)
        self.assertEqual((stats["rods_total"], stats["rods_rejected"]), (11, 1))
        self.assertAlmostEqual(stats["parameters"]["pd"]["mean"], 322.7, places=6)
        self.assertAlmostEqual(stats["parameters"]["weight"]["mean"], 0.6641, places=6)

    def test_out_of_spec_inside_rejection_band_is_kept_and_counted(self):
        rods = [{"pd": 325}] * 9 + [{"pd": 360}]  # 360 > 350 upper, < 400 reject
        stats = qs.compute_run_stats(rods, PD_ONLY)
        pd = stats["parameters"]["pd"]
        self.assertEqual(stats["rods_rejected"], 0)
        self.assertEqual((pd["n"], pd["out_of_spec"]), (10, 1))
        self.assertAlmostEqual(pd["pass_rate"], 0.9)
        self.assertEqual(pd["status"], qs.STATUS_WARN)

    def test_mean_outside_limits_fails(self):
        pd = qs.compute_run_stats([{"pd": 355}] * 5, PD_ONLY)["parameters"]["pd"]
        self.assertEqual(pd["status"], qs.STATUS_FAIL)


class WindowAndEdgeCases(unittest.TestCase):
    def test_last_n_window_counts_rejected_rods_like_the_old_dashboard(self):
        rods = [{"pd": 325}] * 5 + [{"pd": 500}] + [{"pd": 330}] * 2
        stats = qs.compute_run_stats(rods, PD_ONLY, last_n=4)
        # Window = [325, 500, 330, 330] -> 500 rejected -> 3 rods used.
        self.assertEqual((stats["rods_total"], stats["rods_rejected"]), (4, 1))
        self.assertEqual(stats["parameters"]["pd"]["n"], 3)

    def test_empty_input_is_no_data(self):
        stats = qs.compute_run_stats([], CERT_SPECS)
        self.assertEqual(stats["status"], qs.STATUS_NO_DATA)
        self.assertEqual(stats["parameters"]["pd"]["status"], qs.STATUS_NOT_MEASURED)

    def test_single_rod_has_no_sample_sd(self):
        pd = qs.compute_run_stats([{"pd": 325}], PD_ONLY)["parameters"]["pd"]
        self.assertIsNone(pd["sd_samp"])
        self.assertEqual(pd["sd_pop"], 0.0)

    def test_garbage_values_are_ignored_per_parameter(self):
        rods = [{"pd": "325", "weight": None}, {"pd": " 3 25", "weight": "n/a"}, {"pd": float("nan")}]
        stats = qs.compute_run_stats(rods, CERT_SPECS)
        self.assertEqual(stats["parameters"]["pd"]["n"], 2)
        self.assertEqual(stats["parameters"]["weight"]["status"], qs.STATUS_NOT_MEASURED)

    def test_station_sample_is_warn_because_three_rods_exceed_diameter_limit(self):
        # Rods 5, 6 and 10 measure 7.76 mm, above the certificate's 7.75 upper limit,
        # while the diameter mean (7.744) is inside the limits -> WARN, not FAIL.
        stats = qs.compute_run_stats(STATION_RODS, CERT_SPECS)
        dia = stats["parameters"]["diameter"]
        self.assertEqual(dia["out_of_spec"], 3)
        self.assertEqual(dia["status"], qs.STATUS_WARN)
        self.assertEqual(stats["parameters"]["pd"]["status"], qs.STATUS_PASS)
        self.assertEqual(stats["status"], qs.STATUS_WARN)

    def test_unmeasured_hardness_does_not_break_run_status(self):
        clean = [{"pd": 325, "weight": 0.666, "diameter": 7.72}] * 10
        stats = qs.compute_run_stats(clean, CERT_SPECS)
        self.assertEqual(stats["parameters"]["hardness"]["status"], qs.STATUS_NOT_MEASURED)
        self.assertEqual(stats["status"], qs.STATUS_PASS)


class CertificateTable(unittest.TestCase):
    def rows(self, **kw):
        stats = qs.compute_run_stats(STATION_RODS, CERT_SPECS)
        return {r["parameter"]: r for r in qs.certificate_rows(stats, CERT_SPECS, **kw)}

    def test_weight_is_converted_to_grams_per_100(self):
        w = self.rows()["weight"]
        self.assertEqual((w["nominal"], w["lower"], w["upper"]), (66.6, 65.1, 68.1))
        self.assertEqual((w["mean"], w["unit"]), (66.4, "g/100"))

    def test_limits_match_certificate(self):
        rows = self.rows()
        self.assertEqual((rows["pd"]["nominal"], rows["pd"]["lower"], rows["pd"]["upper"]), (325, 310, 350))
        self.assertEqual((rows["diameter"]["lower"], rows["diameter"]["upper"]), (7.69, 7.75))
        self.assertIsNone(rows["hardness"]["upper"])  # hardness has a lower limit only

    def test_sd_kind_switch(self):
        self.assertEqual(self.rows(sd_kind="samp")["pd"]["sd"], 9.5)
        self.assertEqual(self.rows(sd_kind="pop")["pd"]["sd"], 9.0)
        with self.assertRaises(ValueError):
            self.rows(sd_kind="bogus")

    def test_manual_value_is_used_only_when_nothing_was_measured(self):
        rows = self.rows(manual={"hardness": {"mean": 84.4, "sd": None}, "pd": {"mean": 999, "sd": 1}})
        self.assertEqual((rows["hardness"]["mean"], rows["hardness"]["source"]), (84.4, "manual"))
        self.assertEqual(rows["pd"]["source"], "auto")  # measurement wins over manual
        self.assertNotEqual(rows["pd"]["mean"], 999)

    def test_not_measured_row_without_manual_value(self):
        h = self.rows()["hardness"]
        self.assertEqual(h["source"], "not_measured")
        self.assertIsNone(h["mean"])


class ManualMergeTests(unittest.TestCase):
    SPECS = {
        "diameter": CERT_SPECS["diameter"],
        "pd": CERT_SPECS["pd"],
        "weight": CERT_SPECS["weight"],
        "hardness": CERT_SPECS["hardness"],
        "length": ParamSpec("length", 108.0, 107.5, 108.5, report_unit="mm", decimals=2),
    }

    def test_manual_rods_converts_weight_per_rod(self):
        rods = qs.manual_rods([
            {"sample_weight": 6.6, "sample_rods": 10, "length_mm": 108.2, "hardness": 84.0},
            {"sample_weight": 6.8, "sample_rods": 10, "length_mm": 107.9, "hardness": 83.5},
        ])
        self.assertAlmostEqual(rods[0]["weight"], 0.66, places=6)
        self.assertAlmostEqual(rods[1]["weight"], 0.68, places=6)
        self.assertEqual([r["length"] for r in rods], [108.2, 107.9])
        self.assertEqual([r["hardness"] for r in rods], [84.0, 83.5])

    def test_merge_fills_unmeasured_length_and_hardness(self):
        stats = qs.compute_run_stats(STATION_RODS, self.SPECS)
        pseudo = qs.manual_rods([
            {"sample_rods": 10, "length_mm": 108.2, "hardness": 84.0},
            {"sample_rods": 10, "length_mm": 107.8, "hardness": 83.0},
        ])
        qs.merge_manual_parameters(stats["parameters"], pseudo, self.SPECS)
        self.assertEqual(stats["parameters"]["length"]["source"], "manual")
        self.assertAlmostEqual(stats["parameters"]["length"]["mean"], 108.0, places=6)
        self.assertAlmostEqual(stats["parameters"]["hardness"]["mean"], 83.5, places=6)
        self.assertEqual(stats["parameters"]["hardness"]["n"], 2)

    def test_discrepancy_manual_weight_out_of_spec_trusts_auto(self):
        # Manual weight 0.067 g/rod is far below the 0.651..0.681 spec, while the
        # station mean 0.6641 is in-spec: smart consolidation trusts auto and flags.
        stats = qs.compute_run_stats(STATION_RODS, self.SPECS)
        self.assertAlmostEqual(stats["parameters"]["weight"]["mean"], 0.6641, places=6)
        pseudo = qs.manual_rods([{"sample_weight": 0.670, "sample_rods": 10}])
        qs.merge_manual_parameters(stats["parameters"], pseudo, self.SPECS)
        p = stats["parameters"]["weight"]
        self.assertEqual(p["source"], "auto")
        self.assertTrue(p["flagged"])
        self.assertAlmostEqual(p["mean"], 0.6641, places=6)
        self.assertEqual(p["status"], "WARN")

    def test_both_in_spec_uses_auto(self):
        # Condition A: station + manual both in-spec -> auto, not flagged.
        stats = qs.compute_run_stats(STATION_RODS, self.SPECS)
        pseudo = qs.manual_rods([
            {"sample_weight": 6.6, "sample_rods": 10, "length_mm": 108.2, "hardness": 84.0},
        ])
        qs.merge_manual_parameters(stats["parameters"], pseudo, self.SPECS)
        w = stats["parameters"]["weight"]
        self.assertEqual(w["source"], "auto")
        self.assertFalse(w["flagged"])
        self.assertAlmostEqual(w["mean"], 0.6641, places=6)

    def test_auto_missing_uses_manual(self):
        # Condition B: no station rods -> manual fills length.
        stats = qs.compute_run_stats([], self.SPECS)
        pseudo = qs.manual_rods([
            {"length_mm": 108.2, "hardness": 84.0},
            {"length_mm": 107.8, "hardness": 83.0},
        ])
        qs.merge_manual_parameters(stats["parameters"], pseudo, self.SPECS)
        self.assertEqual(stats["parameters"]["length"]["source"], "manual")
        self.assertAlmostEqual(stats["parameters"]["length"]["mean"], 108.0, places=6)

    def test_manual_missing_uses_auto(self):
        # Condition C: no manual checks -> auto used, unflagged.
        stats = qs.compute_run_stats(STATION_RODS, self.SPECS)
        qs.merge_manual_parameters(stats["parameters"], [], self.SPECS)
        self.assertEqual(stats["parameters"]["pd"]["source"], "auto")
        self.assertFalse(stats["parameters"]["pd"]["flagged"])

    def test_discrepancy_auto_out_of_spec_trusts_manual(self):
        # Condition D (machine drift): auto out-of-spec, manual in-spec -> manual.
        specs = dict(self.SPECS)
        specs["length"] = ParamSpec("length", 108.0, 107.5, 108.5, report_unit="mm", decimals=2)
        stats = qs.compute_run_stats([{"length": 107.0}], specs)
        pseudo = qs.manual_rods([{"length_mm": 108.2, "hardness": 84.0}])
        qs.merge_manual_parameters(stats["parameters"], pseudo, specs)
        p = stats["parameters"]["length"]
        self.assertEqual(p["source"], "manual")
        self.assertTrue(p["flagged"])
        self.assertEqual(p["status"], "WARN")

    def test_grand_mean_is_not_average_of_averages(self):
        # Two "runs": 3 hardness checks (50, 60, 70) + 1 check (100). The grand mean
        # must be (50+60+70+100)/4 = 70, NOT the average of per-run means (60, 100 -> 80).
        specs = dict(self.SPECS)
        specs["hardness"] = ParamSpec("hardness", 82.0, None, None, report_unit="%", decimals=1)
        stats = qs.compute_run_stats([], specs)
        pseudo = qs.manual_rods([
            {"hardness": 50.0}, {"hardness": 60.0}, {"hardness": 70.0},
            {"hardness": 100.0},
        ])
        qs.merge_manual_parameters(stats["parameters"], pseudo, specs)
        p = stats["parameters"]["hardness"]
        self.assertAlmostEqual(p["mean"], 70.0, places=6)
        self.assertEqual(p["n"], 4)


class TriacetinTests(unittest.TestCase):
    def _samples(self):
        return [
            {"time": 1000.0, "is_triacetin": False, "rod_count": 10, "weight": 0.72},
            {"time": 1060.0, "is_triacetin": True, "rod_count": 10, "weight": 0.66},
        ]

    def test_marker_detection(self):
        self.assertTrue(qs.is_triacetin_marker("D046-Triacetin"))
        self.assertTrue(qs.is_triacetin_marker(None, "dry Triacetin batch"))
        self.assertTrue(qs.is_triacetin_marker(None, None, "TRIACETIN"))
        self.assertFalse(qs.is_triacetin_marker("D046", "batch 1", "note"))
        self.assertFalse(qs.is_triacetin_marker(None, None, None))

    def test_pairs_same_rod_count_within_window(self):
        out = qs.triacetin_measurements(self._samples())
        self.assertEqual(len(out["measurements"]), 1)
        m = out["measurements"][0]
        self.assertAlmostEqual(m["triacetin_pct"], 9.09, places=2)
        self.assertAlmostEqual(m["regular_weight"], 0.72)
        self.assertAlmostEqual(m["dry_weight"], 0.66)
        self.assertEqual(m["n"], 10)
        self.assertAlmostEqual(out["overall_pct"], 9.09, places=2)

    def test_different_rod_count_is_not_paired(self):
        samples = self._samples()
        samples[0]["rod_count"] = 9
        self.assertEqual(qs.triacetin_measurements(samples)["measurements"], [])

    def test_gap_longer_than_five_minutes_is_not_paired(self):
        samples = [
            {"time": 0.0, "is_triacetin": False, "rod_count": 10, "weight": 0.72},
            {"time": 301.0, "is_triacetin": True, "rod_count": 10, "weight": 0.66},
        ]
        self.assertEqual(qs.triacetin_measurements(samples)["measurements"], [])

    def test_picks_nearest_regular_before_or_after(self):
        samples = [
            {"time": 90.0, "is_triacetin": False, "rod_count": 10, "weight": 0.72},
            {"time": 100.0, "is_triacetin": True, "rod_count": 10, "weight": 0.66},
            {"time": 115.0, "is_triacetin": False, "rod_count": 10, "weight": 0.80},
        ]
        m = qs.triacetin_measurements(samples)["measurements"][0]
        self.assertAlmostEqual(m["regular_weight"], 0.72)

    def test_tie_prefers_earlier_regular(self):
        samples = [
            {"time": 95.0, "is_triacetin": False, "rod_count": 10, "weight": 0.72},
            {"time": 100.0, "is_triacetin": True, "rod_count": 10, "weight": 0.66},
            {"time": 105.0, "is_triacetin": False, "rod_count": 10, "weight": 0.80},
        ]
        m = qs.triacetin_measurements(samples)["measurements"][0]
        self.assertAlmostEqual(m["regular_weight"], 0.72)

    def test_overall_is_mean_of_measurements(self):
        samples = [
            {"time": 0.0, "is_triacetin": False, "rod_count": 10, "weight": 0.72},
            {"time": 10.0, "is_triacetin": True, "rod_count": 10, "weight": 0.66},
            {"time": 20.0, "is_triacetin": False, "rod_count": 10, "weight": 0.78},
            {"time": 30.0, "is_triacetin": True, "rod_count": 10, "weight": 0.70},
        ]
        out = qs.triacetin_measurements(samples)
        self.assertAlmostEqual(out["measurements"][0]["triacetin_pct"], 9.09, places=2)
        self.assertAlmostEqual(out["measurements"][1]["triacetin_pct"], 11.43, places=2)
        self.assertAlmostEqual(out["overall_pct"], 10.26, places=2)

    def test_status(self):
        spec = ParamSpec("triacetin", 8.0, 7.5, 8.5, report_unit="%", decimals=2)
        self.assertEqual(qs.triacetin_status(8.0, spec), qs.STATUS_PASS)
        self.assertEqual(qs.triacetin_status(7.0, spec), qs.STATUS_FAIL)
        self.assertEqual(qs.triacetin_status(9.0, spec), qs.STATUS_FAIL)
        self.assertEqual(qs.triacetin_status(None, spec), qs.STATUS_NOT_MEASURED)


if __name__ == "__main__":
    unittest.main()
