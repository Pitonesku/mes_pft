// lib/screens/web/bug_reports_screen.dart
// Review board for user-submitted bug / suggestion reports (manager / admin).
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../../api_service.dart';
import '../../models.dart';

class BugReportsScreen extends StatefulWidget {
  final User user;
  const BugReportsScreen({super.key, required this.user});

  @override
  State<BugReportsScreen> createState() => _BugReportsScreenState();
}

class _BugReportsScreenState extends State<BugReportsScreen> {
  List<dynamic> _rows = [];
  bool _loading = true;
  String? _statusFilter;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() => _loading = true);
    final rows = await ApiService.fetchBugReports();
    if (!mounted) return;
    setState(() {
      _rows = rows ?? [];
      _loading = false;
    });
  }

  Future<void> _resolve(int id, String status) async {
    final noteC = TextEditingController();
    final note = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(status == 'RESOLVED' ? 'Resolve report #$id' : 'Mark #$id in progress'),
        content: TextField(
          controller: noteC,
          maxLines: 3,
          decoration: const InputDecoration(labelText: 'Note (optional)'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, noteC.text.trim()), child: const Text('Save')),
        ],
      ),
    );
    final r = await ApiService.resolveBugReport(id, status: status, note: note);
    if (!mounted) return;
    if (r == null) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed: ${ApiService.lastApiDetail ?? 'unknown error'}')));
    }
    await _reload();
  }

  Color _statusColor(String s) => switch (s) {
        'NEW' => Colors.red.shade700,
        'IN_PROGRESS' => Colors.orange.shade800,
        _ => Colors.green.shade700,
      };

  @override
  Widget build(BuildContext context) {
    final rows = _statusFilter == null
        ? _rows
        : _rows.where((r) => r['status'] == _statusFilter).toList();
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Text('Bug reports & suggestions',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
          const Spacer(),
          for (final f in [(null, 'All'), ('NEW', 'New'), ('IN_PROGRESS', 'In Progress'), ('RESOLVED', 'Resolved')])
            Padding(
              padding: const EdgeInsets.only(left: 8),
              child: ChoiceChip(
                label: Text(f.$2),
                selected: _statusFilter == f.$1,
                onSelected: (_) => setState(() => _statusFilter = f.$1),
              ),
            ),
        ]),
        const SizedBox(height: 12),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : rows.isEmpty
                  ? const Center(child: Text('No bug reports yet.'))
                  : ListView.builder(
                      itemCount: rows.length,
                      itemBuilder: (ctx, i) => _card(rows[i]),
                    ),
        ),
      ]),
    );
  }

  Widget _card(Map<String, dynamic> r) {
    final id = r['id'] as int;
    final atts = (r['attachments'] as List<dynamic>?) ?? const [];
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(Icons.bug_report, size: 18, color: _statusColor(r['status'].toString())),
            const SizedBox(width: 8),
            Text('#$id · ${r['username']} (${r['source']})',
                style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(width: 10),
            Text(r['created_at']?.toString().replaceFirst('T', ' ').substring(0, 16) ?? '',
                style: TextStyle(color: Colors.grey.shade600, fontSize: 12)),
            const Spacer(),
            Chip(
              label: Text(r['status'].toString(),
                  style: const TextStyle(color: Colors.white, fontSize: 11)),
              backgroundColor: _statusColor(r['status'].toString()),
            ),
          ]),
          const SizedBox(height: 8),
          Text(r['text'].toString()),
          if (r['resolution_note'] != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('Resolution: ${r['resolution_note']}',
                  style: TextStyle(color: Colors.green.shade800, fontSize: 13)),
            ),
          if (atts.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Wrap(spacing: 8, children: [
                for (final a in atts)
                  _AttachmentPreview(reportId: id, att: a as Map<String, dynamic>),
              ]),
            ),
          const SizedBox(height: 8),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            if (r['status'] != 'IN_PROGRESS' && r['status'] != 'RESOLVED')
              TextButton.icon(
                onPressed: () => _resolve(id, 'IN_PROGRESS'),
                icon: const Icon(Icons.play_arrow),
                label: const Text('In Progress'),
              ),
            if (r['status'] != 'RESOLVED')
              FilledButton.icon(
                onPressed: () => _resolve(id, 'RESOLVED'),
                icon: const Icon(Icons.check),
                label: const Text('Resolve'),
              ),
          ]),
        ]),
      ),
    );
  }
}

class _AttachmentPreview extends StatefulWidget {
  final int reportId;
  final Map<String, dynamic> att;
  const _AttachmentPreview({required this.reportId, required this.att});

  @override
  State<_AttachmentPreview> createState() => _AttachmentPreviewState();
}

class _AttachmentPreviewState extends State<_AttachmentPreview> {
  Uint8List? _bytes;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final b = await ApiService.fetchBugAttachment(widget.reportId, widget.att['id'] as int);
    if (mounted) setState(() => _bytes = b);
  }

  @override
  Widget build(BuildContext context) {
    final b = _bytes;
    return GestureDetector(
      onTap: () => showDialog(
        context: context,
        builder: (_) => Dialog(
          child: b == null
              ? const Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())
              : Image.memory(b, fit: BoxFit.contain),
        ),
      ),
      child: Container(
        width: 90,
        height: 90,
        decoration: BoxDecoration(
          border: Border.all(color: Colors.grey.shade300),
          borderRadius: BorderRadius.circular(8),
        ),
        child: b == null
            ? const Center(
                child: SizedBox(
                    width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)))
            : Image.memory(b, fit: BoxFit.cover),
      ),
    );
  }
}