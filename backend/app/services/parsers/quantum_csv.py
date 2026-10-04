"""
Parser for Quantum Neo quality-station CSV output files.

Ported from Data_Bridge/src/Data_Bridge.py ``process_csv`` (the Tkinter/watchdog
daemon). This module keeps only the pure parsing logic and drops the GUI, the
watchdog observer, the SQLite writer and pandas.

File format (see Data_Bridge/measurements/Archive/*.csv):

* The first ``data_start_row`` lines are ``key ,value`` metadata rows.
* The rod table starts at ``data_start_row`` and has a header line plus a units
  line, then one row per rod. The instrument also prints Mean/Min/Max/SD/CofV
  footer rows which we ignore (they are recomputed in quality_stats.py).
* Numeric columns use comma as the decimal separator in some files; we normalize
  both comma and dot.

The column indexes and metadata mapping mirror Data_Bridge/src/config.ini and
can be overridden via the constructor for other station firmware versions.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence

# Mirrors [METADATA_MAP] from Data_Bridge/src/config.ini (csv key -> field).
DEFAULT_METADATA_MAP: Dict[str, str] = {
    "instrument_id": "Instrument ID",
    "maker": "Maker",
    "team": "Team",
    "shift": "Shift",
    "sample_id": "Sample ID",
    "operator": "Operator",
    "brand": "Brand",
    "produced_on": "Produced On",
    "batch_start": "Batch Started On",
    "batch_end": "Batch Ended On",
    "rods_count": "Measured Rods",
    "reserve_1": "Comments",
    "reserve_2": "Batch Description",
}

# Mirrors [COLUMNS] from Data_Bridge/src/config.ini (column index -> field).
DEFAULT_COLUMN_MAP: Dict[str, Optional[int]] = {
    "rod_no": 0,
    "pd": 1,
    "weight": 2,
    "diameter": 3,
    "ovality": 4,
    "roundness": 5,
    "shape": 6,
}

DEFAULT_DATA_START_ROW = 18
# Date formats tried in order for the metadata timestamps.
_DATE_FORMATS = ("%d/%m/%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")


@dataclass
class Rod:
    """One measured filter rod."""

    rod_no: Optional[int]
    pd: Optional[float]
    weight: Optional[float]
    diameter: Optional[float]
    ovality: Optional[float]
    roundness: Optional[float]
    shape: Optional[float]
    hardness: Optional[float] = None

    def as_dict(self) -> Dict[str, Optional[float]]:
        return {
            "rod_no": self.rod_no,
            "pd": self.pd,
            "weight": self.weight,
            "diameter": self.diameter,
            "ovality": self.ovality,
            "roundness": self.roundness,
            "shape": self.shape,
            "hardness": self.hardness,
        }


@dataclass
class ParsedSample:
    """Result of parsing one station output file."""

    instrument_id: str
    maker: str
    team: str
    shift: str
    sample_id: str
    operator: str
    brand: str
    produced_on: Optional[datetime]
    batch_start: Optional[datetime]
    batch_end: Optional[datetime]
    rods_count: Optional[int]
    reserve_1: str
    reserve_2: str
    rods: List[Rod] = field(default_factory=list)
    footer: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    file_sha256: Optional[str] = None
    file_md5: Optional[str] = None

    @property
    def mo_ref(self) -> str:
        """The 'Manufacturing Order' value comes from Batch Description or Comments."""
        return (self.reserve_2 or "").strip() or (self.reserve_1 or "").strip()


def _to_number(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    text = str(raw).strip().replace("\u00a0", " ").replace(" ", "")
    if text in ("", "-", "n/a", "nan", "NaN"):
        return None
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(raw: Optional[str]) -> Optional[int]:
    value = _to_number(raw)
    return None if value is None else int(value)


def _parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


class QuantumCsvParser:
    """Parse a Quantum Neo CSV file into a ParsedSample."""

    def __init__(
        self,
        metadata_map: Optional[Dict[str, str]] = None,
        column_map: Optional[Dict[str, Optional[int]]] = None,
        data_start_row: int = DEFAULT_DATA_START_ROW,
        encoding: str = "utf-8",
    ) -> None:
        self.metadata_map = metadata_map or dict(DEFAULT_METADATA_MAP)
        self.column_map = column_map or dict(DEFAULT_COLUMN_MAP)
        self.data_start_row = data_start_row
        self.encoding = encoding

    def parse(self, content: str) -> ParsedSample:
        """Parse CSV text (already decoded)."""
        lines = content.splitlines()

        raw_meta: Dict[str, str] = {}
        for line in lines[: self.data_start_row]:
            if not line.strip():
                continue
            try:
                key, value = next(csv.reader([line], skipinitialspace=True))[:2]
            except (StopIteration, ValueError):
                continue
            raw_meta[str(key).strip()] = str(value).strip()

        meta = {
            field_name: raw_meta.get(csv_key, "")
            for field_name, csv_key in self.metadata_map.items()
        }

        # Rod table: everything from data_start_row onward, parsed line-by-line.
        # Rows whose first cell is not numeric (the header row, the units row and
        # the Mean/Min/Max/SD/CofV footer) are ignored.
        rods: List[Rod] = []
        for line in lines[self.data_start_row :]:
            if not line.strip():
                continue
            try:
                row = next(csv.reader([line], skipinitialspace=True))
            except StopIteration:
                continue
            first = row[0].strip() if row else ""
            if _to_number(first) is None:
                continue
            rods.append(self._row_to_rod(row))

        return ParsedSample(
            instrument_id=meta.get("instrument_id", ""),
            maker=meta.get("maker", ""),
            team=meta.get("team", ""),
            shift=meta.get("shift", ""),
            sample_id=meta.get("sample_id", ""),
            operator=meta.get("operator", ""),
            brand=meta.get("brand", ""),
            produced_on=_parse_date(meta.get("produced_on")),
            batch_start=_parse_date(meta.get("batch_start")),
            batch_end=_parse_date(meta.get("batch_end")),
            rods_count=_to_int(meta.get("rods_count")),
            reserve_1=meta.get("reserve_1", ""),
            reserve_2=meta.get("reserve_2", ""),
            rods=rods,
        )

    def _row_to_rod(self, row: Sequence[str]) -> Rod:
        def cell(index: Optional[int]) -> Optional[str]:
            if index is None or index >= len(row):
                return None
            return row[index]

        return Rod(
            rod_no=_to_int(cell(self.column_map.get("rod_no"))),
            pd=_to_number(cell(self.column_map.get("pd"))),
            weight=_to_number(cell(self.column_map.get("weight"))),
            diameter=_to_number(cell(self.column_map.get("diameter"))),
            ovality=_to_number(cell(self.column_map.get("ovality"))),
            roundness=_to_number(cell(self.column_map.get("roundness"))),
            shape=_to_number(cell(self.column_map.get("shape"))),
            hardness=None,
        )


def parse_bytes(data: bytes, encoding: str = "utf-8") -> ParsedSample:
    """Decode raw file bytes and parse; falls back to cp1251 like the old daemon."""
    parser = QuantumCsvParser(encoding=encoding)
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        text = data.decode("cp1251")
    return parser.parse(text)
