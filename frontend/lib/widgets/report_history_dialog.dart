// lib/widgets/report_history_dialog.dart
// Read-only audit/history view for a production report, with a
// "Restore to Original" action backed by POST /api/reports/{id}/revert.
import 'package:flutter/material.dart';
import '../api_service.dart';

Future<void> showReportHistoryDialog(
  BuildContext context,
  Map<String, dynamic> report, {
  VoidCallback? onReverted,
}) {
  return showGeneralDialog<void>(
    context: context,
    barrierDismissible: true,
    barrierLabel: 'Report history',
    transitionDuration: const Duration(milliseconds: 180),
    pageBuilder: (ctx, a1, a2) =>
        _ReportHistoryDialog(report: report, onReverted: onReverted),
  );
}

class _ReportHistoryDialog extends StatefulWidget {
  final Map<String, dynamic> report;
  final VoidCallback? onReverted;
  const _ReportHistoryDialog({required this.report, this.onReverted});
  @override
  State<_ReportHistoryDialog> createState() => _ReportHistoryDialogState();
}

class _ReportHistoryDialogState extends State<_ReportHistoryDialog> {
  bool _loading = true;
  bool _reverting = false;
  List<dynamic> _edits = [];
  List<dynamic> _logs = [];
  String? _error;

  int? get _reportId {
    final raw = widget.report['id'];
    if (raw == null) return null;
    return raw is int ? raw : int.tryParse(raw.toString());
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final id = _reportId;
    if (id == null) {
      setState(() {
        _loading = false;
        _error = 'Invalid report id';
      });
      return;
    }
    final edits = await ApiService.fetchReportEdits(id);
    final logs = await ApiService.fetchReportLogs(id);
    if (!mounted) return;
    setState(() {
      _loading = false;
      _edits = (edits?['edits'] as List?) ?? const [];
      _logs = (logs?['logs'] as List?) ?? const [];
    });
  }

  Future<void> _revert() async {
    final id = _reportId;
    if (id == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Restore to Original?'),
        content: const Text(
            'This restores every field to its original pre-edit value and resets '
            'verification to pending. The action is written to the audit log.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Restore')),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() => _reverting = true);
    final ok = await ApiService.revertReport(id);
    if (!mounted) return;
    setState(() => _reverting = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(ok
          ? 'Report restored to original.'
          : 'Failed to restore report.'),
      backgroundColor: ok ? Colors.green : Colors.red,
    ));
    if (ok) {
      widget.onReverted?.call();
      Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('History — Report #${widget.report['id'] ?? ''}'),
        backgroundColor: Colors.deepPurple,
        foregroundColor: Colors.white,
        leading: IconButton(
            icon: const Icon(Icons.close),
            onPressed: () => Navigator.pop(context)),
        actions: [
          if (_edits.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: TextButton.icon(
                onPressed: _reverting ? null : _revert,
                icon: const Icon(Icons.restore, color: Colors.white),
                label: const Text('Restore to Original',
                    style: TextStyle(color: Colors.white)),
              ),
            ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Text(_error!,
                      style: const TextStyle(color: Colors.red)))
              : SingleChildScrollView(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _section('Audit Timeline',
                            _logs.map((l) => _auditRow(l)).toList()),
                        const SizedBox(height: 24),
                        _section('Field Edits',
                            _edits.map((e) => _editCard(e)).toList()),
                        if (_edits.isEmpty && _logs.isEmpty)
                          const Center(
                              child: Padding(
                                  padding: EdgeInsets.all(24),
                                  child: Text('No history for this report.'))),
                      ]),
                ),
    );
  }
  Widget _section(String title, List<Widget> children) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(title,
          style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.bold,
              color: Colors.deepPurple)),
      const SizedBox(height: 8),
      if (children.isEmpty)
        const Text('No records',
            style: TextStyle(fontSize: 12, color: Colors.grey))
      else
        ...children,
    ]);
  }

  Widget _auditRow(dynamic l) {
    final action = l['action']?.toString() ?? '-';
    final user = l['username']?.toString() ?? '-';
    final when = l['created_at']?.toString() ?? '';
    final color = switch (action) {
      'EDITED' => Colors.orange,
      'RESTORED' => Colors.blue,
      'VERIFIED' => Colors.green,
      'REJECTED' => Colors.red,
      'CREATED' => Colors.grey,
      'DELETED' => Colors.red,
      _ => Colors.grey,
    };
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(
              color: color.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(8)),
          child: Text(action,
              style: TextStyle(
                  fontSize: 11, fontWeight: FontWeight.bold, color: color)),
        ),
        const SizedBox(width: 8),
        Expanded(
            child: Text('$user${when.isNotEmpty ? ' · $when' : ''}',
                style: const TextStyle(fontSize: 12))),
      ]),
    );
  }

  Widget _editCard(dynamic e) {
    final user = e['username']?.toString() ?? '-';
    final when = e['edited_at']?.toString() ?? '';
    final changed =
        (e['changed_fields'] as List?)?.map((x) => x.toString()).toList() ??
            const <String>[];
    final oldV =
        (e['old_values'] as Map?)?.cast<String, dynamic>() ?? const {};
    final newV =
        (e['new_values'] as Map?)?.cast<String, dynamic>() ?? const {};
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$user · $when',
              style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
          const SizedBox(height: 6),
          for (final f in changed)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(
                    width: 150,
                    child: Text(f,
                        style: const TextStyle(
                            fontSize: 12,
                            color: Colors.grey,
                            fontWeight: FontWeight.w500))),
                Expanded(
                    child: Text('${_fmtVal(oldV[f])}  →  ${_fmtVal(newV[f])}',
                        style: const TextStyle(fontSize: 12))),
              ]),
            ),
        ]),
      ),
    );
  }

  String _fmtVal(dynamic v) {
    if (v == null) return '(none)';
    var s = v.toString();
    if (s.length > 90) s = '${s.substring(0, 90)}…';
    return s;
  }

}
