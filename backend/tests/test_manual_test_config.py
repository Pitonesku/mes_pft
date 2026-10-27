"""Tests for the pure per-machine manual test config module."""

import unittest

from app.services import manual_test_config as mtc


class DefaultConfigTests(unittest.TestCase):
    def test_all_visible_none_required_by_default(self):
        cfg = mtc.default_config()
        self.assertEqual(set(cfg), set(mtc.PARAMETER_KEYS))
        for flags in cfg.values():
            self.assertTrue(flags["is_visible"])
            self.assertFalse(flags["is_required"])

    def test_effective_merges_partial_over_defaults(self):
        cfg = mtc.effective_config({"weight": {"is_visible": False}})
        self.assertFalse(cfg["weight"]["is_visible"])
        self.assertFalse(cfg["weight"]["is_required"])
        self.assertTrue(cfg["length"]["is_visible"])

    def test_effective_ignores_unknown_keys_and_bad_types(self):
        cfg = mtc.effective_config({"bogus": {"is_visible": False}, "weight": "nope"})
        self.assertTrue(cfg["weight"]["is_visible"])
        self.assertNotIn("bogus", cfg)

    def test_sanitize_keeps_only_valid_booleans(self):
        clean = mtc.sanitize_config({
            "weight": {"is_visible": False, "is_required": True, "junk": 1},
            "nope": {"is_visible": True},
        })
        self.assertEqual(clean, {"weight": {"is_visible": False, "is_required": True}})

    def test_sanitize_none_is_empty(self):
        self.assertEqual(mtc.sanitize_config(None), {})


if __name__ == "__main__":
    unittest.main()
