"""'Entire PO' must ignore stale shift filters (CSV export came back empty)."""

import unittest

from app import v2_routes


class PoWindowFilterTests(unittest.TestCase):
    def test_po_window_drops_shift_filters(self):
        out = v2_routes._po_window_filters("po", 27, 135, 9, "2026-08-04", "Shift 1")
        self.assertEqual(out, (None, None, None, None))

    def test_po_window_without_po_keeps_filters(self):
        out = v2_routes._po_window_filters("po", None, 135, None, None, None)
        self.assertEqual(out, (135, None, None, None))

    def test_other_windows_keep_shift_filters(self):
        for window in ("rods", "shift", "all"):
            out = v2_routes._po_window_filters(window, 27, 135, None, None, None)
            self.assertEqual(out, (135, None, None, None))


if __name__ == "__main__":
    unittest.main()
