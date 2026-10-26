"""Tests for consumption extraction and the UoM ratio fix.

Run from backend/:
    python -m unittest tests.test_odoo_consumption -v
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from app.services.odoo import client as odoo_client
from app.services.odoo import consumption


def report_with(materials_json):
    return SimpleNamespace(materials_json=materials_json)


class ParseConsumptionTests(unittest.TestCase):
    def test_includes_zero_for_direct_materials(self):
        r = report_with(
            '{"acetate_list": [{"type": "Cerdia 3.0Y30000", "batch": "B1", "used": 172.0}],'
            ' "hm_list": [{"type": "Tobacoll Q 2237", "used": 0.0}],'
            ' "paper_list": [{"type": "Delfort 27mm/6000m", "used": 6.0}]}'
        )
        items = consumption.parse_report_consumption(r)
        by_cat = {i["category"]: i for i in items}
        self.assertEqual(by_cat["acetate"]["used"], 172.0)
        self.assertEqual(by_cat["acetate"]["unit"], "kg")
        self.assertEqual(by_cat["paper"]["used"], 6.0)
        self.assertEqual(by_cat["paper"]["unit"], "bob")
        # Zero usage is preserved so it can be written to Odoo as an explicit 0
        # (which prevents Odoo from auto-consuming the component from the BOM).
        self.assertIn("hotMelt", by_cat)
        self.assertEqual(by_cat["hotMelt"]["used"], 0.0)

    def test_used_falls_back_to_start_minus_stop(self):
        r = report_with('{"tri_list": [{"type": "Gli Therm", "start": "300", "stop": "286"}]}')
        items = consumption.parse_report_consumption(r)
        self.assertEqual(items[0]["used"], 14.0)
        self.assertEqual(items[0]["category"], "triacetin")

    def test_invalid_json_is_empty(self):
        self.assertEqual(consumption.parse_report_consumption(report_with("not json")), [])

    def test_aggregate_merges_equal_type_batch(self):
        a = report_with('{"acetate_list": [{"type": "Cerdia", "batch": "B1", "used": 10.0}]}')
        b = report_with('{"acetate_list": [{"type": "Cerdia", "batch": "B1", "used": 5.0}]}')
        items = consumption.aggregate_consumption([a, b])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["used"], 15.0)

    def test_aggregate_sums_multiple_batches(self):
        r = report_with(
            '{"acetate_list": [{"type": "Cerdia", "batch": "B1", "used": 78.0}, {"type": "Cerdia", "batch": "B2", "used": 482.0}]}'
        )
        items = consumption.aggregate_consumption([r])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["used"], 560.0)


class BobbinLengthTests(unittest.TestCase):
    def test_parses_metres(self):
        self.assertEqual(consumption.bobbin_length_metres("Delfort 21.5mm/6000m"), 6000.0)
        self.assertEqual(consumption.bobbin_length_metres("Delfort 27mm/5000m HP PWP 6000CU"), 5000.0)

    def test_missing_returns_none(self):
        self.assertIsNone(consumption.bobbin_length_metres("Plain paper"))
        self.assertIsNone(consumption.bobbin_length_metres(""))


class UomRatioTests(unittest.TestCase):
    def _client(self, fields):
        c = odoo_client.OdooClient.__new__(odoo_client.OdooClient)
        c.read = mock.Mock(return_value=[fields])
        return c

    def test_bigger_unit_returns_factor_inv(self):
        c = self._client({"factor": 0.001, "factor_inv": 1000.0})
        self.assertEqual(c.resolve_uom_ratio(1), 1000.0)
        self.assertEqual(c.convert_rods(1_875_300, 1), 1875.3)

    def test_falls_back_to_inverse_factor(self):
        c = self._client({"factor": 0.001})
        self.assertAlmostEqual(c.resolve_uom_ratio(1), 1000.0)


class PlanConsumptionTests(unittest.TestCase):
    def _client(self, moves, tracking="none", uom_cat="Weight"):
        c = odoo_client.OdooClient.__new__(odoo_client.OdooClient)
        c.search_read = mock.Mock(return_value=moves)
        c.read = mock.Mock()
        c._product_tracking = mock.Mock(return_value=tracking)
        c.uom_category_name = mock.Mock(return_value=uom_cat)
        c._uom_rounding = mock.Mock(return_value=0.001)
        c.resolve_uom_ratio = mock.Mock(return_value=1.0)
        return c

    def _move(self, pid, pname, qty=500.0, done=0.0, uom="kg"):
        return {
            "id": 11, "product_id": [pid, pname],
            "product_uom": [1, uom], "product_uom_qty": qty,
            "quantity": done, "state": "assigned",
        }

    def test_kg_item_writes_move(self):
        c = self._client([self._move(5, "Cerdia 3.0Y30000")])
        items = [{"category": "acetate", "type_name": "Cerdia 3.0Y30000", "used": 172.0, "unit": "kg"}]
        plan = c.plan_consumption(1, items)
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(plan["actions"][0]["move_id"], 11)
        self.assertEqual(plan["actions"][0]["qty"], 172.0)
        self.assertEqual(plan["skipped"], [])

    def test_matches_by_odoo_product_id_not_name(self):
        c = self._client([self._move(941, "Cerdia Acetate Tow 3,0Y30000HK (560kg)")])
        items = [{"category": "acetate", "type_name": "Cerdia 3.0Y30000", "used": 560.0, "unit": "kg", "odoo_product_id": 941}]
        plan = c.plan_consumption(1, items)
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(plan["actions"][0]["product_id"], 941)
        self.assertEqual(plan["actions"][0]["qty"], 560.0)
        self.assertEqual(plan["skipped"], [])

    def test_zero_item_writes_zero_qty(self):
        c = self._client([self._move(5, "Tobacoll Q 2237")])
        items = [{"category": "hotMelt", "type_name": "Tobacoll Q 2237", "used": 0.0, "unit": "kg"}]
        plan = c.plan_consumption(1, items)
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(plan["actions"][0]["move_id"], 11)
        self.assertEqual(plan["actions"][0]["qty"], 0.0)
        self.assertEqual(plan["skipped"], [])

    def test_tracked_product_is_skipped(self):
        c = self._client([self._move(5, "Cerdia 3.0Y30000")], tracking="lot")
        items = [{"category": "acetate", "type_name": "Cerdia 3.0Y30000", "used": 172.0, "unit": "kg"}]
        plan = c.plan_consumption(1, items)
        self.assertEqual(plan["actions"], [])
        self.assertIn("lot-tracked", plan["skipped"][0]["reason"])

    def test_unit_mismatch_is_skipped(self):
        c = self._client([self._move(5, "Cerdia 3.0Y30000")], uom_cat="Length")
        items = [{"category": "acetate", "type_name": "Cerdia 3.0Y30000", "used": 172.0, "unit": "kg"}]
        plan = c.plan_consumption(1, items)
        self.assertEqual(plan["actions"], [])
        self.assertIn("unit mismatch", plan["skipped"][0]["reason"])

    def test_overconsumption_writes_true_amount(self):
        c = self._client([self._move(5, "Cerdia 3.0Y30000", qty=100.0)])
        items = [{"category": "acetate", "type_name": "Cerdia 3.0Y30000", "used": 172.0, "unit": "kg"}]
        plan = c.plan_consumption(1, items)
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(plan["actions"][0]["qty"], 172.0)
        self.assertEqual(plan["skipped"], [])

    def test_paper_bobbin_converts_to_metres(self):
        c = self._client([self._move(6, "Delfort 27mm/6000m", qty=50000.0, uom="m")], uom_cat="Length")
        items = [{"category": "paper", "type_name": "Delfort 27mm/6000m", "used": 6.0, "unit": "bob"}]
        plan = c.plan_consumption(1, items)
        self.assertEqual(plan["actions"][0]["qty"], 36000.0)

    def _box_move(self):
        return {"id": 12, "product_id": [7, "Box"], "product_uom": [1, "Unit"],
                "product_uom_qty": 1000.0, "quantity": 0.0, "state": "assigned",
                "bom_line_id": [99, "Box line"]}

    def test_proportional_auto_consumes_unmatched_move(self):
        c = self._client([self._move(5, "Cerdia 3.0Y30000"), self._box_move()])
        items = [{"category": "acetate", "type_name": "Cerdia 3.0Y30000", "used": 172.0, "unit": "kg"}]
        plan = c.plan_consumption(1, items, proportion=0.5)
        self.assertEqual(len(plan["actions"]), 2)
        box = next(a for a in plan["actions"] if a["product_id"] == 7)
        self.assertEqual(box["qty"], 500.0)
        self.assertEqual(box["category"], "auto")

    def test_no_auto_consumption_without_proportion(self):
        c = self._client([self._move(5, "Cerdia 3.0Y30000"), self._box_move()])
        items = [{"category": "acetate", "type_name": "Cerdia 3.0Y30000", "used": 172.0, "unit": "kg"}]
        plan = c.plan_consumption(1, items)  # proportion=None -> no auto consumption
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(plan["actions"][0]["product_id"], 5)

    def test_prepopulated_quantity_does_not_block_consumption(self):
        # Odoo pre-populates raw-move `quantity` to the full demand on reserved
        # moves; the MES must ignore `quantity` and write the reported amount.
        c = self._client([self._move(5, "Cerdia 3.0Y30000", qty=500.0, done=500.0)])
        items = [{"category": "acetate", "type_name": "Cerdia 3.0Y30000", "used": 172.0, "unit": "kg"}]
        plan = c.plan_consumption(1, items)
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(plan["actions"][0]["qty"], 172.0)

    def test_picked_move_is_skipped(self):
        move = self._move(5, "Cerdia 3.0Y30000")
        move["picked"] = True
        c = self._client([move])
        items = [{"category": "acetate", "type_name": "Cerdia 3.0Y30000", "used": 172.0, "unit": "kg"}]
        plan = c.plan_consumption(1, items)
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["skipped"], [])


if __name__ == "__main__":
    unittest.main()
