"""Tests for the Odoo client's pure helpers + QC/UoM mapping logic.

Run from backend/:
    python -m unittest tests.test_odoo_client -v
"""

import unittest

from app.services.odoo import client as odoo_client


class FloatRoundTests(unittest.TestCase):
    def test_half_up(self):
        self.assertEqual(odoo_client.float_round(1.8753, 0.001), 1.875)
        self.assertEqual(odoo_client.float_round(1.8755, 0.001), 1.876)  # HALF-UP
        self.assertEqual(odoo_client.float_round(1875.3, 0.001), 1875.3)

    def test_no_precision(self):
        self.assertEqual(odoo_client.float_round(1.2345, 0.0), 1.2345)


class FallbackRatioTests(unittest.TestCase):
    def test_million(self):
        self.assertEqual(odoo_client._fallback_ratio("M pcs"), 1_000_000.0)
        self.assertEqual(odoo_client._fallback_ratio("Million"), 1_000_000.0)

    def test_thousand(self):
        self.assertEqual(odoo_client._fallback_ratio("k pcs"), 1_000.0)

    def test_unit(self):
        self.assertEqual(odoo_client._fallback_ratio("Pcs"), 1.0)
        self.assertEqual(odoo_client._fallback_ratio(""), 1.0)


class FakeClient(odoo_client.OdooClient):
    def __init__(self, ratio=1.0, rounding=0.001):
        self._ratio = ratio
        self._rounding = rounding
        self.written = []

    def connect(self):
        pass

    def read(self, model, ids, fields):
        if model == "uom.uom" and "factor" in fields:
            return [{"name": "M pcs", "factor": self._ratio}]
        if model == "uom.uom" and "rounding" in fields:
            return [{"rounding": self._rounding}]
        return [{"product_uom_id": [1]}]

    def write(self, model, ids, values):
        self.written.append((model, ids, values))
        return True

    def call(self, model, method, ids):
        return True


class ConvertRodsTests(unittest.TestCase):
    def test_million(self):
        c = FakeClient(ratio=1_000_000.0)
        self.assertEqual(c.convert_rods(1_875_300, uom_id=1), 1.875)

    def test_thousand(self):
        c = FakeClient(ratio=1_000.0)
        self.assertEqual(c.convert_rods(1_875_300, uom_id=1), 1875.3)

    def test_unit(self):
        c = FakeClient(ratio=1.0)
        self.assertEqual(c.convert_rods(1_875_300, uom_id=1), 1875300.0)


class WriteMoQualityTests(unittest.TestCase):
    def test_writes_status_and_fields(self):
        c = FakeClient()
        run = {
            "status": "PASS",
            "rods_total": 100,
            "rods_rejected": 3,
            "parameters": {
                "pd": {"n": 100, "mean": 325.0, "sd_samp": 8.1},
                "diameter": {"n": 100, "mean": 7.72, "sd_samp": 0.012},
            },
        }
        c.write_mo_quality(5, run)
        values = c.written[0][2]
        self.assertEqual(values[odoo_client.QC_FIELD_QUALITY_STATUS], "pass")
        self.assertEqual(values[odoo_client.QC_FIELD_MEAN_PD], 325.0)
        self.assertEqual(values[odoo_client.QC_FIELD_SD_PD], 8.1)
        self.assertEqual(values[odoo_client.QC_FIELD_MEAN_DIAMETER], 7.72)
        self.assertEqual(values[odoo_client.QC_FIELD_SD_DIAMETER], 0.012)
        self.assertEqual(values[odoo_client.QC_FIELD_TESTED_RODS], 100)
        self.assertEqual(values[odoo_client.QC_FIELD_REJECTED_RODS], 3)

    def test_skips_without_measured(self):
        c = FakeClient()
        result = c.write_mo_quality(5, {"status": "PASS", "parameters": {}})
        self.assertTrue(result.get("skipped"))
        self.assertEqual(c.written, [])


if __name__ == "__main__":
    unittest.main()
