"""Regression: partial PO updates (archive) must not null out sync fields.

The web console's archive action PUTs a PO payload that omits the Odoo
sync fields (``sync_mode``, ``odoo_state``, ``odoo_mo_id``, ...). ``update_po``
must apply only the fields the client actually sent (``exclude_unset=True``);
otherwise it overwrites ``sync_mode``/``odoo_state`` with ``None`` and violates
the NOT NULL constraint on ``purchase_orders.sync_mode``.
"""

import unittest

from app import models, schemas
from app.main import update_po
from tests.db_support import DbTestCase


class PoPartialUpdateTests(DbTestCase):
    def _po(self):
        po = models.PurchaseOrder(
            po_number="PO-PARTIAL-UPDATE",
            diameter=7.72, length=108, pd=325, cu=0, weight=66.0, box_type=4700,
            acetate_type="", paper_type="", pva_glue_type="", hm_glue_type="",
            triacetin_type="", target_qty=1000, produced_qty=0,
            source="odoo", sync_mode="full", odoo_state="open", odoo_mo_id=123,
        )
        self.db.add(po)
        self.db.flush()
        return po

    def _payload(self, **over):
        # What the web console sends: spec fields + the archive flag, but no
        # sync/odoo fields (they are server-managed and never part of toJson()).
        data = dict(
            po_number="PO-PARTIAL-UPDATE",
            diameter=7.72, length=108, pd=325, cu=0, weight=66.0, box_type=4700,
            acetate_type="", paper_type="", pva_glue_type="", hm_glue_type="",
            triacetin_type="", target_qty=1000, is_archived=True,
        )
        data.update(over)
        return schemas.POCreate(**data)

    def test_archive_preserves_sync_mode(self):
        po = self._po()
        self.user.can_edit_po = True  # grant permission inside the test tx

        updated = update_po(po.id, self._payload(), db=self.db, current_user=self.user)

        self.assertTrue(updated.is_archived)
        self.assertEqual(updated.sync_mode, "full")
        self.assertEqual(updated.odoo_state, "open")
        self.assertEqual(updated.odoo_mo_id, 123)

    def test_partial_update_preserves_odoo_link(self):
        po = self._po()
        self.user.can_edit_po = True

        updated = update_po(po.id, self._payload(), db=self.db, current_user=self.user)

        self.db.refresh(updated)
        self.assertEqual(updated.sync_mode, "full")
        self.assertEqual(updated.odoo_state, "open")
        self.assertEqual(updated.odoo_mo_id, 123)


if __name__ == "__main__":
    unittest.main()
