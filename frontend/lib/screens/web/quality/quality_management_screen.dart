// lib/screens/web/quality/quality_management_screen.dart
// Web-only Quality Management: NCR lifecycle + quarantine resolutions
// (scrap / release). Write actions require can_manage_quality.

import 'package:flutter/material.dart';

import '../../../api_service.dart';
import '../../../app_state.dart';
import '../../../models.dart';

class QualityManagementScreen extends StatefulWidget {
  final User user;
  const QualityManagementScreen({super.key, required this.user});

  @override
  State<QualityManagementScreen> createState() => _QualityManagementScreenState();
}

class _QualityManagementScreenState extends State<QualityManagementScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(length: 2, vsync: this);
  bool get _canWrite =>
      widget.user.canManageQuality || widget.user.role == UserRole.superAdmin;

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Quality Management'),
        bottom: TabBar(
          controller: _tabs,
          tabs: const [Tab(text: 'Non-Conformities (NCR)'), Tab(text: 'Quarantine')],
        ),
      ),
      body: TabBarView(
        controller: _tabs,
        children: [
          _NcrTab(user: widget.user, canWrite: _canWrite),
          _QuarantineTab(user: widget.user, canWrite: _canWrite),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// NCR tab
// ---------------------------------------------------------------------------

class _NcrTab extends StatefulWidget {
  final User user;
  final bool canWrite;
  const _NcrTab({required this.user, required this.canWrite});

  @override
  State<_NcrTab> createState() => _NcrTabState();
}

class _NcrTabState extends State<_NcrTab> {
  List<Ncr> _ncrs = [];
  bool _loading = true;
  String? _statusFilter;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() => _loading = true);
    final rows = await ApiService.listNcrs(status: _statusFilter);
    if (mounted) {
      setState(() {
        _ncrs = rows ?? [];
        _loading = false;
      });
    }
  }

  Future<void> _openCreate() async {
    final created = await showDialog<Ncr>(
      context: context,
      builder: (_) => _NcrCreateDialog(),
    );
    if (created != null) await _reload();
  }

  Future<void> _close(Ncr ncr) async {
    final remarksC = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Close ${ncr.ncrNumber}'),
        content: TextField(
          controller: remarksC,
          maxLines: 3,
          decoration: const InputDecoration(labelText: 'Closing remarks *'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Close NCR'),
          ),
        ],
      ),
    );
    if (ok == true) {
      final err = await ApiService.closeNcr(ncr.id, remarksC.text.trim());
      if (err != null && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
      }
      await _reload();
    }
  }

  Future<void> _reopen(Ncr ncr) async {
    final err = await ApiService.reopenNcr(ncr.id);
    if (err != null && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
    }
    await _reload();
  }

  Color _statusColor(String status) => switch (status) {
        'OPEN' => Colors.red.shade700,
        'IN_PROGRESS' => Colors.orange.shade800,
        _ => Colors.green.shade700,
      };

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      Padding(
        padding: const EdgeInsets.all(8),
        child: Row(children: [
          for (final f in [(null, 'All'), ('OPEN', 'Open'), ('IN_PROGRESS', 'In Progress'), ('CLOSED', 'Closed')])
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(f.$2),
                selected: _statusFilter == f.$1,
                onSelected: (_) {
                  setState(() => _statusFilter = f.$1);
                  _reload();
                },
              ),
            ),
          const Spacer(),
          if (widget.canWrite)
            FilledButton.icon(
              onPressed: _openCreate,
              icon: const Icon(Icons.add),
              label: const Text('New NCR'),
            ),
        ]),
      ),
      Expanded(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _ncrs.isEmpty
                ? const Center(child: Text('No NCRs found'))
                : ListView.builder(
                    itemCount: _ncrs.length,
                    itemBuilder: (ctx, i) => _ncrCard(_ncrs[i]),
                  ),
      ),
    ]);
  }

  Widget _ncrCard(Ncr ncr) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      child: ListTile(
        leading: Icon(
          ncr.isCritical ? Icons.warning_amber : Icons.report_problem_outlined,
          color: ncr.isOpen ? Colors.orange.shade800 : Colors.green,
        ),
        title: Text('${ncr.ncrNumber ?? 'NCR'} — ${ncr.moRef ?? ''}'),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(ncr.description, maxLines: 2, overflow: TextOverflow.ellipsis),
          if (ncr.correctiveAction?.isNotEmpty == true)
            Text('CAPA: ${ncr.correctiveAction}', maxLines: 1, overflow: TextOverflow.ellipsis),
          Text(
            '${ncr.severity} · ${ncr.machineName ?? 'no machine'} · '
            '${ncr.createdAt?.toLocal().toString().split('.').first ?? ''}',
            style: const TextStyle(fontSize: 12),
          ),
        ]),
        trailing: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Chip(
            label: Text(ncr.status),
            backgroundColor: _statusColor(ncr.status).withValues(alpha: 0.15),
            labelStyle: TextStyle(color: _statusColor(ncr.status), fontSize: 11),
          ),
          if (widget.canWrite) ...[
            if (ncr.isOpen)
              TextButton(onPressed: () => _close(ncr), child: const Text('Close'))
            else
              TextButton(onPressed: () => _reopen(ncr), child: const Text('Reopen')),
          ],
        ]),
      ),
    );
  }
}

class _NcrCreateDialog extends StatefulWidget {
  @override
  State<_NcrCreateDialog> createState() => _NcrCreateDialogState();
}

class _NcrCreateDialogState extends State<_NcrCreateDialog> {
  PurchaseOrder? _po;
  final _descC = TextEditingController();
  final _capaC = TextEditingController();
  String _severity = 'MINOR';
  bool _saving = false;

  @override
  void dispose() {
    _descC.dispose();
    _capaC.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final orders = AppData.activePOs
        .where((p) => !p.isArchived)
        .toList()
      ..sort((a, b) => b.poNumber.compareTo(a.poNumber));
    return AlertDialog(
      title: const Text('New Non-Conformity Report'),
      content: SizedBox(
        width: 480,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          DropdownButtonFormField<PurchaseOrder>(
            initialValue: _po,
            decoration: const InputDecoration(labelText: 'Manufacturing Order *'),
            items: [
              for (final p in orders)
                DropdownMenuItem(value: p, child: Text(p.poNumber)),
            ],
            onChanged: (v) => setState(() => _po = v),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _descC,
            maxLines: 3,
            decoration: const InputDecoration(labelText: 'Problem description *'),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _capaC,
            maxLines: 2,
            decoration: const InputDecoration(labelText: 'Corrective action (CAPA)'),
          ),
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
            initialValue: _severity,
            decoration: const InputDecoration(labelText: 'Severity'),
            items: const [
              DropdownMenuItem(value: 'MINOR', child: Text('MINOR')),
              DropdownMenuItem(value: 'MAJOR', child: Text('MAJOR')),
              DropdownMenuItem(value: 'CRITICAL', child: Text('CRITICAL')),
            ],
            onChanged: (v) => setState(() => _severity = v ?? 'MINOR'),
          ),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: _saving
              ? null
              : () async {
                  if (_po == null || _descC.text.trim().isEmpty) return;
                  setState(() => _saving = true);
                  final ncr = await ApiService.createNcr(
                    poId: _po!.id!,
                    description: _descC.text.trim(),
                    correctiveAction: _capaC.text.trim().isEmpty ? null : _capaC.text.trim(),
                    severity: _severity,
                  );
                  if (!mounted) return;
                  if (ncr == null) {
                    setState(() => _saving = false);
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Failed to create NCR (permission or server error)')),
                    );
                    return;
                  }
                  Navigator.pop(context, ncr);
                },
          child: const Text('Create'),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Quarantine tab
// ---------------------------------------------------------------------------

class _QuarantineTab extends StatefulWidget {
  final User user;
  final bool canWrite;
  const _QuarantineTab({required this.user, required this.canWrite});

  @override
  State<_QuarantineTab> createState() => _QuarantineTabState();
}

class _QuarantineTabState extends State<_QuarantineTab> {
  PurchaseOrder? _po;
  QuarantineSummary? _summary;
  bool _loading = false;

  Future<void> _reload() async {
    if (_po == null) {
      setState(() => _summary = null);
      return;
    }
    setState(() => _loading = true);
    final s = await ApiService.fetchOrderQuarantine(_po!.id!);
    if (mounted) {
      setState(() {
        _summary = s;
        _loading = false;
      });
    }
  }

  Future<void> _openResolution(String kind) async {
    if (_po == null || _summary == null) return;
    final boxesC = TextEditingController();
    final kgC = TextEditingController();
    final notesC = TextEditingController();
    final isScrap = kind == 'scrap';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(isScrap ? 'Scrap Act (write off quarantine)' : 'Release from quarantine'),
        content: SizedBox(
          width: 420,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(
              '${_po!.poNumber} — ${_summary!.remainingBoxes} boxes remain in quarantine',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: boxesC,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Boxes *'),
            ),
            if (isScrap) ...[
              const SizedBox(height: 10),
              TextField(
                controller: kgC,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Dry weight (kg)'),
              ),
            ],
            const SizedBox(height: 10),
            TextField(
              controller: notesC,
              decoration: const InputDecoration(labelText: 'Notes'),
            ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(isScrap ? 'Scrap' : 'Release'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final err = await ApiService.createQuarantineResolution(
      poId: _po!.id!,
      kind: kind,
      boxes: int.tryParse(boxesC.text.trim()) ?? 0,
      dryWeightKg: isScrap ? (double.tryParse(kgC.text.trim().replaceAll(',', '.')) ?? 0) : null,
      notes: notesC.text.trim().isEmpty ? null : notesC.text.trim(),
    );
    if (!mounted) return;
    if (err != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${isScrap ? 'Scrap' : 'Release'} submitted')),
      );
    }
    await _reload();
  }

  @override
  Widget build(BuildContext context) {
    final orders = AppData.activePOs.toList()
      ..sort((a, b) => b.poNumber.compareTo(a.poNumber));
    return Column(children: [
      Padding(
        padding: const EdgeInsets.all(8),
        child: Row(children: [
          SizedBox(
            width: 320,
            child: DropdownButtonFormField<PurchaseOrder>(
              initialValue: _po,
              decoration: const InputDecoration(labelText: 'Manufacturing Order'),
              items: [
                for (final p in orders)
                  DropdownMenuItem(value: p, child: Text(p.poNumber)),
              ],
              onChanged: (v) {
                setState(() => _po = v);
                _reload();
              },
            ),
          ),
          const SizedBox(width: 12),
          if (widget.canWrite && _summary != null && _summary!.remainingBoxes > 0) ...[
            FilledButton.icon(
              onPressed: () => _openResolution('scrap'),
              icon: const Icon(Icons.delete_outline),
              label: const Text('Scrap'),
            ),
            const SizedBox(width: 8),
            OutlinedButton.icon(
              onPressed: () => _openResolution('release'),
              icon: const Icon(Icons.inventory),
              label: const Text('Release'),
            ),
          ],
        ]),
      ),
      if (_loading)
        const Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())
      else if (_summary == null)
        const Padding(padding: EdgeInsets.all(24), child: Text('Select an order'))
      else
        Expanded(
          child: ListView(children: [
            Padding(
              padding: const EdgeInsets.all(8),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Wrap(spacing: 24, runSpacing: 12, children: [
                    _stat('Quarantined', '${_summary!.totalQuarantineBoxes} boxes'),
                    _stat('Scrapped', '${_summary!.scrapBoxes} boxes / ${_summary!.scrapKg} kg'),
                    _stat('Released', '${_summary!.releasedBoxes} boxes'),
                    _stat('Remaining', '${_summary!.remainingBoxes} boxes',
                        highlight: _summary!.remainingBoxes > 0),
                  ]),
                ),
              ),
            ),
            for (final r in _summary!.resolutions.reversed)
              Card(
                margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                child: ListTile(
                  leading: Icon(
                    r.isScrap ? Icons.delete_outline : Icons.inventory,
                    color: r.isScrap ? Colors.red.shade700 : Colors.green.shade700,
                  ),
                  title: Text('${r.docNumber ?? r.kind.toUpperCase()} — ${r.kind.toUpperCase()}'),
                  subtitle: Text(
                    '${r.boxes} boxes'
                    '${r.dryWeightKg != null ? ' · ${r.dryWeightKg} kg' : ''}'
                    '${r.odooSyncStatus != 'local' ? ' · Odoo: ${r.odooSyncStatus}' : ''}'
                    '${r.notes != null ? ' · ${r.notes}' : ''}'
                    '${r.isVoided ? ' · VOIDED' : ''}',
                  ),
                  trailing: Text(
                    r.createdAt?.toLocal().toString().split('.').first ?? '',
                    style: const TextStyle(fontSize: 11),
                  ),
                ),
              ),
          ]),
        ),
    ]);
  }

  Widget _stat(String label, String value, {bool highlight = false}) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey)),
          Text(
            value,
            style: TextStyle(
              fontWeight: FontWeight.bold,
              color: highlight ? Colors.orange.shade800 : null,
            ),
          ),
        ],
      );
}

