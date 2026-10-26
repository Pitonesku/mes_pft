// lib/dashboard/quality/quality_widget_registry.dart
// Widget registry for the Quality Monitor grid. Independent from the console
// dashboard registry; the shared grid engine resolves content via buildItem.
import 'package:flutter/material.dart';

import 'quality_chart_widget.dart';
import 'quality_data.dart';
import 'quality_kpi_widget.dart';

class QualityWidgetMeta {
  final String type;
  final String title;
  final IconData icon;
  final int defaultW;
  final int defaultH;
  final bool configurable;
  final Widget Function(BuildContext, Map<String, dynamic>, QualityMonitorData)
      builder;

  const QualityWidgetMeta({
    required this.type,
    required this.title,
    required this.icon,
    this.defaultW = 6,
    this.defaultH = 1,
    this.configurable = false,
    required this.builder,
  });
}

final Map<String, QualityWidgetMeta> qualityWidgetRegistry = {
  'quality_kpi': QualityWidgetMeta(
    type: 'quality_kpi',
    title: 'Quality KPI',
    icon: Icons.insights,
    defaultW: 6,
    defaultH: 1,
    configurable: true,
    builder: (ctx, cfg, data) => QualityKpiWidget(config: cfg, data: data),
  ),
  'quality_chart': QualityWidgetMeta(
    type: 'quality_chart',
    title: 'Control Chart',
    icon: Icons.show_chart,
    defaultW: 12,
    defaultH: 4,
    configurable: true,
    builder: (ctx, cfg, data) => QualityChartWidget(config: cfg, data: data),
  ),
};
