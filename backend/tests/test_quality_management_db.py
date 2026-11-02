"""Quality management: quarantine ledger, resolutions and NCR lifecycle.

Requires the real PostgreSQL schema (migration 0028 applied); each test runs
inside a rolled-back transaction so the dev database is never modified.
"""

import unittest

from app import models
from app.services import quarantine as q
from app.services import shift_lifecycle as lc
from tests.db_support import DbTestCase


class QuarantineBalanceTests(DbTestCase):
    def _quarantined_report(self, po, boxes):
        shift = self.make_shift()
        # Close the session so the next shift on the same machine can be created
        # (one_open_shift_per_machine partial unique index).
        shift.ended_at = lc.utcnow()
        shift.status = "CLOSED"
        return self.make_report(shift, po, quarantine_boxes=boxes)

    def test_balance_counts_quarantine_boxes(self):
        self._quarantined_report(self.po_a, 3)
        self._quarantined_report(self.po_a, 5)
        self.db.flush()
        bal = q.quarantine_balance(self.db, self.po_a)
        self.assertEqual(bal["total_quarantine_boxes"], 8)
        self.assertEqual(bal["remaining_boxes"], 8)
        self.assertEqual(bal["scrap_boxes"], 0)
        self.assertEqual(bal["released_boxes"], 0)

    def test_obsolete_and_deleted_reports_are_excluded(self):
        shift = self.make_shift()
        self.make_report(shift, self.po_a, quarantine_boxes=5)
        obsolete = self.make_report(shift, self.po_a, quarantine_boxes=99)
        obsolete.status = "obsolete"
        deleted = self.make_report(shift, self.po_a, quarantine_boxes=99)
        deleted.is_deleted = True
        self.db.flush()
        bal = q.quarantine_balance(self.db, self.po_a)
        self.assertEqual(bal["total_quarantine_boxes"], 5)


class QuarantineResolutionTests(DbTestCase):
    def setUp(self):
        super().setUp()
        shift = self.make_shift()
        self.make_report(shift, self.po_a, quarantine_boxes=10)
        self.make_report(shift, self.po_b, quarantine_boxes=5)
        self.db.flush()

    def test_scrap_reduces_balance_and_numbers_documents(self):
        res = q.create_resolution(self.db, self.po_a, q.KIND_SCRAP, 4,
                                  self.user, dry_weight_kg=1.25,
                                  reason_code="ENGINEERING_REJECT")
        self.db.flush()
        self.assertEqual(res.doc_number, f"SCR-{q.safe_mo(self.po_a.mo_number)}-0001")
        self.assertEqual(res.kind, q.KIND_SCRAP)
        self.assertEqual(float(res.dry_weight_kg), 1.25)
        bal = q.quarantine_balance(self.db, self.po_a)
        self.assertEqual(bal["remaining_boxes"], 6)
        self.assertEqual(bal["scrap_boxes"], 4)
        self.assertEqual(bal["scrap_kg"], 1.25)

    def test_release_reduces_balance_and_stays_local(self):
        res = q.create_resolution(self.db, self.po_a, q.KIND_RELEASE, 3, self.user)
        self.db.flush()
        self.assertEqual(res.doc_number, f"REL-{q.safe_mo(self.po_a.mo_number)}-0001")
        self.assertIsNone(res.dry_weight_kg)
        self.assertEqual(res.odoo_sync_status, q.SYNC_LOCAL)
        bal = q.quarantine_balance(self.db, self.po_a)
        self.assertEqual(bal["released_boxes"], 3)
        self.assertEqual(bal["remaining_boxes"], 7)

    def test_overdraft_is_rejected(self):
        with self.assertRaises(q.QualityError) as ctx:
            q.create_resolution(self.db, self.po_a, q.KIND_SCRAP, 11, self.user)
        self.assertEqual(ctx.exception.status, 422)
        self.assertIn("only 10 remain", ctx.exception.detail)

    def test_scrap_and_release_draw_the_same_pool(self):
        q.create_resolution(self.db, self.po_a, q.KIND_SCRAP, 6, self.user)
        q.create_resolution(self.db, self.po_a, q.KIND_RELEASE, 4, self.user)
        self.db.flush()
        with self.assertRaises(q.QualityError):
            q.create_resolution(self.db, self.po_a, q.KIND_SCRAP, 1, self.user)


    def test_voided_scrap_restores_balance(self):
        res = q.create_resolution(self.db, self.po_a, q.KIND_SCRAP, 4, self.user,
                                  dry_weight_kg=0.5)
        self.db.flush()
        out = q.void_resolution(self.db, res, self.user, reason="mistake")
        self.assertTrue(out["voided"])
        self.db.flush()  # persist the void before re-reading the balance
        bal = q.quarantine_balance(self.db, self.po_a)
        self.assertEqual(bal["remaining_boxes"], 10)
        self.assertEqual(bal["scrap_kg"], 0)

    def test_synced_release_cannot_be_voided(self):
        res = q.create_resolution(self.db, self.po_a, q.KIND_RELEASE, 2, self.user)
        res.odoo_sync_status = q.SYNC_SYNCED
        self.db.flush()
        with self.assertRaises(q.QualityError) as ctx:
            q.void_resolution(self.db, res, self.user)
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("already synced to Odoo", ctx.exception.detail)

    def test_pending_release_can_be_voided(self):
        res = q.create_resolution(self.db, self.po_a, q.KIND_RELEASE, 2, self.user)
        res.odoo_sync_status = q.SYNC_PENDING
        self.db.flush()
        q.void_resolution(self.db, res, self.user)
        self.db.flush()
        self.assertIsNotNone(res.voided_at)

    def test_cancelled_order_is_rejected(self):
        self.po_a.completion_status = "cancelled"
        self.db.flush()
        with self.assertRaises(q.QualityError) as ctx:
            q.create_resolution(self.db, self.po_a, q.KIND_RELEASE, 1, self.user)
        self.assertEqual(ctx.exception.status, 409)

    def test_invalid_kind_and_boxes(self):
        with self.assertRaises(q.QualityError):
            q.create_resolution(self.db, self.po_a, "burn", 1, self.user)
        with self.assertRaises(q.QualityError):
            q.create_resolution(self.db, self.po_a, q.KIND_SCRAP, 0, self.user)
        with self.assertRaises(q.QualityError):
            q.create_resolution(self.db, self.po_a, q.KIND_SCRAP, -2, self.user)
        with self.assertRaises(q.QualityError):
            q.create_resolution(self.db, self.po_a, q.KIND_SCRAP, 1, self.user,
                                dry_weight_kg=-1)

    def test_numbering_continues_across_kinds_and_orders(self):
        q.create_resolution(self.db, self.po_a, q.KIND_SCRAP, 1, self.user)
        q.create_resolution(self.db, self.po_a, q.KIND_RELEASE, 1, self.user)
        q.create_resolution(self.db, self.po_b, q.KIND_SCRAP, 1, self.user)
        self.db.flush()
        rows = (self.db.query(models.QuarantineResolution)
                .filter(models.QuarantineResolution.po_id == self.po_a.id)
                .order_by(models.QuarantineResolution.doc_seq).all())
        self.assertEqual([r.doc_number for r in rows],
                         [f"SCR-{q.safe_mo(self.po_a.mo_number)}-0001",
                          f"REL-{q.safe_mo(self.po_a.mo_number)}-0002"])
        other = (self.db.query(models.QuarantineResolution)
                 .filter(models.QuarantineResolution.po_id == self.po_b.id).one())
        self.assertEqual(other.doc_number, f"SCR-{q.safe_mo(self.po_b.mo_number)}-0001")


class NcrLifecycleTests(DbTestCase):
    def test_create_ncr_numbers_and_logs_open(self):
        ncr = q.create_ncr(self.db, self.po_a, self.user,
                           "Diameter drift observed", severity="MAJOR",
                           corrective_action="Re-center the tow guide")
        self.db.flush()
        self.assertEqual(ncr.ncr_number, f"NCR-{q.safe_mo(self.po_a.mo_number)}-0001")
        self.assertEqual(ncr.status, q.NCR_OPEN)
        logs = q.ncr_history(self.db, ncr.id)
        self.assertEqual(len(logs), 1)
        self.assertIsNone(logs[0].from_status)
        self.assertEqual(logs[0].to_status, q.NCR_OPEN)

    def test_close_requires_remarks_and_stamps_audit(self):
        ncr = q.create_ncr(self.db, self.po_a, self.user, "problem")
        self.db.flush()
        with self.assertRaises(q.QualityError) as ctx:
            q.set_ncr_status(self.db, ncr, q.NCR_CLOSED, self.user)
        self.assertEqual(ctx.exception.status, 422)
        q.set_ncr_status(self.db, ncr, q.NCR_IN_PROGRESS, self.user, remarks="working")
        q.set_ncr_status(self.db, ncr, q.NCR_CLOSED, self.user,
                         remarks="Tow guide re-centered, verified OK")
        self.db.flush()
        self.assertEqual(ncr.status, q.NCR_CLOSED)
        self.assertEqual(ncr.closed_by, self.user.id)
        self.assertIsNotNone(ncr.closed_at)
        self.assertIn("verified", ncr.closing_remarks)
        logs = q.ncr_history(self.db, ncr.id)
        self.assertEqual([l.to_status for l in logs],
                         [q.NCR_OPEN, q.NCR_IN_PROGRESS, q.NCR_CLOSED])

    def test_closed_ncr_only_reopens_to_in_progress(self):
        ncr = q.create_ncr(self.db, self.po_a, self.user, "problem")
        q.set_ncr_status(self.db, ncr, q.NCR_CLOSED, self.user, remarks="done")
        self.db.flush()
        with self.assertRaises(q.QualityError):
            q.set_ncr_status(self.db, ncr, q.NCR_OPEN, self.user)
        q.set_ncr_status(self.db, ncr, q.NCR_IN_PROGRESS, self.user, remarks="reopened")
        self.db.flush()
        self.assertEqual(ncr.status, q.NCR_IN_PROGRESS)
        self.assertIsNone(ncr.closed_at)

    def test_invalid_severity_and_empty_description(self):
        with self.assertRaises(q.QualityError):
            q.create_ncr(self.db, self.po_a, self.user, "  ", severity="MAJOR")
        with self.assertRaises(q.QualityError):
            q.create_ncr(self.db, self.po_a, self.user, "x", severity="HUGE")


class SerializationTests(DbTestCase):
    def test_order_quarantine_summary_shape(self):
        shift = self.make_shift()
        self.make_report(shift, self.po_a, quarantine_boxes=7)
        q.create_resolution(self.db, self.po_a, q.KIND_SCRAP, 2, self.user,
                            dry_weight_kg=0.4)
        self.db.flush()
        out = q.order_quarantine_summary(self.db, self.po_a)
        self.assertEqual(out["total_quarantine_boxes"], 7)
        self.assertEqual(out["remaining_boxes"], 5)
        self.assertEqual(out["scrap_kg"], 0.4)
        self.assertEqual(len(out["resolutions"]), 1)
        self.assertEqual(out["resolutions"][0]["kind"], q.KIND_SCRAP)


if __name__ == "__main__":
    unittest.main()
