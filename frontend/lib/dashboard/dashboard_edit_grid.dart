// lib/dashboard/dashboard_edit_grid.dart
// Edit mode: header-strip drag for free placement (snapped to grid cells),
// corner-handle drag to resize, remove and configure. Coordinate-based — no
// auto-packing; empty cells remain blank.
import 'package:flutter/material.dart';

import 'dashboard_data.dart';
import 'dashboard_grid.dart';
import 'dashboard_layout.dart';
import 'widget_registry.dart';

class DashboardEditGrid extends StatefulWidget {
  final List<DashboardItem> items;
  final int columns;
  final DashboardData data;
  final double gap;
  final void Function(String id, int x, int y) onMove;
  final void Function(String id) onRemove;
  final void Function(String id, int w, int h) onResize;
  final void Function(DashboardItem item) onConfigure;

  const DashboardEditGrid({
    super.key,
    required this.items,
    required this.columns,
    required this.data,
    this.gap = 16,
    required this.onMove,
    required this.onRemove,
    required this.onResize,
    required this.onConfigure,
  });

  @override
  State<DashboardEditGrid> createState() => _DashboardEditGridState();
}

class _DashboardEditGridState extends State<DashboardEditGrid> {
  _HoverCell? _hover;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (ctx, constraints) {
      final cellW =
          (constraints.maxWidth - (widget.columns - 1) * widget.gap) / widget.columns;
      final cellH = kCellHeight;
      final height = gridHeight(widget.items, widget.gap);

      return DragTarget<DashboardItem>(
        onWillAcceptWithDetails: (_) => true,
        onMove: (d) => _onHover(d, cellW, cellH),
        onAcceptWithDetails: (d) => _onDrop(d, cellW, cellH),
        onLeave: (_) => setState(() => _hover = null),
        builder: (ctx, candidate, rejected) => SizedBox(
          height: height,
          width: double.infinity,
          child: Stack(children: [
            for (final item in widget.items) _place(item, cellW, cellH),
            if (_hover != null) _placeholder(cellW, cellH),
          ]),
        ),
      );
    });
  }

  Widget _place(DashboardItem item, double cellW, double cellH) {
    final w = item.w.clamp(1, widget.columns).toInt();
    final x = item.x.clamp(0, widget.columns - w).toInt();
    return Positioned(
      left: x * (cellW + widget.gap),
      top: item.y * (cellH + widget.gap),
      width: w * cellW + (w - 1) * widget.gap,
      height: item.h * cellH + (item.h - 1) * widget.gap,
      child: _EditCell(
        key: ValueKey(item.id),
        item: item,
        data: widget.data,
        columns: widget.columns,
        cellW: cellW,
        cellH: cellH,
        gap: widget.gap,
        onRemove: () => widget.onRemove(item.id),
        onResize: (w, h) => widget.onResize(item.id, w, h),
        onConfigure: () => widget.onConfigure(item),
      ),
    );
  }

  Widget _placeholder(double cellW, double cellH) {
    final h = _hover!;
    return Positioned(
      left: h.x * (cellW + widget.gap),
      top: h.y * (cellH + widget.gap),
      width: h.w * cellW + (h.w - 1) * widget.gap,
      height: h.h * cellH + (h.h - 1) * widget.gap,
      child: Container(
        decoration: BoxDecoration(
          color: Colors.blue.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.blue, width: 2),
        ),
      ),
    );
  }

  void _onHover(DragTargetDetails<DashboardItem> d, double cellW, double cellH) {
    final item = d.data;
    final w = item.w.clamp(1, widget.columns).toInt();
    final x = (d.offset.dx / (cellW + widget.gap))
        .floor()
        .clamp(0, widget.columns - w)
        .toInt();
    final y = (d.offset.dy / (cellH + widget.gap)).floor().clamp(0, 100000).toInt();
    setState(() => _hover = _HoverCell(x, y, w, item.h));
  }

  void _onDrop(DragTargetDetails<DashboardItem> d, double cellW, double cellH) {
    final item = d.data;
    final w = item.w.clamp(1, widget.columns).toInt();
    final x = (d.offset.dx / (cellW + widget.gap))
        .floor()
        .clamp(0, widget.columns - w)
        .toInt();
    final y = (d.offset.dy / (cellH + widget.gap)).floor().clamp(0, 100000).toInt();
    setState(() => _hover = null);
    widget.onMove(item.id, x, y);
  }
}

class _HoverCell {
  final int x;
  final int y;
  final int w;
  final int h;
  const _HoverCell(this.x, this.y, this.w, this.h);
}

class _EditCell extends StatefulWidget {
  final DashboardItem item;
  final DashboardData data;
  final int columns;
  final double cellW;
  final double cellH;
  final double gap;
  final VoidCallback onRemove;
  final void Function(int w, int h) onResize;
  final VoidCallback onConfigure;

  const _EditCell({
    super.key,
    required this.item,
    required this.data,
    required this.columns,
    required this.cellW,
    required this.cellH,
    required this.gap,
    required this.onRemove,
    required this.onResize,
    required this.onConfigure,
  });

  @override
  State<_EditCell> createState() => _EditCellState();
}

class _EditCellState extends State<_EditCell> {
  double _accumDx = 0;
  double _accumDy = 0;
  int? _startW;
  int? _startH;

  @override
  Widget build(BuildContext context) {
    final meta = dashboardWidgetRegistry[widget.item.type];
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.deepPurple.shade200, width: 2),
      ),
      child: Stack(children: [
        Positioned.fill(child: _content(context)),
        _header(context, meta),
        _resizeHandle(),
      ]),
    );
  }

  Widget _content(BuildContext context) {
    final meta = dashboardWidgetRegistry[widget.item.type];
    if (meta == null) {
      return const Center(child: Text('Unknown widget'));
    }
    return Padding(
      padding: const EdgeInsets.only(top: 28),
      child: meta.builder(context, widget.item.config, widget.data),
    );
  }

  Widget _header(BuildContext context, DashboardWidgetMeta? meta) => Positioned(
        top: 0,
        left: 0,
        right: 0,
        height: 28,
        child: Container(
          decoration: BoxDecoration(
            color: Colors.deepPurple.withValues(alpha: 0.06),
            border: Border(
                bottom: BorderSide(color: Colors.deepPurple.shade100, width: 1)),
          ),
          child: Row(children: [
            Expanded(
              child: Draggable<DashboardItem>(
                data: widget.item,
                feedback: _feedback(meta),
                childWhenDragging:
                    Opacity(opacity: 0.35, child: _headerGrip(meta)),
                child: MouseRegion(
                  cursor: SystemMouseCursors.grab,
                  child: _headerGrip(meta),
                ),
              ),
            ),
            if (meta?.configurable == true)
              _control(Icons.tune, 'Configure', widget.onConfigure),
            _control(Icons.close, 'Remove', widget.onRemove),
          ]),
        ),
      );

  Widget _headerGrip(DashboardWidgetMeta? meta) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10),
        child: Row(children: [
          const Icon(Icons.drag_indicator, size: 14, color: Colors.deepPurple),
          const SizedBox(width: 6),
          Expanded(
            child: Text(meta?.title ?? widget.item.type,
                style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: Colors.deepPurple),
                overflow: TextOverflow.ellipsis),
          ),
          Text('${widget.item.w}×${widget.item.h}',
              style:
                  TextStyle(fontSize: 10, color: Colors.deepPurple.shade400)),
        ]),
      );

  Widget _resizeHandle() => Positioned(
        bottom: 0,
        right: 0,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onPanStart: (_) {
            _startW = widget.item.w;
            _startH = widget.item.h;
            _accumDx = 0;
            _accumDy = 0;
          },
          onPanUpdate: (d) {
            if (_startW == null || _startH == null) return;
            _accumDx += d.delta.dx;
            _accumDy += d.delta.dy;
            final wStep = widget.cellW + widget.gap;
            final hStep = widget.cellH + widget.gap;
            final nw = (_startW! + (_accumDx / wStep).round())
                .clamp(kMinWidgetWidth, widget.columns)
                .toInt();
            final rawH = _startH! + (_accumDy / hStep).round();
            final nh = rawH < 1 ? 1 : rawH;
            widget.onResize(nw, nh);
          },
          onPanEnd: (_) => _startW = _startH = null,
          onPanCancel: () => _startW = _startH = null,
          child: MouseRegion(
            cursor: SystemMouseCursors.resizeUpLeftDownRight,
            child: Container(
              width: 22,
              height: 22,
              decoration: BoxDecoration(
                color: Colors.deepPurple.shade50,
                borderRadius:
                    const BorderRadius.only(topLeft: Radius.circular(8)),
                border: Border.all(color: Colors.deepPurple.shade200),
              ),
              child: const Icon(Icons.open_in_full,
                  size: 13, color: Colors.deepPurple),
            ),
          ),
        ),
      );

  Widget _feedback(DashboardWidgetMeta? meta) => Material(
        elevation: 8,
        color: Colors.transparent,
        child: Container(
          width: 220,
          height: 46,
          decoration: BoxDecoration(
              color: Colors.deepPurple,
              borderRadius: BorderRadius.circular(8)),
          child: Center(
            child: Text(meta?.title ?? widget.item.type,
                style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                    fontSize: 12)),
          ),
        ),
      );

  Widget _control(IconData icon, String tooltip, VoidCallback onTap) => Padding(
        padding: const EdgeInsets.only(left: 2),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(6),
            child: Tooltip(
              message: tooltip,
              child: Padding(
                padding: const EdgeInsets.all(6),
                child: Icon(icon, size: 15, color: Colors.deepPurple),
              ),
            ),
          ),
        ),
      );
}
