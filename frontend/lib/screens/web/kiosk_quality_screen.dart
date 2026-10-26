// lib/screens/web/kiosk_quality_screen.dart
// Full-screen shop-floor Quality Monitor. No login required. The metric cards
// and control charts are arranged on the same customizable 24-column grid used
// by the web console dashboard; operators can toggle "Edit Dashboard" to add,
// remove, drag, resize and configure widgets (persisted per machine).
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api_service.dart';
import '../../dashboard/dashboard_edit_grid.dart';
import '../../dashboard/dashboard_grid.dart';
import '../../dashboard/dashboard_layout.dart';
import '../../dashboard/quality/quality_config_dialogs.dart';
import '../../dashboard/quality/quality_data.dart';
import '../../dashboard/quality/quality_widget_registry.dart';

class KioskQualityScreen extends StatefulWidget {
  final String initialMachine;
  const KioskQualityScreen({super.key, this.initialMachine = 'M1'});
  @override
  State<KioskQualityScreen> createState() => _KioskQualityScreenState();
}

class _KioskQualityScreenState extends State<KioskQualityScreen> {
  static const List<String> _machines = ['M1', 'M2'];
  late String _machine;
  String _windowType = 'rods';
  int _windowValue = 50;
  String _anchorMode = 'none';
  DateTime? _since;
  DateTime? _until;
  Map<String, dynamic>? _data;
  String? _error;
  Timer? _timer;

  DashboardLayout _layout = DashboardLayout.defaultQualityLayout();
  bool _editMode = false;
  bool _loadingLayout = true;

  @override
  void initState() {
    super.initState();
    _machine =
        _machines.contains(widget.initialMachine) ? widget.initialMachine : 'M1';
    _loadLayout();
    _load();
    _syncPolling();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _loadLayout() async {
    final layout = await QualityLayoutStore.load(_machine);
    if (!mounted) return;
    setState(() {
      _layout = layout;
      _loadingLayout = false;
    });
  }

  Future<void> _load() async {
    final data = await ApiService.fetchLiveQuality(_machine,
        windowType: _windowType, windowValue: _windowValue, since: _sinceValue, until: _untilValue);
    if (!mounted) return;
    setState(() {
      _data = data;
      _error = data == null ? 'No data from server' : null;
    });
  }

  void _applyWindow(String type, int value) {
    setState(() {
      _windowType = type;
      _windowValue = value;
    });
    _load();
  }

  void _applyMachine(String m) {
    setState(() {
      _machine = m;
      _data = null;
      _loadingLayout = true;
    });
    _loadLayout();
    _load();
  }

  String? get _sinceValue {
    if (_anchorMode == 'shift_start') return 'shift_start';
    if (_anchorMode == 'custom' && _since != null) {
      return _since!.toIso8601String();
    }
    return null;
  }

  String? get _untilValue {
    if (_anchorMode == 'custom' && _until != null) {
      return _until!.toIso8601String();
    }
    return null;
  }

  /// Live polling pauses while a fixed historical window (until) is selected.
  void _syncPolling() {
    if (_until != null) {
      _timer?.cancel();
      _timer = null;
    } else {
      _timer ??= Timer.periodic(const Duration(seconds: 20), (_) => _load());
    }
  }

  Future<void> _pickCustomRange() async {
    final result = await showDialog<(DateTime, DateTime?)>(
      context: context,
      builder: (_) => _CustomRangeDialog(
        initialFrom: _since ?? DateTime.now(),
        initialTo: _until,
      ),
    );
    if (result == null) return;
    setState(() {
      _anchorMode = 'custom';
      _since = result.$1;
      _until = result.$2;
    });
    _syncPolling();
    _load();
  }

  String _rangeLabel() {
    final f = DateFormat('dd MMM HH:mm');
    if (_anchorMode == 'custom' && _since != null) {
      final to = _until == null ? 'now' : f.format(_until!);
      return '${f.format(_since!)} → $to';
    }
    return '';
  }

  Future<void> _saveLayout() async {
    await QualityLayoutStore.save(_machine, _layout);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Dashboard layout saved')),
    );
  }

  Future<void> _resetLayout() async {
    await QualityLayoutStore.reset(_machine);
    if (!mounted) return;
    setState(() => _layout = DashboardLayout.defaultQualityLayout());
    await _saveLayout();
  }

  void _toggleEdit() {
    if (_editMode) _saveLayout();
    setState(() => _editMode = !_editMode);
  }

  void _move(String id, int x, int y) {
    setState(() {
      final idx = _layout.items.indexWhere((i) => i.id == id);
      if (idx != -1) _layout.items[idx] = _layout.items[idx].copyWith(x: x, y: y);
      _resolveOverlaps();
    });
  }

  void _remove(String id) {
    setState(() => _layout.items.removeWhere((i) => i.id == id));
  }

  void _resize(String id, int w, int h) {
    setState(() {
      final idx = _layout.items.indexWhere((i) => i.id == id);
      if (idx != -1) _layout.items[idx] = _layout.items[idx].copyWith(w: w, h: h);
      _resolveOverlaps();
    });
  }

  void _addWidget(String type, Map<String, dynamic> config) {
    final meta = qualityWidgetRegistry[type];
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
    for (var y = 0;; y++) {
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

  QualityMonitorData get _qdata => QualityMonitorData(live: _data);

  Widget _buildItem(BuildContext context, DashboardItem item) {
    final meta = qualityWidgetRegistry[item.type];
    if (meta == null) {
      return Container(
        decoration: BoxDecoration(
            color: const Color(0xFF1A1E2B),
            borderRadius: BorderRadius.circular(10)),
        child: Center(
            child: Text('Unknown widget: ${item.type}',
                style: const TextStyle(color: Colors.white54))),
      );
    }
    return meta.builder(context, item.config, _qdata);
  }

  String _titleFor(String type) => qualityWidgetRegistry[type]?.title ?? type;

  bool _configurableFor(String type) =>
      qualityWidgetRegistry[type]?.configurable ?? false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0E1017),
      body: SafeArea(
        child: Column(children: [
          _header(),
          const Divider(height: 1, color: Colors.white12),
          Expanded(child: _body()),
        ]),
      ),
    );
  }

  Widget _body() {
    if (_loadingLayout) {
      return const Center(child: CircularProgressIndicator(color: Colors.white));
    }
    if (_data == null) {
      return Center(
        child: _error != null
            ? Text(_error!, style: const TextStyle(color: Colors.white70, fontSize: 16))
            : const CircularProgressIndicator(color: Colors.white),
      );
    }
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: _editMode
          ? DashboardEditGrid(
              items: _layout.items,
              columns: _layout.columns,
              gap: 12,
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
              columns: _layout.columns,
              gap: 12,
              buildItem: _buildItem,
            ),
    );
  }

  Widget _header() {
    final activePo = _data?['active_po'];
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      child: Row(children: [
        const Icon(Icons.factory, color: Colors.deepPurpleAccent, size: 28),
        const SizedBox(width: 12),
        const Text('QUALITY MONITOR',
            style: TextStyle(
                color: Colors.white,
                fontSize: 22,
                fontWeight: FontWeight.bold,
                letterSpacing: 2)),
        const SizedBox(width: 20),
        _machineDropdown(),
        const SizedBox(width: 12),
        if (activePo != null) _badge('PO: $activePo', Colors.orange),
        const Spacer(),
        _anchorDropdown(),
        const SizedBox(width: 12),
        _windowButtons(),
        const SizedBox(width: 12),
        if (_editMode) ...[
          OutlinedButton.icon(
            onPressed: _resetLayout,
            style: OutlinedButton.styleFrom(
                foregroundColor: Colors.white,
                side: const BorderSide(color: Colors.white38)),
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
          icon: Icon(_editMode ? Icons.check : Icons.edit, size: 16),
          label: Text(_editMode ? 'Done' : 'Edit Dashboard'),
        ),
      ]),
    );
  }

  Widget _machineDropdown() => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
            color: Colors.white, borderRadius: BorderRadius.circular(8)),
        child: DropdownButton<String>(
          value: _machine,
          items: _machines
              .map((m) => DropdownMenuItem(
                  value: m,
                  child: Text(m,
                      style: const TextStyle(
                          fontSize: 16, fontWeight: FontWeight.bold))))
              .toList(),
          onChanged: (v) {
            if (v != null) _applyMachine(v);
          },
          underline: const SizedBox.shrink(),
        ),
      );

  Widget _badge(String text, Color color) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
            color: color.withValues(alpha: 0.2),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: color)),
        child: Text(text,
            style: TextStyle(
                color: color, fontSize: 15, fontWeight: FontWeight.bold)),
      );

  Widget _windowButtons() => Wrap(spacing: 8, children: [
        _windowChip('50 rods', 'rods', 50),
        _windowChip('100 rods', 'rods', 100),
      ]);

  Widget _anchorDropdown() => Row(children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
              color: Colors.white, borderRadius: BorderRadius.circular(8)),
          child: DropdownButton<String>(
            value: _anchorMode,
            items: const [
              DropdownMenuItem(value: 'none', child: Text('Live (last N)')),
              DropdownMenuItem(
                  value: 'shift_start', child: Text('Since shift start')),
              DropdownMenuItem(
                  value: 'custom', child: Text('Custom range…')),
            ],
            onChanged: (v) {
              if (v == null) return;
              if (v == 'custom') {
                _pickCustomRange();
                return;
              }
              setState(() {
                _anchorMode = v;
                _since = null;
                _until = null;
              });
              _syncPolling();
              _load();
            },
            underline: const SizedBox.shrink(),
          ),
        ),
        if (_anchorMode == 'custom' && _since != null) ...[
          const SizedBox(width: 8),
          Text(_rangeLabel(),
              style: const TextStyle(
                  color: Colors.white, fontSize: 13, fontWeight: FontWeight.bold)),
        ],
      ]);

  Widget _windowChip(String label, String type, int value) {
    final selected = _windowType == type && _windowValue == value;
    return ChoiceChip(
      label: Text(label,
          style: TextStyle(
              color: selected ? Colors.black : Colors.white,
              fontWeight: FontWeight.bold)),
      selected: selected,
      onSelected: (_) => _applyWindow(type, value),
      backgroundColor: const Color(0xFF1E2230),
      selectedColor: Colors.white,
      side: const BorderSide(color: Colors.white24),
      showCheckmark: false,
    );
  }

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
            for (final meta in qualityWidgetRegistry.values)
              ListTile(
                leading: Icon(meta.icon, color: Colors.deepPurple),
                title: Text(meta.title),
                subtitle: Text('${meta.defaultW}×${meta.defaultH}'),
                onTap: () {
                  Navigator.pop(ctx);
                  _openConfigDialogForNew(meta);
                },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _openConfigDialogForNew(QualityWidgetMeta meta) async {
    final config = await promptQualityWidgetConfig(context, meta.type, const {});
    if (config == null) return;
    _addWidget(meta.type, config);
  }

  Future<void> _openConfigureDialog(DashboardItem item) async {
    final config =
        await promptQualityWidgetConfig(context, item.type, item.config);
    if (config == null) return;
    setState(() {
      final idx = _layout.items.indexWhere((i) => i.id == item.id);
      if (idx != -1) _layout.items[idx] = _layout.items[idx].copyWith(config: config);
    });
  }
}

class _CustomRangeDialog extends StatefulWidget {
  final DateTime initialFrom;
  final DateTime? initialTo;
  const _CustomRangeDialog({required this.initialFrom, this.initialTo});
  @override
  State<_CustomRangeDialog> createState() => _CustomRangeDialogState();
}

class _CustomRangeDialogState extends State<_CustomRangeDialog> {
  late DateTime _from;
  DateTime? _to;

  @override
  void initState() {
    super.initState();
    _from = widget.initialFrom;
    _to = widget.initialTo;
  }

  Future<void> _pickFrom() async {
    final dt = await _pickDateTime(_from);
    if (dt != null) setState(() => _from = dt);
  }

  Future<void> _pickTo() async {
    final dt = await _pickDateTime(_to ?? _from);
    if (dt != null) setState(() => _to = dt);
  }

  Future<DateTime?> _pickDateTime(DateTime initial) async {
    final date = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (date == null || !mounted) return null;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(initial),
    );
    if (time == null) return null;
    return DateTime(date.year, date.month, date.day, time.hour, time.minute);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Custom time range'),
      content: SizedBox(
        width: 360,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _rangeRow('From', _from, _pickFrom, canClear: false),
            const SizedBox(height: 12),
            _rangeRow('To (optional)', _to, _pickTo,
                canClear: true, onClear: () => setState(() => _to = null)),
          ],
        ),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel')),
        FilledButton(
            onPressed: () => Navigator.pop(context, (_from, _to)),
            child: const Text('Apply')),
      ],
    );
  }

  Widget _rangeRow(String label, DateTime? value, VoidCallback onPick,
      {required bool canClear, VoidCallback? onClear}) {
    final fmt = DateFormat('yyyy-MM-dd HH:mm');
    return Row(children: [
      SizedBox(
          width: 90,
          child: Text(label,
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
      Expanded(
        child: OutlinedButton.icon(
          onPressed: onPick,
          icon: const Icon(Icons.event, size: 16),
          label: Text(value == null ? 'Up to now (live)' : fmt.format(value),
              style: const TextStyle(fontSize: 13)),
        ),
      ),
      if (canClear && value != null) ...[
        const SizedBox(width: 6),
        IconButton(
            onPressed: onClear,
            icon: const Icon(Icons.clear, size: 16),
            tooltip: 'Clear'),
      ],
    ]);
  }
}

