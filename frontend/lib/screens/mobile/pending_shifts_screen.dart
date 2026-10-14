// lib/screens/mobile/pending_shifts_screen.dart
// Lists AUTO_CLOSED shifts awaiting a final report and unsent local drafts. An
// operator/supervisor can open a draft for review, or discard empty sessions.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../api_service.dart';
import '../../local_db.dart';
import '../../models.dart';
import 'operator_screen.dart';

class PendingShiftsScreen extends StatefulWidget {
  final User operator;
  const PendingShiftsScreen({super.key, required this.operator});
  @override
  State<PendingShiftsScreen> createState() => _PendingShiftsScreenState();
}

class _PendingShiftsScreenState extends State<PendingShiftsScreen> {
  bool _loading = true;
  bool _busy = false;
  List<dynamic> _shifts = [];
  List<Map<String, dynamic>> _localDrafts = [];

  static final DateFormat _date = DateFormat('dd.MM.yyyy');
  static final DateFormat _clock = DateFormat('HH:mm');

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await ApiService.fetchShiftSessions(status: 'AUTO_CLOSED');
    final drafts = await LocalDB.instance.getReportsByStatus('draft');
    final parsed = <Map<String, dynamic>>[];
    var purged = 0;
    for (final d in drafts) {
      final data = jsonDecode(d['report_data'] as String) as Map<String, dynamic>;
      // Sanitize corrupted drafts (missing shift name / machine): never render them.
      if ((data['shift_name'] ?? '').toString().trim().isEmpty ||
          (data['machine_name'] ?? '').toString().trim().isEmpty) {
        await LocalDB.instance.deleteReport(d['id'] as int);
        purged++;
        continue;
      }
      parsed.add({'id': d['id'], 'data': data});
    }
    if (mounted) {
      setState(() {
        _shifts = r ?? [];
        _localDrafts = parsed;
        _loading = false;
      });
    }
    if (purged > 0 && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Removed $purged corrupted draft(s).')),
      );
    }
  }

  // ---------------------------------------------------------------------------
  // time formatting (device local time, human readable)
  // ---------------------------------------------------------------------------

  String _fmt(DateTime? dt) => dt == null ? '' : '${_date.format(dt)} • ${_clock.format(dt)}';

  /// Parse an ISO timestamp (which may carry microseconds + an offset such as
  /// `-07:00`), then render it in device-local time.
  DateTime? _parseIso(dynamic v) {
    if (v == null) return null;
    try {
      return DateTime.parse(v.toString()).toLocal();
    } catch (_) {
      return null;
    }
  }

  String _range(String? start, String? end) {
    final s = _parseIso(start);
    final e = _parseIso(end);
    if (s == null && e == null) return '';
    if (s == null) return _fmt(e);
    if (e == null) return _fmt(s);
    return '${_date.format(s)} • ${_clock.format(s)} – ${_clock.format(e)}';
  }

  // ---------------------------------------------------------------------------
  // actions
  // ---------------------------------------------------------------------------

  Future<void> _finalize(int shiftId) async {
    setState(() => _busy = true);
    final ok = await ApiService.completeShift(shiftId);
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(ok ? 'Shift finalized — report submitted' : 'Failed to finalize'),
    ));
    if (ok) _load();
  }

  Future<void> _discardShift(Map s) async {
    final name = '${s['shift_name'] ?? 'Shift'} • ${s['machine_name'] ?? '?'}';
    final confirmed = await _confirm(
      'Discard shift?',
      'This removes "$name" from the pending list. Only empty test sessions can be discarded.',
    );
    if (confirmed != true) return;
    setState(() => _busy = true);
    final ok = await ApiService.discardShift(s['id'] as int);
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(ok ? 'Shift discarded' : (ApiService.lastApiDetail ?? 'Failed to discard')),
    ));
    if (ok) _load();
  }

  Future<void> _discardDraft(Map d) async {
    final name = '${d['data']['shift_name']} • ${d['data']['machine_name']}';
    final confirmed = await _confirm(
      'Delete draft?',
      'Delete "$name"? This cannot be undone.',
    );
    if (confirmed != true) return;
    await LocalDB.instance.deleteReport(d['id'] as int);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Draft deleted.')));
    _load();
  }

  Future<bool?> _confirm(String title, String message) {
    return showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(d, true), child: const Text('Discard')),
        ],
      ),
    );
  }

  void _openDraft(Map d) {
    final data = d['data'] as Map<String, dynamic>;
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => ReportPage(
          operator: widget.operator,
          initialData: data,
          localId: d['id'] as int?,
          initialStatus: 'draft',
        ),
      ),
    ).then((_) => _load());
  }


  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pending Reports'),
        backgroundColor: Colors.deepPurple,
        foregroundColor: Colors.white,
        actions: [IconButton(icon: const Icon(Icons.refresh), onPressed: _busy ? null : _load)],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : (_shifts.isEmpty && _localDrafts.isEmpty)
              ? const Center(child: Text('No pending shifts or drafts.'))
              : ListView(
                  padding: const EdgeInsets.all(12),
                  children: [
                    if (_shifts.isNotEmpty) ...[
                      const Text('Auto-Closed Shifts', style: TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      ..._shifts.map((raw) => _shiftCard(Map<String, dynamic>.from(raw as Map))),
                    ],
                    if (_localDrafts.isNotEmpty) ...[
                      const Divider(height: 28),
                      const Text('Local Drafts (unsent)', style: TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      ..._localDrafts.map(_draftCard),
                    ],
                  ],
                ),
    );
  }

  Widget _shiftCard(Map s) {
    final mo = (s['mo_ref'] ?? '').toString().trim();
    final operator = (s['operator_name'] ?? '').toString().trim();
    final shiftName = (s['shift_name'] ?? 'Shift').toString();
    final machineName = (s['machine_name'] ?? '').toString().trim();
    final machine = machineName.isEmpty ? 'Machine ${s['machine_id'] ?? '?'}' : machineName;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _header('$shiftName • $machine'),
          const SizedBox(height: 6),
          _row('MO', mo.isEmpty ? 'No MO attached' : mo),
          _row('Operator', operator.isEmpty ? '—' : operator),
          _row('Time', _range(s['started_at']?.toString(), s['ended_at']?.toString())),
          const SizedBox(height: 8),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            TextButton.icon(
              icon: const Icon(Icons.delete_outline, color: Colors.red),
              label: const Text('Discard', style: TextStyle(color: Colors.red)),
              onPressed: _busy ? null : () => _discardShift(s),
            ),
            const SizedBox(width: 8),
            FilledButton.icon(
              icon: const Icon(Icons.send),
              label: const Text('Submit Report'),
              onPressed: _busy ? null : () => _finalize(s['id'] as int),
            ),
          ]),
        ]),
      ),
    );
  }

  Widget _draftCard(Map d) {
    final data = d['data'] as Map<String, dynamic>;
    final mo = (data['po_number'] ?? '').toString().trim();
    final operator = (data['operator_name'] ?? '').toString().trim();
    final time = _draftRange(data);
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _header('${data['shift_name']} • ${data['machine_name']}'),
          const SizedBox(height: 6),
          _row('MO', mo.isEmpty ? 'No MO attached' : mo),
          _row('Operator', operator.isEmpty ? '—' : operator),
          _row('Time', time.isEmpty ? '—' : time),
          const SizedBox(height: 8),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            TextButton.icon(
              icon: const Icon(Icons.delete_outline, color: Colors.red),
              label: const Text('Discard', style: TextStyle(color: Colors.red)),
              onPressed: _busy ? null : () => _discardDraft(d),
            ),
            const SizedBox(width: 8),
            FilledButton.icon(
              icon: const Icon(Icons.edit_note),
              label: const Text('Open & Submit'),
              onPressed: _busy ? null : () => _openDraft(d),
            ),
          ]),
        ]),
      ),
    );
  }

  /// Drafts carry `shift_date` + `start_time`/`end_time` (clock strings).
  String _draftRange(Map data) {
    final date = (data['shift_date'] ?? data['report_date'] ?? '').toString();
    final start = (data['start_time'] ?? '').toString().trim();
    final end = (data['end_time'] ?? '').toString().trim();
    String? day;
    try {
      final d = DateTime.tryParse(date);
      day = d != null ? _date.format(d.toLocal()) : null;
    } catch (_) {
      day = null;
    }
    if (day == null) {
      final tr = (data['shift_time_range'] ?? '').toString().trim();
      return tr.isEmpty ? '' : tr;
    }
    if (start.isEmpty && end.isEmpty) return day;
    if (start.isNotEmpty && end.isNotEmpty) return '$day • $start – $end';
    return '$day • ${start.isEmpty ? end : start}';
  }

  Widget _header(String text) =>
      Text(text, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16));

  Widget _row(String label, String value) => Padding(
        padding: const EdgeInsets.only(bottom: 2),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 72, child: Text(label, style: const TextStyle(color: Colors.grey))),
          Expanded(child: Text(value)),
        ]),
      );
}
