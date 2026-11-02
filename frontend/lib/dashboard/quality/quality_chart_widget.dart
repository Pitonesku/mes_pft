// lib/dashboard/quality/quality_chart_widget.dart
// A Quality Monitor widget wrapping the reusable control chart for a single
// parameter. The chart fills its container (see QualityControlChart), so it
// redraws to whatever cell size the operator assigns.
import 'package:flutter/material.dart';

import '../../widgets/quality_control_chart.dart';
import 'quality_data.dart';
import 'quality_parameter.dart';

class QualityChartWidget extends StatelessWidget {
  final Map<String, dynamic> config;
  final QualityMonitorData data;

  const QualityChartWidget({super.key, required this.config, required this.data});

  @override
  Widget build(BuildContext context) {
    final param = qualityParameterByKey(config['parameter']?.toString() ?? 'pd');
    final display =
        qualityDisplayFor(param.key, weightUnit: config['unit']?.toString());
    return QualityControlChart(
      title: param.label,
      parameter: param.key,
      lineColor: param.color,
      series: data.series,
      // Chart tooltip decimals match the Quality Control page charts.
      formatValue: (v) => v.toStringAsFixed(_chartDecimals(param.key)),
      valueScale: display.scale,
      unitLabel: display.unit,
      yMin: _num(config['yMin']),
      yMax: _num(config['yMax']),
    );
  }

  int _chartDecimals(String key) => switch (key) {
        'pd' => 1,
        'diameter' => 3,
        'weight' => 3,
        'hardness' => 1,
        'length' => 0,
        'triacetin' => 2,
        _ => 2,
      };

  double? _num(dynamic v) =>
      v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));
}