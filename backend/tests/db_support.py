"""Shared fixture for tests that need the real PostgreSQL schema.

Every test runs inside an outer transaction that is rolled back, so the dev
database is never modified. The tests skip themselves when the database is not
reachable or migration 0018 has not been applied.
"""

import unittest
from datetime import timedelta

try:
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app import models
    from app.database import engine
    from app.services import shift_lifecycle as lc
    with engine.connect() as _c:
        DB_READY = bool(_c.execute(text(
            "select count(*) from information_schema.columns "
            "where table_name='production_runs' and column_name='machine_id'")).scalar())
except Exception:  # noqa: BLE001
    DB_READY = False


@unittest.skipUnless(DB_READY, "database with migration 0018 not available")
class DbTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = engine.connect()
        self.trans = self.conn.begin()
        self.db = Session(bind=self.conn, join_transaction_mode="create_savepoint", autoflush=False)
        # Park whatever is open (inside the rolled-back transaction) so any machine is free.
        self.db.execute(text("update production_runs set ended_at = now(), status='CLOSED' where ended_at is null"))
        self.db.execute(text("update shift_sessions set ended_at = now(), status='AUTO_CLOSED' where ended_at is null"))
        self.user = self.db.query(models.User).first()
        machines = self.db.query(models.Machine).order_by(models.Machine.id).limit(2).all()
        pos = self.db.query(models.PurchaseOrder).order_by(models.PurchaseOrder.id.desc()).limit(3).all()
        if len(machines) < 2 or len(pos) < 2 or self.user is None:
            self.skipTest("needs two machines, two purchase orders and a user")
        self.m1, self.m2 = machines
        self.po_a, self.po_b = pos[0], pos[1]

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.conn.close()

    def make_shift(self, machine=None):
        s = models.ShiftSession(
            machine_id=(machine or self.m1).id, operator_id=self.user.id,
            started_at=lc.utcnow() - timedelta(hours=1), status="IN_PROGRESS")
        self.db.add(s)
        self.db.flush()
        return s

    def make_report(self, shift, po, machine=None, run_id=None, **extra):
        rep = models.ProductionReport(
            report_date="2026-10-10", shift_name="Shift 1", machine_name=(machine or self.m1).name,
            operator_name="t", po_number=po.po_number, boxes_produced=1, waste_kg=0,
            shift_id=shift.id, run_id=run_id, **extra)
        self.db.add(rep)
        self.db.flush()
        return rep
