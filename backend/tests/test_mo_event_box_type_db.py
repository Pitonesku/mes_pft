"""Tests for Odoo MO event ingestion: box_type / Base Packaging capture.

Run from backend/:
    python -m unittest tests.test_mo_event_box_type_db -v
"""

import unittest

from app import models
from app.services.odoo import inbound
from tests.db_support import DbTestCase


class MoEventBoxTypeTests(DbTestCase):
    def _event(self, mo_id, name, **extra):
        event = {"mo_id": mo_id, "name": name, "state": "confirmed", "bom": []}
        event.update(extra)
        return event

    def _po(self, out):
        return self.db.query(models.PurchaseOrder).filter_by(id=out["po_id"]).one()

    def test_top_level_box_type_is_authoritative(self):
        out = inbound.handle_mo_event(self.db, self._event(
            900001, "TEST-BOX-1",
            product_name="5.35*120 PD375 Filter rod 6000CU",
            box_type=7750,
            base_packaging_name="Case",
            spec={"diameter": 5.35, "length": 120, "pd": 375,
                  "cu": 6000, "box_type": 4700},
        ))
        self.assertEqual(self._po(out).box_type, 7750)

    def test_spec_box_type_is_fallback_when_top_level_absent(self):
        out = inbound.handle_mo_event(self.db, self._event(
            900002, "TEST-BOX-2", spec={"box_type": 4700},
        ))
        self.assertEqual(self._po(out).box_type, 4700)

    def test_no_box_type_leaves_default(self):
        out = inbound.handle_mo_event(self.db, self._event(
            900003, "TEST-BOX-3",
        ))
        self.assertEqual(self._po(out).box_type, 0)


if __name__ == "__main__":
    unittest.main()
