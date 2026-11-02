import asyncio
import unittest

from starlette.requests import Request
from starlette.responses import Response

from app import require_auth_reads
from app import auth
from tests.db_support import DbTestCase


class PublicPathTests(unittest.TestCase):
    def test_static_and_spa_paths_are_public(self):
        for path in ("/", "/main.dart.js", "/flutter_assets/x", "/icons/Icon.png",
                     "/admin", "/admin/users/list", "/docs", "/openapi.json"):
            self.assertTrue(require_auth_reads.is_public_api(path), path)

    def test_self_authenticating_api_paths_are_public(self):
        for path in ("/api/auth/login", "/api/version",
                     "/api/v2/odoo/mo-event", "/api/v2/odoo/mo-recall",
                     "/api/v2/odoo/order-summary-pdf", "/api/v2/quality/ingest"):
            self.assertTrue(require_auth_reads.is_public_api(path), path)

    def test_regular_api_paths_are_protected(self):
        for path in ("/api/reports", "/api/v2/shifts", "/api/v2/dashboard/summary",
                     "/api/purchase-orders", "/api/v2/quality"):
            self.assertFalse(require_auth_reads.is_public_api(path), path)

    def test_env_flag_parsing(self):
        self.assertFalse(require_auth_reads.enabled())


def _make_request(path: str, headers=None) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": path,
        "raw_path": path.encode("latin-1"), "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "scheme": "http", "server": ("test", 80), "client": ("test", 80),
        "root_path": "",
    })


class RequireAuthReadsHttpTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.mw = require_auth_reads.RequireAuthReadsMiddleware(lambda *a: None)

    def _dispatch(self, path, headers=None):
        request = _make_request(path, headers)

        async def call_next(req):
            return Response("ok", status_code=200)

        return asyncio.run(self.mw.dispatch(request, call_next))

    def test_no_token_is_401(self):
        self.assertEqual(self._dispatch("/api/protected").status_code, 401)

    def test_public_path_passes_without_token(self):
        self.assertEqual(self._dispatch("/api/auth/login").status_code, 200)

    def test_invalid_token_is_401(self):
        resp = self._dispatch("/api/protected", {"Authorization": "Bearer bogus.token"})
        self.assertEqual(resp.status_code, 401)

    def test_valid_bearer_token_passes(self):
        token = auth.create_access_token(self.user.id)
        resp = self._dispatch("/api/protected", {"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.body, b"ok")

    def test_unknown_user_token_is_401(self):
        token = auth.create_access_token(999999999)  # no such user
        resp = self._dispatch("/api/protected", {"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()

