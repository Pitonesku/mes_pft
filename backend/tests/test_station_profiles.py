"""Tests for per-station parser profile helpers (pure, no DB)."""

import unittest
from types import SimpleNamespace

from app.services.parsers.profiles import profile_to_parser_kwargs


class ProfileToParserKwargsTest(unittest.TestCase):
    def test_none_profile(self):
        self.assertEqual(profile_to_parser_kwargs(None), {})

    def test_full_profile(self):
        profile = SimpleNamespace(
            data_start_row=22,
            encoding="cp1251",
            metadata_map={"brand": "Article"},
            column_map={"rod_no": 0, "weight": None, "pd": 1},
            mo_field="brand",
        )
        kwargs = profile_to_parser_kwargs(profile)
        self.assertEqual(kwargs["data_start_row"], 22)
        self.assertEqual(kwargs["encoding"], "cp1251")
        self.assertEqual(kwargs["metadata_map"], {"brand": "Article"})
        self.assertEqual(kwargs["column_map"]["weight"], None)
        self.assertEqual(kwargs["mo_field"], "brand")

    def test_partial_profile_skips_unset(self):
        profile = SimpleNamespace(
            data_start_row=None,
            encoding=None,
            metadata_map=None,
            column_map=None,
            mo_field=None,
        )
        self.assertEqual(profile_to_parser_kwargs(profile), {})


if __name__ == "__main__":
    unittest.main()
