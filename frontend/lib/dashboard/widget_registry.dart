// lib/dashboard/widget_registry.dart
import 'package:flutter/material.dart';

import 'dashboard_data.dart';
import 'dashboard_layout.dart';
import 'widgets/active_orders_widget.dart';
import 'widgets/kpi_tile_widget.dart';
import 'widgets/machine_widget.dart';
import 'widgets/recent_reports_widget.dart';

class DashboardWidgetMeta {
  final String type;
  final String title;
  final IconData icon;
  final int defaultW;
  final int defaultH;
  final bool configurable;
  final Widget Function(BuildContext, Map<String, dynamic>, DashboardData)
      builder;

  const DashboardWidgetMeta({
    required this.type,
    required this.title,
    required this.icon,
    this.defaultW = 2,
    this.defaultH = 1,
    this.configurable = false,
    required this.builder,
  });
}

final Map<String, DashboardWidgetMeta> dashboardWidgetRegistry = {
  'machine': DashboardWidgetMeta(
    type: 'machine',
    title: 'Machine Live Status',
    icon: Icons.precision_manufacturing,
    defaultW: 12,
    defaultH: 2,
    configurable: true,
    builder: (ctx, cfg, data) => MachineWidget(config: cfg, data: data),
  ),
  'orders': DashboardWidgetMeta(
    type: 'orders',
    title: 'Active Orders',
    icon: Icons.receipt_long,
    defaultW: 12,
    defaultH: 2,
    builder: (ctx, cfg, data) => ActiveOrdersWidget(data: data),
  ),
  'kpi': DashboardWidgetMeta(
    type: 'kpi',
    title: 'KPI Metric',
    icon: Icons.insights,
    defaultW: 6,
    defaultH: 1,
    configurable: true,
    builder: (ctx, cfg, data) => KpiTileWidget(config: cfg, data: data),
  ),
  'recent_reports': DashboardWidgetMeta(
    type: 'recent_reports',
    title: 'Recent Shift Reports',
    icon: Icons.table_chart,
    defaultW: 24,
    defaultH: 3,
    builder: (ctx, cfg, data) => RecentReportsWidget(reports: data.recentReports),
  ),
};
