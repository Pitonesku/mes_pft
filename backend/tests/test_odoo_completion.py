"""Tests for MO completion / backorder logic and the Odoo webhook signature.

Run from backend/:
    python -m unittest tests.test_odoo_completion -v
"""

import hashlib
import hmac
import os
import time
import unittest
from unittest import mock

from app.services.odoo import client as odoo_client


def _val(v):
    return v[0] if isinstance(v, (list, tuple)) else v


class FakeOdoo(odoo_client.OdooClient):
    """In-memory stand-in for Odoo's mrp.production chain (one procurement group)."""

    def __init__(self, planned=10.0, wizard=False):
        self.mos = {
            1: {"id": 1, "state": "confirmed", "product_qty": planned,
                "product_uom_id": [1, "Pcs"], "procurement_group_id": [7, "G"],
                "backorder_sequence": 0},
        }
        self.wizard = wizard
        self.calls = []

    def connect(self):
        pass

    def read(self, model, ids, fields):
        if model == "uom.uom":
            if "factor" in fields:
                return [{"name": "Pcs", "factor": 1.0}]
            return [{"rounding": 0.001}]
        return [dict(self.mos[i]) for i in ids if i in self.mos]

    def write(self, model, ids, values):
        self.calls.append(("write", ids, values))
        return True

    def search_read(self, model, domain, fields, limit=None, order=None):
        rows = [dict(m) for m in self.mos.values()]
        for field, op, value in domain:
            if op == "=":
                rows = [r for r in rows if _val(r.get(field)) == value]
            elif op == ">":
                rows = [r for r in rows if (r.get(field) or 0) > value]
            elif op == "in":
                rows = [r for r in rows if r.get(field) in value]
        rows.sort(key=lambda r: r["backorder_sequence"], reverse=bool(order and "desc" in order))
        return rows[:limit] if limit else rows

    def _call(self, model, method, args, kwargs=None):
        if method != "button_mark_done":
            raise AssertionError(method)
        self.calls.append(("button_mark_done", args, kwargs))
        if self.wizard:
            return {"res_model": "mrp.production.backorder", "type": "ir.actions.act_window"}
        mo_id = args[0][0]
        mo = self.mos[mo_id]
        mo["state"] = "done"
        if mo_id in (kwargs or {}).get("context", {}).get("mo_ids_to_backorder", []):
            new_id = max(self.mos) + 1
            self.mos[new_id] = {
                **mo, "id": new_id, "state": "confirmed",
                "backorder_sequence": mo["backorder_sequence"] + 1,
            }
        return True


def _done_context(client):
    return [c for c in client.calls if c[0] == "button_mark_done"][0][2]["context"]


class PostCompletionTests(unittest.TestCase):
    def test_partial_completion_creates_backorder(self):
        c = FakeOdoo(planned=10.0)
        result = c.post_completion(1, 4)
        self.assertEqual(result["qty"], 4.0)
        self.assertEqual(result["backorder_id"], 2)
        ctx = _done_context(c)
        self.assertEqual(ctx["mo_ids_to_backorder"], [1])
        self.assertTrue(ctx["skip_backorder"])

    def test_full_completion_has_no_backorder(self):
        c = FakeOdoo(planned=10.0)
        result = c.post_completion(1, 10)
        self.assertIsNone(result["backorder_id"])
        self.assertNotIn("mo_ids_to_backorder", _done_context(c))

    def test_already_done_is_skipped(self):
        c = FakeOdoo()
        c.mos[1]["state"] = "done"
        self.assertTrue(c.post_completion(1, 5)["skipped"])
        self.assertFalse([x for x in c.calls if x[0] == "button_mark_done"])

    def test_wizard_result_is_an_error_not_silent_success(self):
        with self.assertRaises(odoo_client.OdooError):
            FakeOdoo(wizard=True).post_completion(1, 4)

    def test_zero_quantity_is_skipped(self):
        self.assertTrue(FakeOdoo().post_completion(1, 0)["skipped"])


class ResolveOpenMoTests(unittest.TestCase):
    def test_open_mo_returned_as_is(self):
        self.assertEqual(FakeOdoo().resolve_open_mo(1), 1)

    def test_follows_backorder_chain(self):
        c = FakeOdoo(planned=10.0)
        c.post_completion(1, 4)
        self.assertEqual(c.resolve_open_mo(1), 2)
        c.post_completion(2, 3)
        self.assertEqual(c.resolve_open_mo(1), 3)

    def test_closed_chain_returns_none(self):
        c = FakeOdoo(planned=10.0)
        c.post_completion(1, 10)
        self.assertIsNone(c.resolve_open_mo(1))


class WebhookSignatureTests(unittest.TestCase):
    SECRET = "s3cret"

    def setUp(self):
        from fastapi import HTTPException
        from app import v2_routes
        self.http_error = HTTPException
        self.verify = v2_routes._verify_odoo_webhook
        patcher = mock.patch.dict(os.environ, {"ODOO_WEBHOOK_SECRET": self.SECRET})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("ODOO_WEBHOOK_REQUIRE_TIMESTAMP", None)

    def _sign(self, payload):
        return "sha256=" + hmac.new(self.SECRET.encode(), payload, hashlib.sha256).hexdigest()

    def test_signed_body_ok(self):
        body = b'{"mo_id": 1}'
        ts = str(int(time.time()))
        self.verify("mes:mo:1", self._sign(ts.encode() + b"." + body), body=body, timestamp=ts)

    def test_tampered_body_rejected(self):
        ts = str(int(time.time()))
        sig = self._sign(ts.encode() + b'.{"mo_id": 1}')
        with self.assertRaises(self.http_error):
            self.verify("mes:mo:1", sig, body=b'{"mo_id": 2}', timestamp=ts)

    def test_stale_timestamp_rejected(self):
        body = b"{}"
        ts = str(int(time.time()) - 3600)
        with self.assertRaises(self.http_error):
            self.verify("mes:mo:1", self._sign(ts.encode() + b"." + body), body=body, timestamp=ts)

    def test_legacy_signature_accepted_by_default(self):
        self.verify("mes:mo:1", self._sign(b"mes:mo:1"))

    def test_legacy_rejected_when_timestamp_required(self):
        with mock.patch.dict(os.environ, {"ODOO_WEBHOOK_REQUIRE_TIMESTAMP": "true"}):
            with self.assertRaises(self.http_error):
                self.verify("mes:mo:1", self._sign(b"mes:mo:1"))

    def test_missing_signature_rejected(self):
        with self.assertRaises(self.http_error):
            self.verify("mes:mo:1", None)


if __name__ == "__main__":
    unittest.main()
