// lib/dashboard/dashboard_grid.dart
import 'package:flutter/material.dart';

import 'dashboard_layout.dart';

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
  final double gap;
  final Widget Function(BuildContext context, DashboardItem item) buildItem;

  const DashboardGrid({
    super.key,
    required this.items,
    required this.columns,
    this.gap = 16,
    required this.buildItem,
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
          child: buildItem(context, item),
        ));
      }

      return SizedBox(
        height: height,
        width: double.infinity,
        child: Stack(children: children),
      );
    });
  }

}
