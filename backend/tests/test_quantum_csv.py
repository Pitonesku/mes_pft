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

    def test_mo_field_brand(self):
        sample = parse_bytes(_SAMPLE.read_bytes(), mo_field="brand")
        self.assertEqual(sample.mo_ref, "7.75x108 PD300 porosus")

    def test_mo_field_default_uses_batch_description_then_comments(self):
        # The sample has empty Batch Description and Comments, so mo_ref is empty.
        self.assertEqual(self.sample.mo_ref, "")

    def test_custom_column_map_can_omit_weight(self):
        from app.services.parsers.quantum_csv import QuantumCsvParser

        content = (
            "Instrument ID           ,X\n"
            "Produced On             ,06/05/2026 09:00:00\n"
            "\n"
            "Rod# ,PD,SizeL\n"
            "     , (mmWg),(mm)\n"
            "1    , 300, 7.70\n"
        ).encode("utf-8")
        sample = QuantumCsvParser(
            data_start_row=3,
            column_map={"rod_no": 0, "pd": 1, "diameter": 2},
        ).parse(content.decode("utf-8"))
        self.assertEqual(len(sample.rods), 1)
        self.assertEqual(sample.rods[0].pd, 300.0)
        self.assertIsNone(sample.rods[0].weight)
        self.assertAlmostEqual(sample.rods[0].diameter, 7.70)


class StationExtendedColumnTest(unittest.TestCase):
    """Length (core parameter) and custom field parsing."""

    def _content(self, header, units, *rows):
        meta = (
            "Instrument ID           ,X\n"
            "Produced On             ,06/05/2026 09:00:00\n"
            "\n"
        )
        body = header + "\n" + units + "\n" + "\n".join(rows) + "\n"
        return (meta + body).encode("utf-8")

    def test_length_and_hardness_parsed_from_default_columns(self):
        from app.services.parsers.quantum_csv import QuantumCsvParser

        content = self._content(
            "Rod# ,PD,Weight,SizeL,Ovality,Roundness,Shape,Hardness,Length",
            "     , (mmWg),(g),(mm),(mm),(mm),(mm),(%),(mm)",
            "1    , 322, 0.664, 7.74, 0.10, 0.20, 0.30, 84, 108.2",
        )
        sample = QuantumCsvParser(data_start_row=3).parse(content.decode("utf-8"))
        self.assertEqual(len(sample.rods), 1)
        self.assertAlmostEqual(sample.rods[0].hardness, 84.0)
        self.assertAlmostEqual(sample.rods[0].length, 108.2)

    def test_custom_fields_parsed_into_extra(self):
        from app.services.parsers.quantum_csv import QuantumCsvParser

        content = self._content(
            "Rod# ,PD,Weight,SizeL,ID",
            "     , (mmWg),(g),(mm),(mm)",
            "1    , 322, 0.664, 7.74, 5.35",
        )
        sample = QuantumCsvParser(
            data_start_row=3,
            custom_fields=[{"label": "Inner Diameter", "unit": "mm", "index": 4}],
        ).parse(content.decode("utf-8"))
        self.assertEqual(len(sample.rods), 1)
        self.assertAlmostEqual(sample.rods[0].extra["Inner Diameter"], 5.35)


class ComputeCustomMetricsTest(unittest.TestCase):
    def test_aggregates_custom_fields_mean_sd(self):
        from types import SimpleNamespace

        from app.services.parsers.profiles import compute_custom_metrics

        rods = [
            SimpleNamespace(extra={"Inner Diameter": 5.30}),
            SimpleNamespace(extra={"Inner Diameter": 5.40}),
            SimpleNamespace(extra={}),
        ]
        sample = SimpleNamespace(rods=rods)
        profile = SimpleNamespace(
            custom_fields=[{"label": "Inner Diameter", "unit": "mm", "index": 9}]
        )
        out = compute_custom_metrics(sample, profile)
        self.assertIn("Inner Diameter", out)
        self.assertAlmostEqual(out["Inner Diameter"]["mean"], 5.35)
        self.assertEqual(out["Inner Diameter"]["n"], 2)
        self.assertEqual(out["Inner Diameter"]["unit"], "mm")

    def test_no_custom_fields_returns_none(self):
        from types import SimpleNamespace

        from app.services.parsers.profiles import compute_custom_metrics

        self.assertIsNone(compute_custom_metrics(SimpleNamespace(rods=[]), None))


if __name__ == "__main__":
    unittest.main()
