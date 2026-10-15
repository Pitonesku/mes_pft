// lib/core/csv_column_mapper.dart
// Pure helpers: map a rod-table CSV header row to {parameter -> column index}.
// No dart:html / Flutter imports, so it stays unit-testable.

const _columnAliases = <String, List<String>>{
  'rod_no': ['rod', 'rodno', 'rodnumber', 'no', 'rodnum'],
  'pd': ['pd', 'pressuredrop', 'mmwg', 'mmwg'],
  'weight': ['weight', 'wt', 'grams', 'gram', 'mass'],
  'diameter': ['diameter', 'sizel', 'size', 'diam'],
  'ovality': ['ovality', 'oval'],
  'roundness': ['roundness', 'round'],
  'shape': ['shape'],
  'hardness': ['hardness', 'hard'],
  'length': ['length', 'len'],
};

String _norm(String s) =>
    s.trim().toLowerCase().replaceAll(RegExp(r'[^a-z0-9 ]'), '').trim();

/// Map a list of header cell strings to `{parameter: columnIndex}`.
Map<String, int> mapHeaderToColumns(List<String> headerCells) {
  final result = <String, int>{};
  final normalized = headerCells.map(_norm).toList();
  for (var i = 0; i < normalized.length; i++) {
    final name = normalized[i];
    if (name.isEmpty) continue;
    for (final e in _columnAliases.entries) {
      if (e.value.contains(name)) {
        result[e.key] = i;
        break;
      }
    }
  }
  return result;
}

/// Find the rod-table header row index in raw CSV text.
///
/// Uses [dataStartRow] as a hint (the Quantum Neo convention puts the header at
/// ``data_start_row``); falls back to scanning the first 40 lines for a row that
/// contains a ``Rod`` / ``PD`` cell.
int? findHeaderRow(String csvText, int? dataStartRow) {
  final lines = csvText.split(RegExp(r'\r?\n'));
  if (dataStartRow != null && dataStartRow >= 0 && dataStartRow < lines.length) {
    return dataStartRow;
  }
  for (var i = 0; i < lines.length && i < 40; i++) {
    final cells = lines[i].split(',').map(_norm).toList();
    if (cells.any((c) => c == 'rod' || c == 'pd' || c == 'rodno' || c == 'rodnum')) {
      return i;
    }
  }
  return null;
}
