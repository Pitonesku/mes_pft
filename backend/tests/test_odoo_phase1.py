"""Phase 1 tests: material mapping, sync_mode/cutover guard, report gating.

Pure fakes only (no DB, no Odoo). Run from backend/:
    python -m unittest tests.test_odoo_phase1 -v
"""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app import models
from app.services.odoo import mapping, outbound


class FakeSession:
    """Minimal Session stand-in: .get(model, key) and .commit()."""

    def __init__(self, objects=None):
        self.objects = objects or {}
        self.commits = 0

    def get(self, model, key):
        return self.objects.get((model, key))

    def add(self, obj):
        key = getattr(obj, "key", getattr(obj, "id", None))
        self.objects[(type(obj), key)] = obj

    def commit(self):
        self.commits += 1

    def query(self, *a, **k):  # pragma: no cover - guard against accidental use
        raise AssertionError("unexpected query()")


def material(mid, category, name, odoo_id=None):
    return SimpleNamespace(
        id=mid, category=category, type_name=name, odoo_product_id=odoo_id,
        odoo_uom_id=None, source="local", is_hidden=False,
    )


class ScoreMatchTests(unittest.TestCase):
    def test_identical_after_normalization(self):
        self.assertEqual(mapping.score_match("Cerdia 4.0Y30000 (560kg)", "cerdia 4.0y30000"), 1.0)

    def test_unrelated_is_low(self):
        self.assertLess(mapping.score_match("Cerdia 4.0Y30000", "Tipping paper 32gsm"), 0.3)

    def test_empty_is_zero(self):
        self.assertEqual(mapping.score_match("", "anything"), 0.0)


class SuggestTests(unittest.TestCase):
    PRODUCTS = [
        {"id": 11, "display_name": "Acetate tow Cerdia 4.0Y30000", "uom_id": [3, "kg"]},
        {"id": 12, "display_name": "Plug wrap paper 25gsm", "uom_id": [4, "m"]},
        {"id": 13, "display_name": "Cardboard box", "uom_id": [1, "Pcs"]},
    ]

    def test_suggests_same_category_only(self):
        m = material(1, "acetate", "Cerdia 4.0Y30000")
        out = mapping.suggest_for_material(m, self.PRODUCTS)
        self.assertEqual([s["odoo_product_id"] for s in out], [11])
        self.assertEqual(out[0]["uom_id"], 3)

    def test_nothing_applied_by_suggestion(self):
        m = material(1, "acetate", "Cerdia 4.0Y30000")
        mapping.suggest_for_material(m, self.PRODUCTS)
        self.assertIsNone(m.odoo_product_id)


class ConfirmMappingTests(unittest.TestCase):
    def _session(self, *materials):
        return FakeSession({(models.MaterialDictionary, m.id): m for m in materials})

    def test_confirm_sets_link_and_commits(self):
        m = material(1, "acetate", "X")
        s = self._session(m)
        # confirm_mapping runs a clash query; emulate "no clash" via a stub.
        s.query = lambda *a, **k: SimpleNamespace(
            filter=lambda *x, **y: SimpleNamespace(first=lambda: None))
        out = mapping.confirm_mapping(s, 1, 11, 3)
        self.assertEqual(m.odoo_product_id, 11)
        self.assertEqual(m.odoo_uom_id, 3)
        self.assertEqual(m.source, "odoo")
        self.assertEqual(out["odoo_product_id"], 11)
        self.assertEqual(s.commits, 1)

    def test_overwrite_requires_force(self):
        m = material(1, "acetate", "X", odoo_id=5)
        s = self._session(m)
        with self.assertRaises(ValueError):
            mapping.confirm_mapping(s, 1, 11)
        self.assertEqual(m.odoo_product_id, 5)

    def test_unlink_requires_force(self):
        m = material(1, "acetate", "X", odoo_id=5)
        s = self._session(m)
        with self.assertRaises(ValueError):
            mapping.confirm_mapping(s, 1, None)
        mapping.confirm_mapping(s, 1, None, force=True)
        self.assertIsNone(m.odoo_product_id)

    def test_unknown_material(self):
        with self.assertRaises(ValueError):
            mapping.confirm_mapping(self._session(), 99, 1)


class CutoverTests(unittest.TestCase):
    def _session(self, date):
        setting = SimpleNamespace(value={"date": date})
        return FakeSession({(models.SystemSetting, "odoo_sync_from_date"): setting})

    def _run(self, started):
        return SimpleNamespace(started_at=started)

    def test_no_cutover_means_not_before(self):
        s = FakeSession()
        self.assertFalse(outbound._before_cutover(s, self._run(datetime(2020, 1, 1, tzinfo=timezone.utc))))

    def test_run_before_cutover(self):
        s = self._session("2026-10-01")
        self.assertTrue(outbound._before_cutover(s, self._run(datetime(2026, 9, 30, tzinfo=timezone.utc))))

    def test_run_after_cutover(self):
        s = self._session("2026-10-01")
        self.assertFalse(outbound._before_cutover(s, self._run(datetime(2026, 10, 2, tzinfo=timezone.utc))))

    def test_invalid_date_is_ignored(self):
        s = self._session("not-a-date")
        self.assertFalse(outbound._before_cutover(s, self._run(datetime(2020, 1, 1, tzinfo=timezone.utc))))


class LinkedReportGateTests(unittest.TestCase):
    def _case(self, status, rods=1000):
        report = SimpleNamespace(id=7, verification_status=status, produced_rods=rods)
        run = SimpleNamespace(report_id=7)
        return FakeSession({(models.ProductionReport, 7): report}), run

    def test_approved_returns_rods(self):
        s, run = self._case("approved", 4200)
        self.assertEqual(outbound.verified_produced_rods(s, run), 4200)

    def test_pending_waits(self):
        s, run = self._case("pending")
        with self.assertRaises(outbound.AwaitingVerification):
            outbound.verified_produced_rods(s, run)

    def test_rejected_waits(self):
        s, run = self._case("rejected")
        with self.assertRaises(outbound.AwaitingVerification):
            outbound.verified_produced_rods(s, run)


class MappingEngineV2Tests(unittest.TestCase):
    """Real-data cases from the audit (see docs/odoo-integration.md)."""

    PRODUCTS = [
        {"id": 11, "display_name": "Cerdia Acetate Tow 3,0Y30000HK (560kg)", "uom_id": [3, "kg"]},
        {"id": 12, "display_name": "Cerdia Acetate Tow 8,0Y40000HK (513kg)", "uom_id": [3, "kg"]},
        {"id": 13, "display_name": "Paper 27mm / 6000m HP PWP 6000CU", "uom_id": [4, "Bob"]},
        {"id": 14, "display_name": "Paper 27mm / 5000m HP PWP 6000CU", "uom_id": [4, "Bob"]},
        {"id": 15, "display_name": "[HP PWP] TOBACOLL 5067-1 Cold Glue 25 kg", "uom_id": [3, "kg"]},
        {"id": 16, "display_name": "TOBACOLL Q 2237 Hot Melt Glue 20kg", "uom_id": [3, "kg"]},
        {"id": 17, "display_name": "del", "uom_id": [1, "Pcs"]},
    ]

    def test_acetate_grade_ignores_hk_and_weight(self):
        m = material(1, "acetate", "Cerdia 3.0Y30000")
        out = mapping.suggest_for_material(m, self.PRODUCTS)
        self.assertEqual(out[0]["odoo_product_id"], 11)
        self.assertEqual(out[0]["score"], 1.0)

    def test_acetate_without_matching_grade_gets_nothing(self):
        m = material(1, "acetate", "Cerdia 8.0Y28000")
        self.assertEqual(mapping.suggest_for_material(m, self.PRODUCTS), [])

    def test_junk_product_never_suggests(self):
        m = material(2, "paper", "Delfort 21.5mm/6000m")
        ids = [s["odoo_product_id"] for s in mapping.suggest_for_material(m, self.PRODUCTS)]
        self.assertNotIn(17, ids)  # 'del' must never rank

    def test_paper_width_length_ranking(self):
        m = material(2, "paper", "Delfort 27mm/6000m")
        out = mapping.suggest_for_material(m, self.PRODUCTS)
        scores = {s["odoo_product_id"]: s["score"] for s in out}
        self.assertEqual(scores.get(13), 1.0)   # exact width+length
        self.assertEqual(scores.get(14), 0.7)   # same width, other length
        self.assertNotIn(17, scores)

    def test_cold_glue_matches_by_code(self):
        m = material(3, "coldGlue", "Tobacoll 5067-1")
        out = mapping.suggest_for_material(m, self.PRODUCTS)
        self.assertEqual([s["odoo_product_id"] for s in out], [15])

    def test_hot_melt_matches_by_code(self):
        m = material(4, "hotMelt", "Tobacoll Q 2237")
        out = mapping.suggest_for_material(m, self.PRODUCTS)
        self.assertEqual([s["odoo_product_id"] for s in out], [16])

    def test_triacetin_has_no_name_match(self):
        m = material(5, "triacetin", "Gli Therm")
        self.assertEqual(mapping.suggest_for_material(m, self.PRODUCTS), [])

    def test_category_normalization(self):
        self.assertEqual(mapping._normalize_category("coldGlue"), "glue")
        self.assertEqual(mapping._normalize_category("hotMelt"), "glue")
        self.assertEqual(mapping._normalize_category("acetate"), "acetate")

    def test_paper_key_extraction(self):
        self.assertEqual(mapping._paper_key("Delfort 27mm/6000m"), ("27", "6000"))
        self.assertEqual(mapping._paper_key("Paper 27mm / 5000m HP PWP 6000CU"), ("27", "5000"))
        self.assertIsNone(mapping._paper_key("no size here"))


class ShadowSettingTests(unittest.TestCase):
    def _session(self, value=None, env_shadow=False):
        from unittest import mock
        s = FakeSession()
        if value is not None:
            s.objects[(models.SystemSetting, "odoo_shadow_mode")] = SimpleNamespace(value=value)
        patcher = mock.patch.dict(
            "os.environ", {"ODOO_SHADOW_MODE": "true" if env_shadow else ""}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return s

    def test_default_falls_back_to_env(self):
        self.assertTrue(outbound.shadow_enabled(self._session(env_shadow=True)))
        self.assertFalse(outbound.shadow_enabled(self._session(env_shadow=False)))

    def test_setting_overrides_env(self):
        s = self._session(value={"enabled": False}, env_shadow=True)
        self.assertFalse(outbound.shadow_enabled(s))

    def test_set_persists(self):
        s = FakeSession()
        outbound.set_shadow_enabled(s, False)
        row = s.objects[(models.SystemSetting, "odoo_shadow_mode")]
        self.assertEqual(row.value, {"enabled": False})
        self.assertEqual(s.commits, 1)


class DispatchTimingSettingsTests(unittest.TestCase):
    def _setting(self, key, value):
        return SimpleNamespace(value={"value": value})

    def test_defaults_when_unset(self):
        s = FakeSession()
        self.assertEqual(outbound.verification_wait_minutes(s), 10)
        self.assertEqual(outbound.error_retry_minutes(s), 5)
        self.assertEqual(outbound.max_attempts(s), 5)
        self.assertEqual(outbound.poll_seconds(s), 30)
        self.assertEqual(outbound.reconcile_minutes(s), 10)

    def test_overrides_are_read(self):
        s = FakeSession({
            (models.SystemSetting, outbound.VERIFY_WAIT_SETTING_KEY): self._setting(outbound.VERIFY_WAIT_SETTING_KEY, 2),
            (models.SystemSetting, outbound.ERROR_RETRY_SETTING_KEY): self._setting(outbound.ERROR_RETRY_SETTING_KEY, 1),
            (models.SystemSetting, outbound.MAX_ATTEMPTS_SETTING_KEY): self._setting(outbound.MAX_ATTEMPTS_SETTING_KEY, 3),
            (models.SystemSetting, outbound.POLL_SECONDS_SETTING_KEY): self._setting(outbound.POLL_SECONDS_SETTING_KEY, 15),
            (models.SystemSetting, outbound.RECONCILE_MINUTES_SETTING_KEY): self._setting(outbound.RECONCILE_MINUTES_SETTING_KEY, 20),
        })
        self.assertEqual(outbound.verification_wait_minutes(s), 2)
        self.assertEqual(outbound.error_retry_minutes(s), 1)
        self.assertEqual(outbound.max_attempts(s), 3)
        self.assertEqual(outbound.poll_seconds(s), 15)
        self.assertEqual(outbound.reconcile_minutes(s), 20)

    def test_invalid_and_minimum_clamp(self):
        s = FakeSession({
            (models.SystemSetting, outbound.VERIFY_WAIT_SETTING_KEY): self._setting(outbound.VERIFY_WAIT_SETTING_KEY, "abc"),
            (models.SystemSetting, outbound.POLL_SECONDS_SETTING_KEY): self._setting(outbound.POLL_SECONDS_SETTING_KEY, 0),
            (models.SystemSetting, outbound.MAX_ATTEMPTS_SETTING_KEY): self._setting(outbound.MAX_ATTEMPTS_SETTING_KEY, 0),
        })
        self.assertEqual(outbound.verification_wait_minutes(s), 10)  # invalid -> default
        self.assertEqual(outbound.poll_seconds(s), 1)  # clamped to minimum 1
        self.assertEqual(outbound.max_attempts(s), 1)  # clamped to minimum 1



if __name__ == "__main__":
    unittest.main()
