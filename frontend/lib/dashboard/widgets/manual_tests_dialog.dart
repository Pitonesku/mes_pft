// lib/dashboard/widgets/manual_tests_dialog.dart
// Modal table of every manual QC check for a machine's active run. Columns are
// dynamic: only parameters marked Visible in the machine's manual_test_config
// are shown (mirrors the "Manual measurements" section of the report).
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api_service.dart';

class ManualTestsDialog extends StatefulWidget {
  final int machineId;
  final String? machineName;
  const ManualTestsDialog({super.key, required this.machineId, this.machineName});
  @override
  State<ManualTestsDialog> createState() => _ManualTestsDialogState();
}

class _ManualTestsDialogState extends State<ManualTestsDialog> {
  bool _loading = true;
  Map<String, dynamic>? _data;
  List<Map<String, dynamic>> _checks = [];
  Map<String, Map<String, dynamic>> _config = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await ApiService.fetchMachineManualTests(widget.machineId);
    if (!mounted) return;
    final checks = <Map<String, dynamic>>[];
    for (final c in ((d?['checks'] as List<dynamic>?) ?? const [])) {
      if (c is Map) checks.add(c.cast<String, dynamic>());
    }
    final cfg = <String, Map<String, dynamic>>{};
    final params = ((d?['config'] as Map<String, dynamic>?) ?? const {})['parameters'];
    for (final p in (params as List<dynamic>? ?? const [])) {
      if (p is Map) cfg['${p['key']}'] = p.cast<String, dynamic>();
    }
    setState(() {
      _data = d;
      _checks = checks;
      _config = cfg;
      _loading = false;
    });
  }

  bool _visible(String key) => _config[key]?['is_visible'] == true;

  // (key, label) for every visible parameter, in report order.
  List<(String, String)> get _columns => [
        if (_visible('weight')) ('weight', 'Weight (mg)'),
        if (_visible('length')) ('length', 'Length (mm)'),
        if (_visible('hardness')) ('hardness', 'Hardness (%)'),
        if (_visible('glue_seam')) ('glue_seam', 'Glue Seam'),
        if (_visible('cut_quality')) ('cut_quality', 'Cut Quality'),
        if (_visible('visual_cleanness')) ('visual_cleanness', 'Visual Cleanness'),
        if (_visible('triacetin')) ('triacetin', 'Triacetin (%)'),
      ];

  @override
  Widget build(BuildContext context) {
    final title = widget.machineName ?? 'Machine #${widget.machineId}';
    return AlertDialog(
      title: Row(children: [
        const Icon(Icons.fact_check_outlined, color: Colors.deepPurple),
        const SizedBox(width: 8),
        Expanded(
            child: Text('Manual tests — $title',
                overflow: TextOverflow.ellipsis)),
        IconButton(icon: const Icon(Icons.refresh), tooltip: 'Refresh', onPressed: _load),
      ]),
      content: SizedBox(
        width: 760,
        child: _buildContent(),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
      ],
    );
  }

  Widget _buildContent() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_data?['run_id'] == null) {
      return const Text('No active run for this machine.');
    }
    if (_checks.isEmpty) {
      return const Text('No manual tests recorded for the active run.');
    }
    final cols = _columns;
    final rows = <TableRow>[
      TableRow(children: [
        _th('Time'),
        for (final (_, label) in cols) _th(label),
      ]),
      for (final c in _checks)
        TableRow(children: [
          _td(_fmtTime(c['measured_at'])),
          for (final (key, _) in cols) _td(_cell(c, key)),
        ]),
    ];
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: SingleChildScrollView(
        child: Table(
          border: TableBorder.all(color: Colors.grey.shade300),
          defaultColumnWidth: const IntrinsicColumnWidth(),
          children: rows,
        ),
      ),
    );
  }

  String _cell(Map<String, dynamic> c, String key) {
    switch (key) {
      case 'weight':
        return _f(c['weight_mg']);
      case 'length':
        return _f(c['length_mm']);
      case 'hardness':
        return _f(c['hardness']);
      case 'glue_seam':
        return _flag(c['glue_seam_ok']);
      case 'cut_quality':
        return _flag(c['cut_quality_ok']);
      case 'visual_cleanness':
        return _flag(c['visual_appearance_ok']);
      case 'triacetin':
        return _f(c['triacetin_pct']);
      default:
        return '-';
    }
  }

  String _f(dynamic v) {
    if (v == null) return '';
    if (v is num) {
      final d = v.toDouble();
      if (d == d.roundToDouble()) return d.round().toString();
      return d.toString();
    }
    return '$v';
  }

  String _flag(dynamic v) => v == null ? '-' : (v == true ? 'OK' : 'FAIL');

  String _fmtTime(dynamic v) {
    if (v == null || '$v'.isEmpty) return '-';
    try {
      return DateFormat('HH:mm').format(DateTime.parse('$v').toLocal());
    } catch (_) {
      return '$v';
    }
  }

  Widget _th(String t) => Padding(
      padding: const EdgeInsets.all(6),
      child: Text(t, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 11)));
  Widget _td(String t) => Padding(
      padding: const EdgeInsets.all(6),
      child: Text(t, style: const TextStyle(fontSize: 11)));
}
