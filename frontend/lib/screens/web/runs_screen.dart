// lib/screens/web/runs_screen.dart
// Web console "Runs & Audit": run timeline per shift, per-run QC checks,
// change/audit log and the supervisor reassign action.

import 'package:flutter/material.dart';

import '../../api_service.dart';
import '../../models.dart';

class RunsScreen extends StatefulWidget {
  final User user;
  const RunsScreen({super.key, required this.user});

  @override
  State<RunsScreen> createState() => _RunsScreenState();
}

class _RunsScreenState extends State<RunsScreen> {
  List<dynamic> _shifts = [];
  bool _loading = true;
  String _status = 'active';
  int? _selectedShiftId;
  Map<String, dynamic>? _detail;

  bool get _isSupervisor =>
      widget.user.role == UserRole.superAdmin ||
      widget.user.role == UserRole.manager;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() => _loading = true);
    final rows = await ApiService.fetchV2Shifts(status: _status);
    if (!mounted) return;
    setState(() {
      _shifts = rows ?? [];
      _loading = false;
      if (_selectedShiftId != null &&
          !_shifts.any((s) => _s(s, 'id') == _selectedShiftId)) {
        _selectedShiftId = null;
        _detail = null;
      }
      if (_selectedShiftId == null && _shifts.isNotEmpty) {
        _selectShift(_s(_shifts.first, 'id'));
      }
    });
  }

  Future<void> _selectShift(int id) async {
    setState(() {
      _selectedShiftId = id;
      _detail = null;
    });
    final detail = await ApiService.fetchShiftDetail(id);
    if (!mounted || _selectedShiftId != id) return;
    setState(() => _detail = detail);
  }

  static dynamic _s(dynamic m, String k) => m is Map ? m[k] : null;

  String _fmt(dynamic iso) {
    if (iso is! String || iso.isEmpty) return '—';
    final t = DateTime.tryParse(iso);
    if (t == null) return iso;
    return t.toLocal().toString().substring(0, 16);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Runs & Audit'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: 'Refresh',
              onPressed: _reload,
            ),
          ),
        ],
      ),
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 380,
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: Row(
                    children: [
                      for (final (label, value) in [
                        ('Active', 'active'),
                        ('Auto-closed', 'AUTO_CLOSED'),
                        ('Closed', 'CLOSED'),
                        ('All', ''),
                      ])
                        Padding(
                          padding: const EdgeInsets.only(right: 6),
                          child: ChoiceChip(
                            label: Text(label),
                            selected: _status == value,
                            onSelected: (_) {
                              setState(() => _status = value);
                              _reload();
                            },
                          ),
                        ),
                    ],
                  ),
                ),
                Expanded(
                  child: _loading
                      ? const Center(child: CircularProgressIndicator())
                      : _shifts.isEmpty
                          ? const Center(child: Text('No shifts found'))
                          : ListView.builder(
                              itemCount: _shifts.length,
                              itemBuilder: (_, i) {
                                final s = _shifts[i];
                                final id = _s(s, 'id');
                                final selected = id == _selectedShiftId;
                                return ListTile(
                                  selected: selected,
                                  title: Text(
                                    '${_s(s, 'machine_name') ?? 'Machine ${_s(s, 'machine_id')}'} — '
                                    '${_s(s, 'operator_name') ?? 'op ${_s(s, 'operator_id')}'}',
                                  ),
                                  subtitle: Text(
                                    '${_s(s, 'status')}\n'
                                    '${_s(s, 'mo_ref') ?? ''}  ${_fmt(_s(s, 'started_at'))}',
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  isThreeLine: true,
                                  onTap: () => _selectShift(id),
                                );
                              },
                            ),
                ),
              ],
            ),
          ),
          const VerticalDivider(width: 1),
          Expanded(
            child: _detail == null
                ? const Center(child: Text('Select a shift to see its runs'))
                : _ShiftDetail(
                    detail: _detail!,
                    isSupervisor: _isSupervisor,
                    onChanged: () {
                      _selectShift(_selectedShiftId!);
                      _reload();
                    },
                  ),
          ),
        ],
      ),
    );
  }
}


// ---------------------------------------------------------------------------
// Shift detail: run timeline + per-run audit
// ---------------------------------------------------------------------------

class _ShiftDetail extends StatefulWidget {
  final Map<String, dynamic> detail;
  final bool isSupervisor;
  final VoidCallback onChanged;
  const _ShiftDetail(
      {required this.detail, required this.isSupervisor, required this.onChanged});

  @override
  State<_ShiftDetail> createState() => _ShiftDetailState();
}

class _ShiftDetailState extends State<_ShiftDetail> {
  final Map<int, List<dynamic>> _changes = {};
  final Map<int, List<dynamic>> _checks = {};
  final Set<int> _expanded = {};
  final Set<int> _loadingRun = {};

  List<dynamic> get _runs =>
      (widget.detail['runs'] as List?) ?? const <dynamic>[];

  dynamic _s(Map m, String k) => m[k];

  Future<void> _toggleRun(int runId) async {
    if (_expanded.contains(runId)) {
      setState(() => _expanded.remove(runId));
      return;
    }
    setState(() {
      _expanded.add(runId);
      _loadingRun.add(runId);
    });
    final changes = await ApiService.fetchRunChanges(runId);
    final checks = await ApiService.fetchRunManualChecks(runId);
    if (!mounted) return;
    setState(() {
      _changes[runId] = changes ?? [];
      _checks[runId] = checks ?? [];
      _loadingRun.remove(runId);
    });
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.detail;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Shift #${_s(d, 'id')} — ${_s(d, 'status')}',
            style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 4),
        Text(
          'Started ${_fmt(_s(d, 'started_at'))}  •  '
          'Ended ${_fmt(_s(d, 'ended_at'))}  •  '
          '${_s(d, 'shift_name') ?? ''}',
          style: Theme.of(context).textTheme.bodyMedium,
        ),
        const SizedBox(height: 16),
        Text('Runs (${_runs.length})',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        for (final run in _runs) _runCard(run),
      ],
    );
  }

  Widget _runCard(dynamic run) {
    final id = _s(run, 'id');
    final runId = id is int ? id : 0;
    final expanded = _expanded.contains(runId);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('Run #${_s(run, 'seq')}',
                    style: const TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(width: 12),
                Expanded(child: Text('${_s(run, 'mo_ref') ?? '—'}')),
                Text('${_s(run, 'status') ?? ''}'),
                const SizedBox(width: 8),
                IconButton(
                  icon: Icon(expanded ? Icons.expand_less : Icons.expand_more),
                  tooltip: 'Audit',
                  onPressed: () => _toggleRun(runId),
                ),
              ],
            ),
            Text(
              '${_fmt(_s(run, 'started_at'))} → ${_fmt(_s(run, 'ended_at'))}'
              '   counter ${_s(run, 'end_counter') ?? '—'}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            if (expanded && _loadingRun.contains(runId))
              const Padding(
                padding: EdgeInsets.all(8),
                child: Center(child: CircularProgressIndicator()),
              ),
            if (expanded && !_loadingRun.contains(runId))
              _auditPanel(runId, run),
          ],
        ),
      ),
    );
  }

  Widget _auditPanel(int runId, dynamic run) {
    final changes = _changes[runId] ?? const [];
    final checks = _checks[runId] ?? const [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Text('Change log', style: TextStyle(fontWeight: FontWeight.bold)),
            const Spacer(),
            if (widget.isSupervisor)
              TextButton.icon(
                icon: const Icon(Icons.edit),
                label: const Text('Reassign'),
                onPressed: () => _showReassign(runId, run),
              ),
          ],
        ),
        if (changes.isEmpty)
          const Padding(
            padding: EdgeInsets.only(bottom: 8),
            child: Text('No changes recorded.', style: TextStyle(color: Colors.grey)),
          )
        else
          for (final c in changes)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                '• ${_s(c, 'action')}  ${_s(c, 'created_at')}  '
                'reason: ${_s(c, 'reason') ?? '—'}  user ${_s(c, 'user_id')}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
        const SizedBox(height: 8),
        Text('Manual QC checks (${checks.length})',
            style: const TextStyle(fontWeight: FontWeight.bold)),
        if (checks.isEmpty)
          const Text('None recorded.', style: TextStyle(color: Colors.grey))
        else
          for (final c in checks)
            Padding(
              padding: const EdgeInsets.only(bottom: 2),
              child: Text(
                '• ${_fmt(_s(c, 'recorded_at') ?? _s(c, 'created_at'))} '
                '${_s(c, 'overall_status') ?? ''} ${_s(c, 'operator_name') ?? ''} '
                '${_s(c, 'notes') ?? ''}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
      ],
    );
  }

  Future<void> _showReassign(int runId, dynamic run) async {
    final reasonCtl = TextEditingController();
    final moCtl = TextEditingController(text: '${_s(run, 'mo_ref') ?? ''}');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Reassign run'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: moCtl,
              decoration: const InputDecoration(labelText: 'MO / PO number'),
            ),
            TextField(
              controller: reasonCtl,
              decoration: const InputDecoration(labelText: 'Reason (mandatory)'),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Reassign'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final reason = reasonCtl.text.trim();
    if (!mounted) return;
    if (reason.isEmpty) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Reason is mandatory')));
      return;
    }
    final result = await ApiService.reassignRun(
      runId,
      moRef: moCtl.text.trim().isEmpty ? null : moCtl.text.trim(),
      reason: reason,
    );
    if (!mounted) return;
    if (result != null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Run reassigned')));
      widget.onChanged();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(ApiService.lastApiDetail ?? 'Reassign failed')));
    }
  }

  String _fmt(dynamic iso) {
    if (iso is! String || iso.isEmpty) return '—';
    final t = DateTime.tryParse(iso);
    if (t == null) return iso;
    return t.toLocal().toString().substring(0, 16);
  }
}

