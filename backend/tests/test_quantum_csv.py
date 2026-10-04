"""Tests for the Quantum Neo CSV parser (ported from Data_Bridge)."""

import pathlib
import unittest

from app.services.parsers.quantum_csv import parse_bytes

# A real sample file from the quality station, shipped in the repo for tests.
_SAMPLE = pathlib.Path(__file__).resolve().parent / "sample_20260506-091100.csv"


@unittest.skipUnless(_SAMPLE.is_file(), "sample CSV not present")
class QuantumCsvParserTest(unittest.TestCase):
    def setUp(self):
        self.sample = parse_bytes(_SAMPLE.read_bytes())

    def test_metadata(self):
        self.assertEqual(self.sample.instrument_id, "102248")
        self.assertEqual(self.sample.maker, "2")
        self.assertEqual(self.sample.team, "M2")
        self.assertEqual(self.sample.shift, "B")
        self.assertEqual(self.sample.sample_id, "D046")

    def test_produced_on_is_parsed(self):
        self.assertEqual(self.sample.produced_on.strftime("%Y-%m-%d %H:%M:%S"), "2026-05-06 09:12:57")

    def test_rod_count_matches(self):
        self.assertEqual(len(self.sample.rods), 10)
        self.assertEqual(self.sample.rods_count, 10)

    def test_first_and_last_rod_values(self):
        self.assertEqual(self.sample.rods[0].pd, 293.0)
        self.assertEqual(self.sample.rods[-1].pd, 296.0)
        self.assertAlmostEqual(self.sample.rods[0].diameter, 7.75)

    def test_inline_minimal_file(self):
        # A minimal inline file (dot decimals, comma-delimited like the real files).
        content = (
            "Instrument ID           ,102248\n"
            "Maker                   ,1\n"
            "Produced On             ,06/05/2026 09:00:00\n"
            "\n"
            "Rod# ,PD,Weight,SizeL\n"
            "     , (mmWg),(g),(mm)\n"
            "1    , 322, 0.664, 7.74\n"
        ).encode("utf-8")
        from app.services.parsers.quantum_csv import QuantumCsvParser

        sample = QuantumCsvParser(data_start_row=4).parse(content.decode("utf-8"))
        self.assertEqual(len(sample.rods), 1)
        self.assertEqual(sample.rods[0].pd, 322.0)
        self.assertAlmostEqual(sample.rods[0].weight, 0.664)
        self.assertAlmostEqual(sample.rods[0].diameter, 7.74)


if __name__ == "__main__":
    unittest.main()
