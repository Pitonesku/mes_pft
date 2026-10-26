"""Tests for the shift quality report PDF (certificate-style renderer)."""

import unittest

from app.pdf_generator import render_shift_quality_pdf


def _data(**kw):
    data = {
        "header": {
            "po_number": "I096", "spec_string": "7.72*108 PD 325 CU 0",
            "machine": "M1", "date": "2026-10-11",
            "interval": "11.10.2026 13:55 – 14:54", "operator": "Gabor",
        },
        "certificate": [
            {"parameter": "diameter", "nominal": 7.72, "lower": 7.69, "upper": 7.75, "mean": 7.74, "sd": 0.012},
            {"parameter": "pd", "nominal": 325, "lower": 310, "upper": 350, "mean": 322.7, "sd": 9.4},
        ],
        "manual_checks": [],
        "remarks": None,
    }
    data.update(kw)
    return data


class ShiftQualityReportPdfTests(unittest.TestCase):
    def test_renders_valid_pdf(self):
        pdf = render_shift_quality_pdf(_data())
        self.assertTrue(pdf.startswith(b"%PDF"), pdf[:8])
        self.assertGreater(len(pdf), 1000)

    def test_empty_manual_checks_is_fine(self):
        pdf = render_shift_quality_pdf(_data(manual_checks=[]))
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_manual_checks_log(self):
        pdf = render_shift_quality_pdf(_data(manual_checks=[
            {"time": "15:57", "operator": "Gabor", "length_mm": 107.0, "weight_g": 6.6,
             "glue_seam": True, "cut_quality": False, "visual": None, "notes": "ok"},
        ]))
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_unicode_and_remarks(self):
        pdf = render_shift_quality_pdf(_data(
            header={**_data()["header"], "operator": "Kiss Árpád"},
            remarks="glue seam checked",
        ))
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_triacetin_table(self):
        pdf = render_shift_quality_pdf(_data(triacetin=[
            {"time": "15:57", "triacetin_pct": 8.2, "regular_weight": 0.72,
             "dry_weight": 0.66, "n": 10},
        ]))
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_empty_triacetin_table(self):
        pdf = render_shift_quality_pdf(_data(triacetin=[]))
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
