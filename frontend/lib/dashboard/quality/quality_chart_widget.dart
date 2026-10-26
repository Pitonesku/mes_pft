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
      formatValue: (v) => v.toStringAsFixed(display.decimals),
      valueScale: display.scale,
      unitLabel: display.unit,
      yMin: _num(config['yMin']),
      yMax: _num(config['yMax']),
    );
  }

  double? _num(dynamic v) =>
      v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));
}