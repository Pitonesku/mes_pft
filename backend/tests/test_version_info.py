"""Version info: software version constant + /api/version response shape."""

import unittest

from app import version as version_mod
from tests.db_support import DbTestCase


class VersionConstantTests(unittest.TestCase):
    def test_software_version_is_set_and_semver_like(self):
        parts = version_mod.SOFTWARE_VERSION.split(".")
        self.assertEqual(len(parts), 3, version_mod.SOFTWARE_VERSION)
        self.assertTrue(all(p.isdigit() for p in parts), version_mod.SOFTWARE_VERSION)


class VersionEndpointTests(DbTestCase):
    def test_get_data_version_shape(self):
        from app import main as main_mod

        payload = main_mod.get_data_version(db=self.db)
        self.assertEqual(payload["app_version"], version_mod.SOFTWARE_VERSION)
        self.assertEqual(payload["data_version"], payload["version"])
        self.assertTrue(payload["version"].startswith("v_"))


if __name__ == "__main__":
    unittest.main()
