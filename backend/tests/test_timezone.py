"""Timezone handling: plant-local -> UTC conversion (station ingest correctness)."""

import unittest
from datetime import datetime, timezone
from unittest import mock

from app import config


class PlantTimezoneTests(unittest.TestCase):
    def test_default_plant_timezone_is_budapest(self):
        self.assertEqual(str(config.get_plant_timezone()), "Europe/Budapest")

    def test_local_to_utc_summer(self):
        # 13 Oct 2026 is CEST (UTC+2): 18:11 local -> 16:11 UTC.
        local = datetime(2026, 10, 13, 18, 11, 43)
        self.assertEqual(
            config.local_to_utc(local),
            datetime(2026, 10, 13, 16, 11, 43, tzinfo=timezone.utc),
        )

    def test_local_to_utc_winter(self):
        # 1 Jan 2026 is CET (UTC+1): 12:00 local -> 11:00 UTC.
        local = datetime(2026, 1, 1, 12, 0, 0)
        self.assertEqual(
            config.local_to_utc(local),
            datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
        )

    def test_local_to_utc_already_aware(self):
        aware = datetime(2026, 10, 13, 16, 11, 43, tzinfo=timezone.utc)
        self.assertEqual(config.local_to_utc(aware), aware)

    def test_local_to_utc_none(self):
        self.assertIsNone(config.local_to_utc(None))

    def test_env_override(self):
        with mock.patch.dict("os.environ", {"MES_PLANT_TIMEZONE": "UTC"}):
            self.assertEqual(str(config.get_plant_timezone()), "UTC")


if __name__ == "__main__":
    unittest.main()
