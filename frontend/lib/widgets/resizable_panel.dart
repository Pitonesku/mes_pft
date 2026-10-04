// lib/widgets/resizable_panel.dart
// A horizontal split view where the right panel can be resized by dragging
// the divider between the main content and the side panel.
import 'package:flutter/material.dart';

class ResizablePanelLayout extends StatefulWidget {
  /// The main (left) content — takes all remaining space.
  final Widget main;

  /// The side (right) panel widget.
  final Widget panel;

  /// Initial width of the side panel in logical pixels.
  final double initialPanelWidth;

  /// Minimum allowed panel width.
  final double minPanelWidth;

  /// Maximum allowed panel width.
  final double maxPanelWidth;

  const ResizablePanelLayout({
    super.key,
    required this.main,
    required this.panel,
    this.initialPanelWidth = 400,
    this.minPanelWidth = 280,
    this.maxPanelWidth = 800,
  });

  @override
  State<ResizablePanelLayout> createState() => _ResizablePanelLayoutState();
}

class _ResizablePanelLayoutState extends State<ResizablePanelLayout> {
  late double _panelWidth;

  @override
  void initState() {
    super.initState();
    _panelWidth = widget.initialPanelWidth;
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        // ── Main content ────────────────────────────────────────────────
        Expanded(child: widget.main),

        // ── Draggable divider ────────────────────────────────────────────
        MouseRegion(
          cursor: SystemMouseCursors.resizeColumn,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onHorizontalDragUpdate: (details) {
              setState(() {
                _panelWidth = (_panelWidth - details.delta.dx)
                    .clamp(widget.minPanelWidth, widget.maxPanelWidth);
              });
            },
            child: Container(
              width: 6,
              color: Colors.transparent,
              child: Center(
                child: Container(
                  width: 2,
                  color: Colors.grey.shade300,
                ),
              ),
            ),
          ),
        ),

        // ── Side panel ───────────────────────────────────────────────────
        SizedBox(
          width: _panelWidth,
          child: widget.panel,
        ),
      ],
    );
  }
}
