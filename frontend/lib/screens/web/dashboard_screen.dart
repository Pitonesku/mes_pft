// lib/screens/web/dashboard_screen.dart
// Modular, customizable widget dashboard with drag/resize edit mode.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api_service.dart';
import '../../dashboard/dashboard_data.dart';
import '../../dashboard/dashboard_edit_grid.dart';
import '../../dashboard/dashboard_grid.dart';
import '../../dashboard/dashboard_layout.dart';
import '../../dashboard/widget_config_dialogs.dart';
import '../../dashboard/widget_registry.dart';
import '../../models.dart';

class DashboardScreen extends StatefulWidget {
  final User user;
  const DashboardScreen({super.key, required this.user});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  DashboardLayout _layout = DashboardLayout.defaultLayout();
  bool _editMode = false;
  bool _loadingLayout = true;
  Map<String, dynamic>? _summary;
  List<Map<String, dynamic>> _recentReports = [];
  List<String> _machineAliases = ['M1', 'M2'];
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _loadLayout();
    _loadData();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) => _loadData());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _loadLayout() async {
    final layout = await DashboardLayoutStore.load(widget.user.name);
    if (!mounted) return;
    setState(() {
      _layout = layout;
      _loadingLayout = false;
    });
  }

  Future<void> _loadData() async {
    final summary = await ApiService.fetchDashboardSummary();
    final machines = await ApiService.fetchMachines();
    final now = DateTime.now();
    final start = now.subtract(const Duration(days: 30));
    final reports = (await ApiService.fetchReports(
            startDate: start, endDate: now) ??
        [])
        .cast<Map<String, dynamic>>();
    if (!mounted) return;

    final aliases = <String>[];
    for (final m in (machines ?? const [])) {
      if (m is Map && m['is_inactive'] != true) {
        final name = m['name']?.toString();
        if (name != null && name.isNotEmpty) aliases.add(name);
      }
    }

    setState(() {
      _summary = summary;
      _recentReports = reports.take(8).toList();
      if (aliases.isNotEmpty) _machineAliases = aliases;
    });
  }

  Future<void> _saveLayout() async {
    await DashboardLayoutStore.save(widget.user.name, _layout);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Dashboard layout saved')),
    );
  }

  Future<void> _resetLayout() async {
    await DashboardLayoutStore.reset(widget.user.name);
    if (!mounted) return;
    setState(() => _layout = DashboardLayout.defaultLayout());
    await _saveLayout();
  }

  void _toggleEdit() {
    if (_editMode) _saveLayout();
    setState(() => _editMode = !_editMode);
  }

  void _move(String id, int x, int y) {
    setState(() {
      final idx = _layout.items.indexWhere((i) => i.id == id);
      if (idx != -1) {
        _layout.items[idx] = _layout.items[idx].copyWith(x: x, y: y);
      }
      _resolveOverlaps();
    });
  }

  void _remove(String id) {
    setState(() => _layout.items.removeWhere((i) => i.id == id));
  }

  void _resize(String id, int w, int h) {
    setState(() {
      final idx = _layout.items.indexWhere((i) => i.id == id);
      if (idx != -1) {
        _layout.items[idx] = _layout.items[idx].copyWith(w: w, h: h);
      }
      _resolveOverlaps();
    });
  }

  void _addWidget(String type, Map<String, dynamic> config) {
    final meta = dashboardWidgetRegistry[type];
    if (meta == null) return;
    final cell = _firstFreeCell(meta.defaultW, meta.defaultH);
    setState(() {
      _layout.items.add(DashboardItem(
        id: 'w${DateTime.now().microsecondsSinceEpoch}',
        type: type,
        config: config,
        x: cell.$1,
        y: cell.$2,
        w: meta.defaultW,
        h: meta.defaultH,
      ));
    });
  }

  /// Finds the first (row-major) free cell large enough for a [w]×[h] widget,
  /// so newly added widgets never overlap existing ones.
  (int, int) _firstFreeCell(int w, int h) {
    final columns = _layout.columns;
    final occupied = <(int, int)>{};
    for (final it in _layout.items) {
      for (var dx = 0; dx < it.w; dx++) {
        for (var dy = 0; dy < it.h; dy++) {
          occupied.add((it.x + dx, it.y + dy));
        }
      }
    }
    for (var y = 0; ; y++) {
      for (var x = 0; x + w <= columns; x++) {
        var fits = true;
        for (var dx = 0; dx < w && fits; dx++) {
          for (var dy = 0; dy < h && fits; dy++) {
            if (occupied.contains((x + dx, y + dy))) {
              fits = false;
              break;
            }
          }
        }
        if (fits) return (x, y);
      }
    }
  }

  bool _overlaps(DashboardItem a, DashboardItem b) {
    final ax2 = a.x + a.w;
    final ay2 = a.y + a.h;
    final bx2 = b.x + b.w;
    final by2 = b.y + b.h;
    return a.x < bx2 && b.x < ax2 && a.y < by2 && b.y < ay2;
  }

  /// Resolves overlaps by pushing the lower widget below the upper one
  /// (item.y = blocking.y + blocking.h). Repeats until nothing intersects.
  void _resolveOverlaps() {
    final items = _layout.items;
    for (var pass = 0; pass < items.length * items.length + 1; pass++) {
      var moved = false;
      for (var i = 0; i < items.length; i++) {
        for (var j = i + 1; j < items.length; j++) {
          final a = items[i];
          final b = items[j];
          if (!_overlaps(a, b)) continue;
          final lowerIdx = a.y >= b.y ? i : j;
          final upper = a.y >= b.y ? b : a;
          final lower = items[lowerIdx];
          final newY = upper.y + upper.h;
          if (newY != lower.y) {
            items[lowerIdx] = lower.copyWith(y: newY);
            moved = true;
          }
        }
      }
      if (!moved) break;
    }
  }

  DashboardData get _data => DashboardData(
        summary: _summary,
        recentReports: _recentReports,
        user: widget.user,
      );

  Widget _buildItem(BuildContext context, DashboardItem item) {
    final meta = dashboardWidgetRegistry[item.type];
    if (meta == null) {
      return Card(
        margin: EdgeInsets.zero,
        child: Center(child: Text('Unknown widget: ${item.type}')),
      );
    }
    return meta.builder(context, item.config, _data);
  }

  String _titleFor(String type) => dashboardWidgetRegistry[type]?.title ?? type;

  bool _configurableFor(String type) =>
      dashboardWidgetRegistry[type]?.configurable ?? false;

  @override
  Widget build(BuildContext context) {
    if (_loadingLayout) {
      return const Center(child: CircularProgressIndicator());
    }
    final columns = _columnsFor(context);
    return Column(children: [
      _header(),
      const Divider(height: 1),
      Expanded(
        child: RefreshIndicator(
          onRefresh: _loadData,
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Welcome, ${widget.user.name}',
                    style: const TextStyle(
                        fontSize: 22, fontWeight: FontWeight.w600)),
                Text(DateFormat('EEEE, d MMMM yyyy').format(DateTime.now()),
                    style: TextStyle(fontSize: 13, color: Colors.grey[600])),
                const SizedBox(height: 24),
                _editMode
                    ? DashboardEditGrid(
                        items: _layout.items,
                        columns: columns,
                        buildItem: _buildItem,
                        titleFor: _titleFor,
                        configurableFor: _configurableFor,
                        onMove: _move,
                        onRemove: _remove,
                        onResize: _resize,
                        onConfigure: _openConfigureDialog,
                      )
                    : DashboardGrid(
                        items: _layout.items,
                        columns: columns,
                        buildItem: _buildItem),
              ],
            ),
          ),
        ),
      ),
    ]);
  }

  int _columnsFor(BuildContext context) => kColumns;

  Widget _header() => Container(
        color: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
        child: Row(children: [
          Icon(_editMode ? Icons.edit_note : Icons.dashboard,
              size: 20, color: Colors.deepPurple),
          const SizedBox(width: 8),
          Text(_editMode ? 'Editing dashboard' : 'Dashboard',
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
          const Spacer(),
          if (_editMode) ...[
            OutlinedButton.icon(
              onPressed: _resetLayout,
              icon: const Icon(Icons.restart_alt, size: 16),
              label: const Text('Reset'),
            ),
            const SizedBox(width: 8),
            FilledButton.icon(
              onPressed: _showAddWidget,
              icon: const Icon(Icons.add, size: 16),
              label: const Text('Add Widget'),
            ),
            const SizedBox(width: 8),
          ],
          FilledButton.tonalIcon(
            onPressed: _toggleEdit,
            icon: Icon(_editMode ? Icons.check : Icons.settings, size: 16),
            label: Text(_editMode ? 'Done' : 'Edit Dashboard'),
          ),
        ]),
      );

  void _showAddWidget() {
    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('Add Widget',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            ),
            for (final meta in dashboardWidgetRegistry.values)
              ListTile(
                leading: Icon(meta.icon, color: Colors.deepPurple),
                title: Text(meta.title),
                subtitle: Text('${meta.defaultW}×${meta.defaultH}'),
                onTap: () {
                  Navigator.pop(ctx);
                  if (meta.configurable) {
                    _openConfigDialogForNew(meta);
                  } else {
                    _addWidget(meta.type, const {});
                  }
                },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _openConfigDialogForNew(DashboardWidgetMeta meta) async {
    final config = await promptWidgetConfig(
        context, meta.type, const {}, _machineAliases);
    if (config == null) return;
    _addWidget(meta.type, config);
  }

  Future<void> _openConfigureDialog(DashboardItem item) async {
    final config = await promptWidgetConfig(
        context, item.type, item.config, _machineAliases);
    if (config == null) return;
    setState(() {
      final idx = _layout.items.indexWhere((i) => i.id == item.id);
      if (idx != -1) {
        _layout.items[idx] = _layout.items[idx].copyWith(config: config);
      }
    });
  }
}

