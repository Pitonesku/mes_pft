"""Phase 3 tests: shadow mode records Odoo writes and never performs them.

Run from backend/:
    python -m unittest tests.test_odoo_shadow -v
"""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from app.services.odoo import client as odoo_client
from app.services.odoo import outbound
from app.services.odoo.shadow import ShadowClient
from tests.test_odoo_completion import FakeOdoo

RUN_SUMMARY = {
    "status": "PASS",
    "rods_total": 100,
    "rods_rejected": 2,
    "parameters": {
        "pd": {"n": 100, "mean": 325.0, "sd_samp": 8.1},
        "diameter": {"n": 100, "mean": 7.72, "sd_samp": 0.012},
    },
}


class RecordingFake(FakeOdoo):
    """FakeOdoo that also counts every write-type call that reaches 'Odoo'."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.sent = []

    def write(self, model, ids, values):
        self.sent.append(("write", model, ids, values))
        return True

    def attach_pdf(self, *a, **k):
        self.sent.append(("attach_pdf", a))
        return 1

    def _call(self, model, method, args, kwargs=None):
        if method == "button_mark_done":
            self.sent.append(("button_mark_done", args))
        return super()._call(model, method, args, kwargs)


class ShadowClientTests(unittest.TestCase):
    def setUp(self):
        self.real = RecordingFake(planned=10.0)
        self.shadow = ShadowClient(self.real)

    def test_quality_is_recorded_not_written(self):
        values = self.shadow.write_mo_quality(1, RUN_SUMMARY)
        self.assertEqual(values[odoo_client.QC_FIELD_QUALITY_STATUS], "pass")
        self.assertEqual(self.shadow.actions[0]["action"], "write_quality")
        self.assertEqual(self.real.sent, [])

    def test_quality_without_measurements_is_skipped(self):
        out = self.shadow.write_mo_quality(1, {"status": "PASS", "parameters": {}})
        self.assertTrue(out["skipped"])
        self.assertEqual(self.real.sent, [])

    def test_pdf_is_recorded_not_attached(self):
        self.shadow.attach_pdf("a.pdf", "mrp.production", 1, b"%PDF-1234")
        self.assertEqual(self.shadow.actions[0]["bytes"], 9)
        self.assertEqual(self.real.sent, [])

    def test_partial_completion_plan_is_recorded(self):
        result = self.shadow.post_completion(1, 4)
        kinds = [a["action"] for a in self.shadow.actions]
        self.assertEqual(kinds[0], "apply_consumption")
        self.assertEqual(kinds[-1], "complete_mo")
        action = self.shadow.actions[-1]
        self.assertEqual(action["qty_producing"], 4.0)
        self.assertEqual(action["planned_qty"], 10.0)
        self.assertTrue(action["expects_backorder"])
        self.assertTrue(result["shadow"])
        self.assertIsNone(result["backorder_id"])
        # Nothing was sent and the real MO is untouched.
        self.assertEqual(self.real.sent, [])
        self.assertEqual(self.real.mos[1]["state"], "confirmed")
        self.assertEqual(len(self.real.mos), 1)

    def test_completion_of_done_mo_is_recorded_as_skipped(self):
        self.real.mos[1]["state"] = "done"
        self.shadow.post_completion(1, 4)
        self.assertEqual(self.shadow.actions[0]["skipped"], "already done")

    def test_reads_reach_real_odoo(self):
        self.assertEqual(self.shadow.resolve_open_mo(1), 1)


class DispatchRunShadowTests(unittest.TestCase):
    def setUp(self):
        self.real = RecordingFake(planned=10.0)
        self.shadow = ShadowClient(self.real)
        self.db_run = SimpleNamespace(
            id=5, shift_id=1, po_id=None, mo_ref="MO-1", odoo_mo_id=None,
            odoo_sync_status="pending", odoo_done_qty=None, odoo_backorder_id=None,
            report_id=None, started_at=None,
        )

    def test_link_only_attaches_quality_and_never_completes(self):
        outbound._dispatch_run(None, self.shadow, self.db_run, RUN_SUMMARY, 1, link_only=True)
        kinds = [a["action"] for a in self.shadow.actions]
        self.assertEqual(kinds, ["write_quality"])
        self.assertNotIn("complete_mo", kinds)
        self.assertEqual(self.real.sent, [])

    def test_full_flow_orders_completion_last(self):
        run = dict(RUN_SUMMARY, certificate=[])
        report = SimpleNamespace(produced_rods=4, materials_json="{}")
        with mock.patch.object(outbound, "_verified_reports", return_value=[report]), \
                mock.patch.object(outbound, "_resolve_material_lots"):
            outbound._dispatch_run(None, self.shadow, self.db_run, run, 1)
        kinds = [a["action"] for a in self.shadow.actions]
        self.assertEqual(kinds[0], "write_quality")
        self.assertEqual(kinds[-1], "complete_mo")
        self.assertEqual(self.real.sent, [])
        self.assertEqual(self.db_run.odoo_mo_id, 1)

    def test_gate_blocks_before_any_action(self):
        with mock.patch.object(
            outbound, "_verified_reports",
            side_effect=outbound.AwaitingVerification("pending"),
        ):
            with self.assertRaises(outbound.AwaitingVerification):
                outbound._dispatch_run(None, self.shadow, self.db_run, RUN_SUMMARY, 1)
        self.assertEqual(self.shadow.actions, [])


class ConfigTests(unittest.TestCase):
    def test_shadow_flag_from_env(self):
        with mock.patch.dict(os.environ, {"ODOO_SHADOW_MODE": "true"}):
            self.assertTrue(odoo_client.OdooConfig.from_env().shadow)
        with mock.patch.dict(os.environ, {"ODOO_SHADOW_MODE": ""}):
            self.assertFalse(odoo_client.OdooConfig.from_env().shadow)


class LiveDispatchSkipTests(unittest.TestCase):
    """A live (non-shadow) completion that is skipped must fail, never 'synced'."""

    class SkippingClient:
        is_shadow = False

        def resolve_open_mo(self, mo_id):
            return mo_id

        def write_mo_quality(self, mo_id, run):
            return {"skipped": False}

        def attach_pdf(self, *args, **kwargs):
            return 1

        def attach_file(self, *args, **kwargs):
            return 1

        def post_completion(self, mo_id, qty_rods, consumption=None):
            return {"skipped": True, "reason": "already done"}

    def test_skip_raises_and_does_not_mark_synced(self):
        run = dict(RUN_SUMMARY, certificate=[])
        report = SimpleNamespace(produced_rods=4, materials_json="{}")
        db_run = SimpleNamespace(
            id=5, shift_id=1, po_id=None, mo_ref="MO-1", odoo_mo_id=None,
            odoo_sync_status="pending", odoo_done_qty=None, odoo_backorder_id=None,
            report_id=None, started_at=None,
        )
        client = self.SkippingClient()
        with mock.patch.object(outbound, "_verified_reports", return_value=[report]), \
                mock.patch.object(outbound, "_resolve_material_lots"):
            with self.assertRaises(odoo_client.OdooError):
                outbound._dispatch_run(None, client, db_run, run, 1)
        self.assertEqual(db_run.odoo_sync_status, "pending")


if __name__ == "__main__":
    unittest.main()
