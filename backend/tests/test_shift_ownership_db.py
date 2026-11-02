"""S1: only the shift's own operator (or a supervisor/admin) may close/stop it.

Runs against the real PostgreSQL schema inside a rolled-back transaction
(see tests/db_support.py). Skipped when the database is not reachable.
"""

import unittest
import uuid
from datetime import timedelta

from fastapi import HTTPException

from app import models, v2_routes as v2
from app.services import shift_lifecycle
from tests.db_support import DbTestCase


class ShiftOwnershipTests(DbTestCase):
    def _suffix(self) -> str:
        return uuid.uuid4().hex[:8]

    def make_user(self, can_edit_report=False, manager_role=False):
        role = None
        if manager_role:
            role = self.db.query(models.Role).filter_by(role_name="manager").first()
            if role is None:
                role = models.Role(role_name="manager")
                self.db.add(role)
                self.db.flush()
        user = models.User(
            username=f"s1_{self._suffix()}", email="", password_hash="x",
            role_id=role.id if role else None, can_edit_report=can_edit_report,
        )
        self.db.add(user)
        self.db.flush()
        return user

    def _open_as(self, user, machine=None, **kw):
        return v2.open_shift(
            v2.ShiftOpen(
                machine_id=(machine or self.m1).id, po_id=self.po_a.id,
                shift_name=f"S1-OWN-{self._suffix()}", operator_id=user.id, **kw,
            ),
            db=self.db, current_user=user,
        )

    def _get(self, shift_id):
        return self.db.query(models.ShiftSession).filter(models.ShiftSession.id == shift_id).first()

    # --- close ---

    def test_operator_cannot_close_another_operators_shift(self):
        owner, other = self.make_user(), self.make_user()
        opened = self._open_as(owner)
        with self.assertRaises(HTTPException) as ctx:
            v2.close_shift(opened["id"], v2.ShiftClose(), db=self.db, current_user=other,
                           idempotency_key=None)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(self._get(opened["id"]).status, "IN_PROGRESS")  # untouched

    def test_owner_can_close_own_shift(self):
        owner = self.make_user()
        opened = self._open_as(owner)
        summary = v2.close_shift(opened["id"], v2.ShiftClose(), db=self.db, current_user=owner,
                                 idempotency_key=None)
        self.assertIn("runs", summary)
        self.assertEqual(self._get(opened["id"]).status, "CLOSED")

    def test_supervisor_grant_can_close_another_operators_shift(self):
        owner, supervisor = self.make_user(), self.make_user(can_edit_report=True)
        opened = self._open_as(owner)
        summary = v2.close_shift(opened["id"], v2.ShiftClose(), db=self.db, current_user=supervisor,
                                 idempotency_key=None)
        self.assertIn("runs", summary)
        shift = self._get(opened["id"])
        self.assertEqual((shift.status, shift.closed_by), ("CLOSED", supervisor.id))

    def test_manager_role_can_close_another_operators_shift(self):
        owner, manager = self.make_user(), self.make_user(manager_role=True)
        opened = self._open_as(owner)
        summary = v2.close_shift(opened["id"], v2.ShiftClose(), db=self.db, current_user=manager,
                                 idempotency_key=None)
        self.assertIn("runs", summary)
        self.assertEqual(self._get(opened["id"]).status, "CLOSED")

    def test_closed_shift_replay_stays_idempotent_for_any_authenticated_user(self):
        owner, other = self.make_user(), self.make_user()
        opened = self._open_as(owner)
        v2.close_shift(opened["id"], v2.ShiftClose(), db=self.db, current_user=owner,
                       idempotency_key=None)
        # Offline retry from another device/user must return the stored summary, not 403.
        replay = v2.close_shift(opened["id"], v2.ShiftClose(), db=self.db, current_user=other,
                                idempotency_key=None)
        self.assertIn("runs", replay)

    # --- stop ---

    def test_operator_cannot_stop_another_operators_shift(self):
        owner, other = self.make_user(), self.make_user()
        opened = self._open_as(owner)
        with self.assertRaises(HTTPException) as ctx:
            v2.stop_shift(opened["id"], db=self.db, current_user=other)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIsNone(self._get(opened["id"]).ended_at)  # still active

    def test_owner_can_stop_own_shift(self):
        owner = self.make_user()
        opened = self._open_as(owner)
        stopped = v2.stop_shift(opened["id"], db=self.db, current_user=owner)
        self.assertEqual(stopped["status"], "AUTO_CLOSED")

    def test_supervisor_can_stop_another_operators_shift(self):
        owner, supervisor = self.make_user(), self.make_user(can_edit_report=True)
        opened = self._open_as(owner)
        stopped = v2.stop_shift(opened["id"], db=self.db, current_user=supervisor)
        self.assertEqual(stopped["status"], "AUTO_CLOSED")

    # --- resume ownership ---

    def test_resume_transfers_ownership_to_the_resuming_operator(self):
        owner, other = self.make_user(), self.make_user()
        future = shift_lifecycle.utcnow() + timedelta(hours=12)
        name = f"S1-RES-{self._suffix()}"
        opened = v2.open_shift(
            v2.ShiftOpen(machine_id=self.m1.id, po_id=self.po_a.id,
                         shift_name=name, operator_id=owner.id, scheduled_end_at=future),
            db=self.db, current_user=owner,
        )
        v2.stop_shift(opened["id"], db=self.db, current_user=owner)

        resumed = v2.open_shift(
            v2.ShiftOpen(machine_id=self.m1.id, po_id=self.po_b.id,
                         shift_name=name, operator_id=other.id, scheduled_end_at=future),
            db=self.db, current_user=other,
        )
        self.assertEqual(resumed["id"], opened["id"])  # resumed, not re-created
        self.assertEqual(self._get(opened["id"]).operator_id, other.id)

        with self.assertRaises(HTTPException) as ctx:  # old owner is locked out
            v2.close_shift(opened["id"], v2.ShiftClose(), db=self.db, current_user=owner,
                           idempotency_key=None)
        self.assertEqual(ctx.exception.status_code, 403)

        summary = v2.close_shift(opened["id"], v2.ShiftClose(), db=self.db, current_user=other,
                                 idempotency_key=None)
        self.assertIn("runs", summary)


if __name__ == "__main__":
    unittest.main()
