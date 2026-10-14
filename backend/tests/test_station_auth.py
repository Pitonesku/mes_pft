"""Tests for station API key authentication (pure, no DB)."""

import unittest
from unittest import mock

from fastapi import HTTPException

from app.auth import _hash_station_key, _resolve_station_key


class _FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._row


class _FakeSession:
    """Minimal session double: returns a fixed row per model name."""

    def __init__(self, key_row=None, user=None):
        self._key_row = key_row
        self._user = user

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "StationKey":
            return _FakeQuery(self._key_row)
        return _FakeQuery(self._user)

    def commit(self):
        pass


class _KeyRow:
    def __init__(self, user_id, last_used_at=None):
        self.user_id = user_id
        self.is_active = True
        self.last_used_at = last_used_at


class StationAuthTest(unittest.TestCase):
    def test_hash_key_is_sha256_hex(self):
        self.assertEqual(len(_hash_station_key("abc")), 64)
        self.assertEqual(_hash_station_key("abc"), _hash_station_key("abc"))
        self.assertNotEqual(_hash_station_key("abc"), _hash_station_key("abd"))

    def test_unknown_key_raises_401(self):
        with self.assertRaises(HTTPException) as ctx:
            _resolve_station_key(_FakeSession(key_row=None), "nope")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_key_returns_user(self):
        user = mock.Mock()
        session = _FakeSession(key_row=_KeyRow(user_id=7), user=user)
        self.assertIs(_resolve_station_key(session, "good"), user)

    def test_key_without_user_raises_403(self):
        with self.assertRaises(HTTPException) as ctx:
            _resolve_station_key(_FakeSession(key_row=_KeyRow(user_id=None)), "good")
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
