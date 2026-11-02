"""Bug reports: create validation, persistence and review lifecycle."""

import base64
import unittest

from app import models
from app.services import bug_reports as svc
from tests.db_support import DbTestCase


class BugReportServiceTests(DbTestCase):
    def test_create_with_attachment(self):
        r = svc.create(
            self.db, self.user, "Weigh station keeps beeping on M1",
            "tablet",
            [{"filename": "shot.png", "mime": "image/png",
              "data_base64": base64.b64encode(b"PNGDATA").decode()}],
        )
        self.db.flush()
        self.assertEqual(r.status, "NEW")
        self.assertEqual(r.username, self.user.username)
        atts = self.db.query(models.BugReportAttachment).filter(
            models.BugReportAttachment.bug_report_id == r.id).all()
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts[0].data, b"PNGDATA")

    def test_text_required_and_length(self):
        with self.assertRaises(svc.BugReportError) as cm:
            svc.create(self.db, self.user, "   ", "web", None)
        self.assertEqual(cm.exception.status, 422)
        with self.assertRaises(svc.BugReportError):
            svc.create(self.db, self.user, "x" * 2001, "web", None)

    def test_attachment_limits(self):
        with self.assertRaises(svc.BugReportError):
            svc.create(self.db, self.user, "t", "web",
                       [{"filename": f"f{i}.png", "mime": "image/png",
                         "data_base64": base64.b64encode(b"x").decode()} for i in range(4)])
        with self.assertRaises(svc.BugReportError):
            svc.create(self.db, self.user, "t", "web",
                       [{"filename": "bad.png", "mime": "image/png", "data_base64": "!!!not-base64!!!"}])

    def test_resolve_lifecycle(self):
        r = svc.create(self.db, self.user, "UI glitch", "web", None)
        self.db.flush()
        svc.resolve(self.db, r, self.user, "IN_PROGRESS", "looking into it")
        self.assertEqual(r.status, "IN_PROGRESS")
        svc.resolve(self.db, r, self.user, "RESOLVED", "fixed in b56")
        self.assertEqual(r.status, "RESOLVED")
        self.assertEqual(r.resolved_by, self.user.username)
        self.assertIsNotNone(r.resolved_at)
        with self.assertRaises(svc.BugReportError):
            svc.resolve(self.db, r, self.user, "BOGUS", None)


if __name__ == "__main__":
    unittest.main()
