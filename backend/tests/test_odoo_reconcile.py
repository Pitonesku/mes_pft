"""Phase 2 tests: chain status, reconciliation and state events.

Fakes only (no DB, no Odoo). Run from backend/:
    python -m unittest tests.test_odoo_reconcile -v
"""

import unittest
from types import SimpleNamespace

from app import models
from app.services.odoo import inbound, reconcile
from tests.test_odoo_completion import FakeOdoo


def chain_client(*states_qty):
    """FakeOdoo with a chain: [(state, qty), ...] - first entry is the root MO."""
    c = FakeOdoo(planned=10.0)
    c.mos = {}
    for i, (state, qty) in enumerate(states_qty, start=1):
        c.mos[i] = {
            "id": i, "state": state, "product_qty": qty,
            "product_uom_id": [1, "Pcs"], "procurement_group_id": [7, "G"],
            "backorder_sequence": i - 1,
        }
    return c


def order(**kw):
    base = dict(
        id=1, po_number="PO-1", odoo_mo_id=1, odoo_current_mo_id=None,
        odoo_state=None, odoo_synced_at=None, odoo_qty_drift=None,
        sync_mode="full", target_qty=10,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class ChainStatusTests(unittest.TestCase):
    def test_open_chain_reports_latest_open_mo(self):
        c = chain_client(("done", 4), ("confirmed", 6))
        s = c.chain_status(1)
        self.assertEqual((s["state"], s["open_mo_id"]), ("open", 2))
        self.assertEqual(s["total_qty"], 10.0)

    def test_finished_chain(self):
        s = chain_client(("done", 4), ("done", 6)).chain_status(1)
        self.assertEqual((s["state"], s["open_mo_id"]), ("done", None))

    def test_all_cancelled(self):
        s = chain_client(("cancel", 10)).chain_status(1)
        self.assertEqual(s["state"], "cancel")

    def test_cancelled_backorder_not_counted_in_total(self):
        s = chain_client(("done", 4), ("cancel", 6)).chain_status(1)
        self.assertEqual(s["state"], "done")
        self.assertEqual(s["total_qty"], 4.0)

    def test_missing_mo(self):
        c = chain_client(("confirmed", 10))
        self.assertEqual(c.chain_status(99)["state"], "missing")


class ReconcileOrderTests(unittest.TestCase):
    def test_open_chain_advances_current_mo(self):
        po = order()
        report = reconcile.reconcile_order(chain_client(("done", 4), ("confirmed", 6)), po)
        self.assertEqual(po.odoo_state, "open")
        self.assertEqual(po.odoo_current_mo_id, 2)
        self.assertEqual(po.sync_mode, "full")
        self.assertTrue(report["changed"])
        self.assertIsNotNone(po.odoo_synced_at)

    def test_cancelled_chain_downgrades_sync_mode(self):
        po = order()
        report = reconcile.reconcile_order(chain_client(("cancel", 10)), po)
        self.assertEqual(po.odoo_state, "cancel")
        self.assertEqual(po.sync_mode, "link_only")
        self.assertTrue(report["notes"])

    def test_done_chain_downgrades_sync_mode(self):
        po = order()
        reconcile.reconcile_order(chain_client(("done", 10)), po)
        self.assertEqual((po.odoo_state, po.sync_mode), ("done", "link_only"))

    def test_missing_mo_flags_but_keeps_everything(self):
        po = order(odoo_mo_id=99, sync_mode="full")
        reconcile.reconcile_order(chain_client(("confirmed", 10)), po)
        self.assertEqual(po.odoo_state, "missing")
        self.assertEqual(po.sync_mode, "full")      # one failed lookup must not unlink
        self.assertEqual(po.odoo_mo_id, 99)

    def test_quantity_drift_is_informational(self):
        po = order(target_qty=8)
        reconcile.reconcile_order(chain_client(("confirmed", 10)), po)
        self.assertEqual(po.odoo_qty_drift, 2.0)
        self.assertEqual(po.target_qty, 8)          # never overwritten

    def test_unlinked_order_skipped(self):
        po = order(odoo_mo_id=None)
        self.assertEqual(reconcile.reconcile_order(chain_client(("confirmed", 1)), po)["skipped"], "not linked")


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *a, **k):
        return self

    def first(self):
        return self.result


class FakeSession:
    def __init__(self, po):
        self.po, self.commits = po, 0

    def query(self, model):
        return FakeQuery(self.po)

    def commit(self):
        self.commits += 1


class StateEventTests(unittest.TestCase):
    def test_done_event_marks_check_not_done(self):
        po = order(odoo_state="open")
        s = FakeSession(po)
        out = inbound.handle_mo_event(s, {"mo_id": 1, "state": "done", "root_mo_id": 1})
        self.assertEqual(po.odoo_state, "check")
        self.assertEqual(out["po_id"], 1)

    def test_cancel_event_does_not_reopen_finished_order(self):
        po = order(odoo_state="done")
        inbound.handle_mo_event(FakeSession(po), {"mo_id": 1, "state": "cancel"})
        self.assertEqual(po.odoo_state, "done")

    def test_unknown_order_is_ignored_not_created(self):
        s = FakeSession(None)
        out = inbound.handle_mo_event(s, {"mo_id": 5, "state": "cancel"})
        self.assertTrue(out["ignored"])
        self.assertEqual(s.commits, 0)


class FakeChainClient:
    """Stub OdooClient for suggest_unlinked_orders tests."""

    def __init__(self, mos):
        self.mos = mos
        self.uom_ratio_calls = 0
        self.fetched_uom_ids = None

    def search_read(self, model, domain, fields, limit=None, order=None):
        assert model == "mrp.production"
        return self.mos

    def fetch_uom_ratios(self, uom_ids):
        self.uom_ratio_calls += 1
        self.fetched_uom_ids = set(int(i) for i in uom_ids if i)
        return {int(i): 1000.0 for i in uom_ids if i}

    def to_rods(self, qty, uom_id):
        return float(qty) * 1000.0


def mo(id_, name, origin, state, group, seq, qty, dates, product_name):
    return {
        "id": id_, "name": name, "origin": origin, "x_production_order_no": None,
        "state": state, "product_id": [1, product_name], "product_qty": qty,
        "product_uom_id": [36, "1000pcs"], "backorder_sequence": seq,
        "procurement_group_id": [group, "G"], "date_start": dates[0],
        "date_finished": dates[1], "date_deadline": None,
    }


class ChainMatcherTests(unittest.TestCase):
    def _orders(self, *specs):
        out = []
        for i, (num, dia, ln, pd) in enumerate(specs, start=1):
            out.append(SimpleNamespace(
                id=i, po_number=num, target_qty=10000000, diameter=dia, length=ln, pd=pd,
                odoo_mo_id=None, odoo_state=None, odoo_current_mo_id=None,
                sync_mode="link_only", odoo_mo_name=None, odoo_linked_at=None,
                odoo_synced_at=None, odoo_qty_drift=None, source="local",
            ))
        return out

    def test_code_match_on_source_groups_chain(self):
        client = FakeChainClient([
            mo(10, "WH/MO/00155", "F058", "done", 7, 0, 5000, ["2026-05-01", "2026-05-05"], "7.72*108 PD325 0Cu"),
            mo(11, "WH/MO/00155-001", "F058", "done", 7, 1, 4000, ["2026-05-05", "2026-05-08"], "7.72*108 PD325 0Cu"),
        ])
        class Q:
            def __init__(self, orders):
                self.orders = orders
            def filter(self, *a, **k):
                return self
            def order_by(self, *a):
                return self
            def all(self):
                return self.orders
            def first(self):
                return (None, None)
        s = SimpleNamespace(query=lambda *a, **k: Q(self._orders(("F058", 7.72, 108, 325))))
        out = reconcile.suggest_unlinked_orders(s, client)
        self.assertEqual(out["orders"], 1)
        self.assertEqual(len(out["review"][0]["candidates"]), 1)
        c = out["review"][0]["candidates"][0]
        self.assertEqual(c["root_id"], 10)
        self.assertEqual(c["mo_count"], 2)
        self.assertEqual(c["matched_on"], "code:source")
        self.assertIn("done_history", c["risk"])

    def test_heuristic_spec_and_date_within_window(self):
        client = FakeChainClient([
            mo(20, "WH/MO/00200", None, "done", 9, 0, 8000, ["2026-09-01", "2026-09-04"], "6.03*108 PD380 0Cu"),
        ])
        class Q:
            def filter(self, *a, **k):
                return self
            def order_by(self, *a):
                return self
            def all(self):
                return self._orders
            def first(self):
                return ("2026-09-02", "2026-09-06")
        orders = self._orders(("I099", 6.03, 108, 380))
        q = Q()
        q._orders = orders
        s = SimpleNamespace(query=lambda *a, **k: q)
        out = reconcile.suggest_unlinked_orders(s, client)
        self.assertEqual(len(out["review"][0]["candidates"]), 1)
        c = out["review"][0]["candidates"][0]
        self.assertEqual(c["matched_on"], "heuristic:spec+date")
        self.assertIn("done_history", c["risk"])

    def test_heuristic_rejected_when_outside_window(self):
        client = FakeChainClient([
            mo(30, "WH/MO/00003", None, "done", 11, 0, 8000, ["2026-02-01", "2026-02-05"], "7.72*108 PD325 0Cu"),
        ])
        class Q:
            def filter(self, *a, **k):
                return self
            def order_by(self, *a):
                return self
            def all(self):
                return self._orders
            def first(self):
                return ("2026-09-02", "2026-09-06")
        orders = self._orders(("I099", 7.72, 108, 325))
        q = Q()
        q._orders = orders
        s = SimpleNamespace(query=lambda *a, **k: q)
        out = reconcile.suggest_unlinked_orders(s, client)
        self.assertEqual(out["review"][0]["candidates"], [])
        self.assertEqual(out["unmatched"][0]["reason"], "no Odoo MO")

    def test_ignored_orders_are_excluded(self):
        client = FakeChainClient([])
        class Q:
            def filter(self, *a, **k):
                return self
            def order_by(self, *a):
                return self
            def all(self):
                return []
        s = SimpleNamespace(query=lambda *a, **k: Q())
        self.assertEqual(reconcile.suggest_unlinked_orders(s, client)["orders"], 0)

    def test_spec_matches_tolerances(self):
        order = SimpleNamespace(diameter=7.72, length=108, pd=325)
        self.assertTrue(reconcile._spec_matches(order, {"spec": {"diameter": 7.72, "length": 108.0, "pd": 325.0, "cu": 0}}))
        self.assertFalse(reconcile._spec_matches(order, {"spec": {"diameter": 6.03, "length": 108.0, "pd": 380.0, "cu": 0}}))


class ChainBatchingTests(unittest.TestCase):
    def test_chain_rows_batches_uom_reads(self):
        mos = []
        uoms = [(36, "1000pcs"), (42, "100pcs")]
        for i in range(1, 51):
            m = mo(i, f"WH/MO/{i:05d}", "F058", "done", 7, 0, 10, ["2026-05-01", "2026-05-02"], "7.72*108 PD325 0Cu")
            m["product_uom_id"] = list(uoms[i % 2])
            mos.append(m)
        client = FakeChainClient(mos)
        chains = reconcile._chain_rows(client)
        self.assertEqual(client.uom_ratio_calls, 1)
        self.assertEqual(client.fetched_uom_ids, {36, 42})
        self.assertEqual(len(chains), 1)
        total = next(iter(chains.values()))["total_rods"]
        self.assertEqual(total, 50 * 10 * 1000.0)


class RankChainsTests(unittest.TestCase):
    def _chains(self):
        # 120 chains named WH/MO/00001.., the exact Source match sits far past index 100.
        chains = {}
        for i in range(1, 121):
            chains[i] = {"root_id": i, "root_name": f"WH/MO/{i:05d}", "keys": {"name": f"wh/mo/{i:05d}"}}
        chains[900] = {"root_id": 900, "root_name": "WH/MO/00191-001",
                       "keys": {"origin": "h082", "name": "wh/mo/00191-001"}}
        return chains

    def test_exact_source_match_is_first_and_survives_limit(self):
        out = reconcile.rank_chains(self._chains(), "H082", 5)
        self.assertEqual([c["root_id"] for c in out], [900])

    def test_exact_match_ranked_before_partial_matches(self):
        chains = self._chains()
        chains[901] = {"root_id": 901, "root_name": "WH/MO/00200", "keys": {"origin": "h082-extra"}}
        out = reconcile.rank_chains(chains, "h082", 10)
        self.assertEqual([c["root_id"] for c in out], [900, 901])

    def test_no_query_returns_limited_list_sorted_by_name(self):
        out = reconcile.rank_chains(self._chains(), "", 3)
        self.assertEqual([c["root_name"] for c in out],
                         ["WH/MO/00001", "WH/MO/00002", "WH/MO/00003"])


class AttachSuggestionsTests(unittest.TestCase):
    def _cand(self, root_id):
        return {"root_id": root_id, "root_name": f"WH/MO/{root_id:05d}-001",
                "matched_on": "code:source", "risk": [], "qty_mismatch": None}

    def test_unlinked_rows_get_capped_suggestions_and_linked_rows_none(self):
        rows = [
            {"id": 1, "po_number": "H085", "odoo_mo_id": None},
            {"id": 2, "po_number": "H082", "odoo_mo_id": 501},
            {"id": 3, "po_number": "H086", "odoo_mo_id": None},
        ]
        review = [
            {"local_mo_id": 1, "candidates": [self._cand(i) for i in range(5)]},
            {"local_mo_id": 2, "candidates": [self._cand(9)]},
        ]
        out = reconcile.attach_suggestions(rows, review, per_order=3)
        self.assertEqual(len(out[0]["suggestions"]), 3)
        self.assertEqual(out[0]["suggestions"][0]["root_id"], 0)   # order preserved
        self.assertEqual(out[1]["suggestions"], [])                # linked: never suggested
        self.assertEqual(out[2]["suggestions"], [])                # no candidates

    def test_input_rows_are_not_mutated(self):
        rows = [{"id": 1, "po_number": "H085", "odoo_mo_id": None}]
        reconcile.attach_suggestions(rows, [{"local_mo_id": 1, "candidates": [self._cand(1)]}])
        self.assertNotIn("suggestions", rows[0])


class FieldSchemaTests(unittest.TestCase):
    def test_mrp_production_field_lists_use_product_uom_id(self):
        from app.services.odoo import inbound, reconcile
        for fields in (inbound.MO_LINK_FIELDS, reconcile.MO_CHAIN_FIELDS):
            self.assertIn("product_uom_id", fields)
            self.assertNotIn("product_uom", fields)  # invalid on mrp.production in Odoo 18


if __name__ == "__main__":
    unittest.main()
