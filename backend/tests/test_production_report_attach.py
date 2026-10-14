"""Production Report PDF attachment: report->dict mapping, bytes render, MO resolution."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.pdf_generator import PDFReportGenerator, report_to_dict
from app.services.odoo import legacy_push
from app.services.odoo.client import OdooClient


def _report(**over):
    base = dict(
        id=185, report_date="2026-08-04", shift_name="Shift 1", machine_name="M1",
        operator_name="Szilard", po_number="G080", lot_number="040826M1",
        shift_time_range="06:00 - 14:00", box_type=10, diameter=7.72, length=108,
        pd=325, cu=0, weight=0.663, boxes_produced=1, produced_rods=921200,
        machine_counter=0, difference=0, diff_percent="0%", waste_kg=0,
        machine_efficiency=0, total_acetate=0, total_paper=0, total_pva=0,
        total_hm=0, total_triacetin=0, remarks="",
        materials_json=json.dumps({"acetate_list": [{"type": "A", "batch": "B1"}]}),
    )
    base.update(over)
    return SimpleNamespace(**base)


class ReportToDictTests(unittest.TestCase):

    def test_maps_scalar_fields_and_material_lists(self):
        d = report_to_dict(_report())
        self.assertEqual(d["id"], 185)
        self.assertEqual(d["po_number"], "G080")
        self.assertEqual(d["machine_name"], "M1")
        self.assertEqual(d["acetate_list"], [{"type": "A", "batch": "B1"}])
        self.assertEqual(d["paper_list"], [])

    def test_bad_materials_json_is_ignored(self):
        d = report_to_dict(_report(materials_json="{not json"))
        self.assertEqual(d["acetate_list"], [])


class GeneratePdfBytesTests(unittest.TestCase):
    def test_renders_pdf_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = PDFReportGenerator(archive_path=tmp)
            data = report_to_dict(_report())
            data["id"] = 185
            pdf = gen.generate_pdf_bytes(data)
            self.assertIsNotNone(pdf)
            self.assertTrue(pdf.startswith(b"%PDF"), pdf[:8])


class ResolveReportMoTests(unittest.TestCase):
    class Fake(OdooClient):
        def __init__(self, mos, group=390):
            self.mos = mos
            self.group = group

        def read(self, model, ids, fields):
            return [{"procurement_group_id": [self.group, "WH/MO/ROOT"]}]

        def search_read(self, model, domain, fields, limit=None, order=None):
            return self.mos

        def fetch_uom_ratios(self, ids):
            return {}

    def _mos(self, *rows):
        return [{"id": i, "name": n, "state": s, "product_qty": q,
                 "product_uom_id": [1, "pcs"]} for i, n, s, q in rows]

    def test_unique_done_mo_by_quantity(self):
        c = self.Fake(self._mos((508, "WH/MO/00189-002", "done", 860100)))
        po = SimpleNamespace(odoo_mo_id=499)
        self.assertEqual(legacy_push.resolve_report_mo(c, po, 860100), (508, "WH/MO/00189-002"))

    def test_skips_non_done_mo(self):
        c = self.Fake(self._mos((508, "WH/MO/00189-002", "confirmed", 860100)))
        po = SimpleNamespace(odoo_mo_id=499)
        self.assertIsNone(legacy_push.resolve_report_mo(c, po, 860100))

    def test_ambiguous_quantity_returns_none(self):
        c = self.Fake(self._mos(
            (7, "WH/MO/-007", "done", 2119700), (8, "WH/MO/-008", "done", 2119700)))
        po = SimpleNamespace(odoo_mo_id=499)
        self.assertIsNone(legacy_push.resolve_report_mo(c, po, 2119700))

    def test_unlinked_order_returns_none(self):
        c = self.Fake(self._mos())
        self.assertIsNone(legacy_push.resolve_report_mo(c, SimpleNamespace(odoo_mo_id=None), 10))


if __name__ == "__main__":
    unittest.main()
