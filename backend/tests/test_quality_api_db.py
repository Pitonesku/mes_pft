"""Quality-management v2 endpoints: permissions, NCR lifecycle, quarantine
resolutions and the Odoo release outbox enqueue (rolled-back afterwards)."""

import unittest

from fastapi import HTTPException

from app import models, v2_routes as v2
from app.services import quarantine as q
from app.services.odoo import outbound as odoo_outbound
from tests.db_support import DbTestCase


def _quality_mgr(user):
    role = type("R", (), {"role_name": "manager", "can_manage_quality": True})()
    return type("U", (), {"username": user.username, "role": role,
                          "can_manage_quality": False, "id": user.id})()


def _plain(user):
    role = type("R", (), {"role_name": "operator", "can_manage_quality": False})()
    return type("U", (), {"username": user.username, "role": role,
                          "can_manage_quality": False, "id": 0})()


class NcrApiTests(DbTestCase):
    def test_plain_user_cannot_create_ncr(self):
        with self.assertRaises(HTTPException) as ctx:
            v2.create_ncr(v2.NcrCreate(po_id=self.po_a.id, description="x"),
                          db=self.db, current_user=_plain(self.user))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_quality_manager_creates_and_lists_ncr(self):
        mgr = _quality_mgr(self.user)
        out = v2.create_ncr(v2.NcrCreate(po_id=self.po_a.id, description="PD drift",
                                         severity="MAJOR"),
                            db=self.db, current_user=mgr)
        self.assertEqual(out["ncr_number"], f"NCR-{q.safe_mo(self.po_a.mo_number)}-0001")
        self.assertEqual(out["status"], "OPEN")
        self.assertEqual(len(out["history"]), 1)
        rows = v2.list_ncrs(po_id=self.po_a.id, db=self.db, current_user=mgr)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], out["id"])

    def test_close_flow_and_reopen(self):
        mgr = _quality_mgr(self.user)
        out = v2.create_ncr(v2.NcrCreate(po_id=self.po_a.id, description="issue"),
                            db=self.db, current_user=mgr)
        with self.assertRaises(HTTPException) as ctx:
            v2.close_ncr(out["id"], v2.NcrClose(closing_remarks=" "),
                         db=self.db, current_user=mgr)
        self.assertEqual(ctx.exception.status_code, 422)
        closed = v2.close_ncr(out["id"], v2.NcrClose(closing_remarks="fixed"),
                              db=self.db, current_user=mgr)
        self.assertEqual(closed["status"], "CLOSED")
        self.assertEqual(closed["closing_remarks"], "fixed")
        reopened = v2.reopen_ncr(out["id"], v2.StatusNote(), db=self.db, current_user=mgr)
        self.assertEqual(reopened["status"], "IN_PROGRESS")
        history = v2.ncr_status_history(out["id"], db=self.db, current_user=mgr)
        self.assertEqual([h["to_status"] for h in history],
                         ["OPEN", "CLOSED", "IN_PROGRESS"])

    def test_update_ncr_fields(self):
        mgr = _quality_mgr(self.user)
        out = v2.create_ncr(v2.NcrCreate(po_id=self.po_a.id, description="old"),
                            db=self.db, current_user=mgr)
        patched = v2.update_ncr(out["id"],
                                v2.NcrUpdate(description="new", corrective_action="rework"),
                                db=self.db, current_user=mgr)
        self.assertEqual((patched["description"], patched["corrective_action"]),
                         ("new", "rework"))


class QuarantineResolveApiTests(DbTestCase):
    def setUp(self):
        super().setUp()
        shift = self.make_shift()
        self.make_report(shift, self.po_a, quarantine_boxes=8)
        self.db.flush()
        self.mgr = _quality_mgr(self.user)

    def test_permission_required(self):
        with self.assertRaises(HTTPException) as ctx:
            v2.create_quarantine_resolution(
                v2.QuarantineResolutionCreate(po_id=self.po_a.id, kind="scrap", boxes=1),
                db=self.db, current_user=_plain(self.user))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_scrap_via_endpoint(self):
        out = v2.create_quarantine_resolution(
            v2.QuarantineResolutionCreate(po_id=self.po_a.id, kind="scrap", boxes=3,
                                          dry_weight_kg=0.9),
            db=self.db, current_user=self.mgr)
        self.assertEqual(out["doc_number"], f"SCR-{q.safe_mo(self.po_a.mo_number)}-0001")
        self.assertEqual(out["balance"]["remaining_boxes"], 5)
        rows = v2.list_quarantine_resolutions(po_id=self.po_a.id, db=self.db,
                                              current_user=self.mgr)
        self.assertEqual(len(rows), 1)

    def test_overdraft_returns_422(self):
        with self.assertRaises(HTTPException) as ctx:
            v2.create_quarantine_resolution(
                v2.QuarantineResolutionCreate(po_id=self.po_a.id, kind="release", boxes=9),
                db=self.db, current_user=self.mgr)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_release_enqueues_odoo_outbox_when_linked(self):
        self.po_a.odoo_mo_id = 4242
        self.po_a.odoo_mo_name = "WH/MO/004242"
        self.db.flush()
        orig_enabled = odoo_outbound.enabled
        odoo_outbound.enabled = lambda config=None: True
        try:
            out = v2.create_quarantine_resolution(
                v2.QuarantineResolutionCreate(po_id=self.po_a.id, kind="release", boxes=2),
                db=self.db, current_user=self.mgr)
        finally:
            odoo_outbound.enabled = orig_enabled
        self.assertEqual(out["odoo_sync_status"], q.SYNC_PENDING)
        item = (self.db.query(models.OdooOutbox)
                .filter(models.OdooOutbox.aggregate_type == "quarantine_release").one())
        self.assertEqual(item.aggregate_id, out["id"])
        self.assertEqual(item.payload["mo_id"], 4242)
        self.assertIn("Recovered from Quarantine, orig. MO: WH/MO/004242",
                      item.payload["reference"])

    def test_release_stays_local_without_odoo_link(self):
        self.po_a.odoo_mo_id = None
        self.po_a.odoo_mo_name = None
        self.db.flush()
        out = v2.create_quarantine_resolution(
            v2.QuarantineResolutionCreate(po_id=self.po_a.id, kind="release", boxes=1),
            db=self.db, current_user=self.mgr)
        self.assertEqual(out["odoo_sync_status"], q.SYNC_LOCAL)
        self.assertEqual(self.db.query(models.OdooOutbox)
                         .filter(models.OdooOutbox.aggregate_type == "quarantine_release")
                         .count(), 0)

    def test_void_is_admin_only(self):
        res = v2.create_quarantine_resolution(
            v2.QuarantineResolutionCreate(po_id=self.po_a.id, kind="scrap", boxes=1),
            db=self.db, current_user=self.mgr)
        with self.assertRaises(HTTPException) as ctx:
            v2.void_quarantine_resolution(res["id"], v2.ResolutionVoid(reason="oops"),
                                          db=self.db, current_user=self.mgr)
        self.assertEqual(ctx.exception.status_code, 403)
        admin_role = type("R", (), {"role_name": "admin", "can_manage_quality": False})()
        admin = type("U", (), {"username": "root", "role": admin_role,
                               "can_manage_quality": False, "id": self.user.id})()
        out = v2.void_quarantine_resolution(res["id"], v2.ResolutionVoid(reason="oops"),
                                            db=self.db, current_user=admin)
        self.assertTrue(out["voided"])

    def test_order_quarantine_endpoint(self):
        v2.create_quarantine_resolution(
            v2.QuarantineResolutionCreate(po_id=self.po_a.id, kind="scrap", boxes=2,
                                          dry_weight_kg=0.5),
            db=self.db, current_user=self.mgr)
        summary = v2.order_quarantine(self.po_a.id, db=self.db, current_user=self.mgr)
        self.assertEqual((summary["total_quarantine_boxes"],
                          summary["remaining_boxes"], summary["scrap_kg"]), (8, 6, 0.5))


class OrderQualityFlagsApiTests(DbTestCase):
    def test_flags_aggregate_ncr_and_quarantine(self):
        shift = self.make_shift()
        self.make_report(shift, self.po_a, quarantine_boxes=5)
        self.db.flush()
        mgr = _quality_mgr(self.user)
        v2.create_ncr(v2.NcrCreate(po_id=self.po_a.id, description="a"),
                      db=self.db, current_user=mgr)
        v2.create_ncr(v2.NcrCreate(po_id=self.po_a.id, description="b",
                                   severity="CRITICAL"),
                      db=self.db, current_user=mgr)
        v2.create_quarantine_resolution(
            v2.QuarantineResolutionCreate(po_id=self.po_a.id, kind="scrap", boxes=1,
                                          dry_weight_kg=0.2),
            db=self.db, current_user=mgr)
        flags = v2.order_quality_flags(po_ids=str(self.po_a.id), db=self.db,
                                       current_user=mgr)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f["open_ncr_count"], f["critical_open_ncr"], f["total_ncr_count"]),
                         (2, True, 2))
        self.assertEqual((f["total_quarantine_boxes"], f["remaining_quarantine_boxes"],
                          f["scrap_kg"]), (5, 4, 0.2))

    def test_no_ncr_and_no_quarantine_gives_zero_flags(self):
        flags = v2.order_quality_flags(po_ids=str(self.po_a.id), db=self.db,
                                       current_user=self.user)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["open_ncr_count"], 0)
        self.assertEqual(flags[0]["remaining_quarantine_boxes"], 0)


if __name__ == "__main__":
    unittest.main()
