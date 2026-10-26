// lib/dashboard/quality/quality_parameter.dart
// Parameter catalog shared by the Quality Monitor widgets and config dialogs.
// Keys match the backend parameter names exactly (pd, diameter, weight,
// hardness, length) so no mapping layer is needed.
import 'package:flutter/material.dart';

class QualityParameter {
  final String key; // backend key: pd, diameter, weight, hardness, length
  final String label; // human-readable name
  final String short; // compact abbreviation for KPI headers
  final String unit; // display unit for live values
  final int decimals; // default decimals for live display
  final Color color; // chart line color

  const QualityParameter({
    required this.key,
    required this.label,
    required this.short,
    required this.unit,
    required this.decimals,
    required this.color,
  });
}

const List<QualityParameter> qualityParameters = [
  QualityParameter(
      key: 'diameter',
      label: 'Diameter',
      short: 'DIA',
      unit: 'mm',
      decimals: 2,
      color: Colors.teal),
  QualityParameter(
      key: 'pd',
      label: 'Pressure Drop',
      short: 'PD',
      unit: 'mm WG',
      decimals: 0,
      color: Colors.blue),
  QualityParameter(
      key: 'weight',
      label: 'Weight',
      short: 'WT',
      unit: 'g',
      decimals: 3,
      color: Colors.orange),
  QualityParameter(
      key: 'hardness',
      label: 'Hardness',
      short: 'HARD',
      unit: '%',
      decimals: 1,
      color: Colors.purple),
  QualityParameter(
      key: 'length',
      label: 'Length',
      short: 'LEN',
      unit: 'mm',
      decimals: 0,
      color: Colors.green),
];

QualityParameter qualityParameterByKey(String key) => qualityParameters.firstWhere(
      (p) => p.key == key,
      orElse: () => const QualityParameter(
          key: 'pd',
          label: 'Pressure Drop',
          short: 'PD',
          unit: 'mm WG',
          decimals: 0,
          color: Colors.blue),
    );

/// Resolved display formatting for one parameter: the scale factor applied to
/// backend measurement values, the display unit, and the decimal precision.
/// Weight is toggleable between grams (measurement unit) and milligrams.
class QualityDisplay {
  final double scale;
  final String unit;
  final int decimals;

  const QualityDisplay({
    required this.scale,
    required this.unit,
    required this.decimals,
  });
}

QualityDisplay qualityDisplayFor(String key, {String? weightUnit}) {
  switch (key) {
    case 'pd':
      return const QualityDisplay(scale: 1, unit: 'mm WG', decimals: 0);
    case 'diameter':
      return const QualityDisplay(scale: 1, unit: 'mm', decimals: 2);
    case 'length':
      return const QualityDisplay(scale: 1, unit: 'mm', decimals: 0);
    case 'hardness':
      return const QualityDisplay(scale: 1, unit: '%', decimals: 1);
    case 'weight':
      final mg = weightUnit == 'mg';
      return QualityDisplay(
          scale: mg ? 1000 : 1, unit: mg ? 'mg' : 'g', decimals: mg ? 0 : 3);
    default:
      return const QualityDisplay(scale: 1, unit: '', decimals: 2);
  }
}