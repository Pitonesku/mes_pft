"""Tests for the manual triacetin fallback helpers in quality_stats."""

import unittest

from app import quality_stats as qs


class ManualTriacetinTests(unittest.TestCase):
    def test_pct_uses_wet_minus_dry_over_dry(self):
        self.assertAlmostEqual(qs.manual_triacetin_pct(720.0, 660.0), 9.09, places=2)

    def test_pct_requires_positive_dry(self):
        self.assertIsNone(qs.manual_triacetin_pct(720.0, 0))
        self.assertIsNone(qs.manual_triacetin_pct(None, 660.0))
        self.assertIsNone(qs.manual_triacetin_pct(720.0, None))

    def test_measurements_convert_total_mg_to_per_rod_g(self):
        out = qs.manual_triacetin_measurements([{
            "triacetin_wet_mg": 720.0,
            "triacetin_dry_mg": 660.0,
            "triacetin_rods": 10,
            "measured_at": "2026-10-26T10:00:00",
        }])
        self.assertEqual(len(out), 1)
        m = out[0]
        self.assertAlmostEqual(m["triacetin_pct"], 9.09, places=2)
        self.assertAlmostEqual(m["regular_weight"], 0.072, places=5)
        self.assertAlmostEqual(m["dry_weight"], 0.066, places=5)
        self.assertEqual(m["n"], 10)
        self.assertEqual(m["source"], "manual")

    def test_measurements_skips_invalid(self):
        out = qs.manual_triacetin_measurements([{"triacetin_wet_mg": 720.0}])
        self.assertEqual(out, [])

    def test_merge_combines_station_and_manual(self):
        station = {
            "measurements": [{"triacetin_pct": 8.0, "time": "t1"}],
            "overall_pct": 8.0,
        }
        merged = qs.merge_triacetin(station, [{"triacetin_pct": 10.0, "time": "t2"}])
        self.assertEqual(len(merged["measurements"]), 2)
        self.assertAlmostEqual(merged["overall_pct"], 9.0, places=2)

    def test_merge_none_station(self):
        merged = qs.merge_triacetin(None, [{"triacetin_pct": 5.0}])
        self.assertAlmostEqual(merged["overall_pct"], 5.0, places=2)


if __name__ == "__main__":
    unittest.main()
