// lib/dashboard/dashboard_grid.dart
import 'package:flutter/material.dart';

import 'dashboard_data.dart';
import 'dashboard_layout.dart';
import 'widget_registry.dart';

/// Fixed height of a single grid row (px). The cell *width* is fluid (derived
/// from the 24-column container width), so rows stay 120px while columns flex.
const double kCellHeight = 120.0;

/// Total canvas height (px) for the given items (max y+h).
double gridHeight(List<DashboardItem> items, double gap) {
  final cellH = kCellHeight;
  var maxRow = 0;
  for (final it in items) {
    final end = it.y + it.h;
    if (end > maxRow) maxRow = end;
  }
  return maxRow * (cellH + gap) - gap;
}

/// Static (non-edit) coordinate-based dashboard grid.
class DashboardGrid extends StatelessWidget {
  final List<DashboardItem> items;
  final int columns;
  final DashboardData data;
  final double gap;

  const DashboardGrid({
    super.key,
    required this.items,
    required this.columns,
    required this.data,
    this.gap = 16,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (ctx, constraints) {
      final cellW = (constraints.maxWidth - (columns - 1) * gap) / columns;
      final cellH = kCellHeight;
      final height = gridHeight(items, gap);

      final children = <Widget>[];
      for (final item in items) {
        final w = item.w.clamp(1, columns).toInt();
        final x = item.x.clamp(0, columns - w).toInt();
        children.add(Positioned(
          left: x * (cellW + gap),
          top: item.y * (cellH + gap),
          width: w * cellW + (w - 1) * gap,
          height: item.h * cellH + (item.h - 1) * gap,
          child: _build(context, item),
        ));
      }

      return SizedBox(
        height: height,
        width: double.infinity,
        child: Stack(children: children),
      );
    });
  }

  Widget _build(BuildContext context, DashboardItem item) {
    final meta = dashboardWidgetRegistry[item.type];
    if (meta == null) {
      return Card(
        margin: EdgeInsets.zero,
        child: Center(child: Text('Unknown widget: ${item.type}')),
      );
    }
    return meta.builder(context, item.config, data);
  }
}
