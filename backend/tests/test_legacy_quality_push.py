"""Legacy quality push: lot format, report<->MO matching, and the stock-safety guard."""

import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.lot_number import lot_number
from app.services.odoo import legacy_matching as lm
from app.services.odoo import legacy_push
from app.services.odoo.client import OdooClient

TZ = ZoneInfo("Europe/Budapest")


class LotNumberTests(unittest.TestCase):
    def test_format_uses_shift_start_date(self):
        start = datetime(2026, 7, 31, 14, 0, tzinfo=TZ)
        self.assertEqual(lot_number(start, "M1"), "310726M1")
        self.assertEqual(lot_number(start, "M2"), "310726M2")

    def test_utc_timestamp_converted_to_plant_date(self):
        # 22:30 UTC on 30 Jul is 00:30 on 31 Jul in Budapest (UTC+2)
        start = datetime(2026, 7, 30, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(lot_number(start, "M1"), "310726M1")

    def test_night_shift_keeps_start_date(self):
        start = datetime(2026, 8, 3, 22, 0, tzinfo=TZ)  # runs past midnight
        self.assertEqual(lot_number(start, "M2"), "030826M2")

    def test_unknown_inputs(self):
        self.assertIsNone(lot_number(None, "M1"))
        self.assertIsNone(lot_number(datetime(2026, 7, 31, tzinfo=TZ), "Line"))


class MatchTests(unittest.TestCase):
    def test_exact_quantity_pairs_and_only_done_mos(self):
        reports = [{"id": 179, "rods": 860100}, {"id": 185, "rods": 921200}]
        mos = [
            {"id": 508, "name": "-002", "rods": 860100, "state": "done"},
            {"id": 513, "name": "-007", "rods": 921200, "state": "done"},
            {"id": 599, "name": "-099", "rods": 5, "state": "confirmed"},
        ]
        out = lm.match_reports_to_mos(reports, mos)
        self.assertEqual({(r["id"], m["name"]) for r, m in out["pairs"]},
                         {(179, "-002"), (185, "-007")})
        self.assertEqual(out["unmatched_mos"], [])  # the open MO is not a candidate

    def test_duplicate_quantity_with_one_mo_collapses_to_duplicate(self):
        # Same date/machine/shift/qty (the H081/H083 case): treated as one report.
        reports = [
            {"id": 1, "rods": 100, "date": "2026-08-13", "machine": "M2", "shift": "Shift 1"},
            {"id": 2, "rods": 100, "date": "2026-08-13", "machine": "M2", "shift": "Shift 1"},
        ]
        mos = [{"id": 9, "name": "-1", "rods": 100, "state": "done", "seq": 1}]
        out = lm.match_reports_to_mos(reports, mos)
        self.assertEqual([(r["id"], m["name"]) for r, m in out["pairs"]], [(1, "-1")])
        self.assertEqual(out["deduped"], 1)

    def test_two_reports_one_mo_stays_ambiguous(self):
        # Same qty but different machine -> NOT a duplicate; 2 reports vs 1 MO.
        reports = [
            {"id": 1, "rods": 100, "date": "2026-08-13", "machine": "M1", "shift": "Shift 1"},
            {"id": 2, "rods": 100, "date": "2026-08-13", "machine": "M2", "shift": "Shift 1"},
        ]
        mos = [{"id": 9, "name": "-1", "rods": 100, "state": "done", "seq": 1}]
        out = lm.match_reports_to_mos(reports, mos)
        self.assertEqual(out["pairs"], [])
        self.assertEqual(len(out["ambiguous"]), 1)

    def test_unmatched_both_sides_reported(self):
        out = lm.match_reports_to_mos(
            [{"id": 1, "rods": 10}], [{"id": 2, "name": "-2", "rods": 20, "state": "done"}])
        self.assertEqual([r["id"] for r in out["unmatched_reports"]], [1])
        self.assertEqual([m["name"] for m in out["unmatched_mos"]], ["-2"])

    def test_exact_duplicate_reports_collapse(self):
        reports = [
            {"id": 188, "rods": 272600, "date": "2026-08-04", "machine": "M2", "shift": "Shift 1"},
            {"id": 189, "rods": 272600, "date": "2026-08-04", "machine": "M2", "shift": "Shift 1"},
        ]
        mos = [{"id": 1, "name": "-002", "rods": 272600, "state": "done", "seq": 2}]
        out = lm.match_reports_to_mos(reports, mos)
        self.assertEqual([(r["id"], m["name"]) for r, m in out["pairs"]], [(188, "-002")])
        self.assertEqual(out["deduped"], 1)

    def test_n_reports_n_mos_pair_by_machine_and_sequence(self):
        reports = [
            {"id": 212, "rods": 2119700, "date": "2026-08-10", "machine": "M2", "shift": "Shift 2"},
            {"id": 213, "rods": 2119700, "date": "2026-08-10", "machine": "M1", "shift": "Shift 2"},
        ]
        mos = [
            {"id": 7, "name": "-007", "rods": 2119700, "state": "done", "seq": 7},
            {"id": 8, "name": "-008", "rods": 2119700, "state": "done", "seq": 8},
        ]
        out = lm.match_reports_to_mos(reports, mos)
        got = {r["machine"]: m["name"] for r, m in out["pairs"]}
        self.assertEqual(got, {"M1": "-007", "M2": "-008"})  # M1 -> lower seq
        self.assertEqual(out["ambiguous"], [])


class RecordingClient(OdooClient):
    """Fake Odoo: records every call so the test can prove nothing touches stock."""

    def __init__(self, existing_lot=False):
        self.calls = []
        self._existing_lot = existing_lot

    def read(self, model, ids, fields):
        self.calls.append(("read", model))
        return [{"x_lot_number": "OLDLOT" if self._existing_lot else False}]

    def search_read(self, model, domain, fields, limit=None, order=None):
        self.calls.append(("search_read", model))
        return []

    def write(self, model, ids, values):
        self.calls.append(("write", model, dict(values)))
        return True

    def create(self, model, values):
        self.calls.append(("create", model))
        return 1

    def call(self, model, method, ids):  # button_* / action_* must never be used
        self.calls.append(("call", model, method))
        return True


def _summary():
    return {
        "run_id": 1, "mo_ref": "WH/MO/1", "status": "PASS", "rods_total": 10,
        "rods_rejected": 0, "rods_used": 10,
        "parameters": {"pd": {"n": 10, "mean": 325.0, "sd_samp": 5.0},
                       "diameter": {"n": 10, "mean": 7.72, "sd_samp": 0.01}},
        "certificate": [{"parameter": "pd", "unit": "mm WG", "nominal": 325, "lower": 310,
                         "upper": 350, "mean": 325, "sd": 5, "n": 10, "status": "PASS"}],
    }


class PushSafetyTests(unittest.TestCase):
    def test_writes_only_whitelisted_fields_and_never_completes(self):
        c = RecordingClient()
        out = legacy_push.push_pair(c, {"id": 508, "name": "WH/MO/00189-002"}, _summary(),
                                    b"a,b\n1,2\n", 135, 178, "310726M1", dry_run=False)
        writes = [x for x in c.calls if x[0] == "write" and x[1] == "mrp.production"]
        self.assertEqual(len(writes), 1)
        self.assertTrue(set(writes[0][2]) <= legacy_push.ALLOWED_FIELDS)
        self.assertEqual(writes[0][2]["mes_sync_status"], "synced")
        self.assertEqual(writes[0][2]["x_lot_number"], "310726M1")
        self.assertFalse([x for x in c.calls if x[0] == "call"])  # no button_mark_done etc.
        touched = {x[1] for x in c.calls if x[0] in ("write", "create")}
        self.assertTrue(touched <= {"mrp.production", "ir.attachment"})
        self.assertEqual(out["attachments"][-1], "Quality_Measurements_WH_MO_00189-002.csv")

    def test_existing_lot_is_not_overwritten(self):
        c = RecordingClient(existing_lot=True)
        legacy_push.push_pair(c, {"id": 1, "name": "WH/MO/1"}, _summary(), b"x", 1, 1,
                              "310726M1", dry_run=False)
        write = next(x for x in c.calls if x[0] == "write" and x[1] == "mrp.production")
        self.assertNotIn("x_lot_number", write[2])

    def test_dry_run_writes_nothing(self):
        c = RecordingClient()
        legacy_push.push_pair(c, {"id": 1, "name": "WH/MO/1"}, _summary(), b"x", 1, 1,
                              "310726M1", dry_run=True)
        self.assertFalse([x for x in c.calls if x[0] in ("write", "create")])

    def test_no_measured_rods_is_skipped(self):
        c = RecordingClient()
        s = {**_summary(), "parameters": {}}
        out = legacy_push.push_pair(c, {"id": 1, "name": "WH/MO/1"}, s, b"x", 1, 1, "L", False)
        self.assertIn("skipped", out)
        self.assertFalse([x for x in c.calls if x[0] in ("write", "create")])


class AttachReplaceTests(unittest.TestCase):
    def test_attach_file_updates_existing_instead_of_duplicating(self):
        class C(RecordingClient):
            def search_read(self, model, domain, fields, limit=None, order=None):
                self.calls.append(("search_read", model))
                return [{"id": 77}]

        c = C()
        self.assertEqual(c.attach_file("a.csv", "mrp.production", 5, b"z", "text/csv"), 77)
        self.assertEqual([x[0] for x in c.calls if x[0] in ("write", "create")], ["write"])


if __name__ == "__main__":
    unittest.main()

