// lib/screens/web/odoo_review_dialogs.dart
// Odoo order-matching dialogs: manual MO chain picker and the unlinked-order
// review list. Superadmin flows only; the endpoints enforce it.
import 'package:flutter/material.dart';

import '../../api_service.dart';

Color _stateColor(String state) => switch (state) {
      'open' => Colors.green,
      'done' => Colors.blueGrey,
      'cancel' => Colors.red,
      _ => Colors.grey,
    };

Widget stateChip(String state) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: _stateColor(state).withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(state,
          style: TextStyle(color: _stateColor(state), fontSize: 12, fontWeight: FontWeight.w600)),
    );

Widget riskChips(List<dynamic> risk) {
  if (risk.isEmpty) return const SizedBox.shrink();
  return Wrap(
    spacing: 6,
    children: [
      for (final r in risk.cast<String>())
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(
            color: r == 'open_chain'
                ? Colors.orange.withValues(alpha: 0.15)
                : Colors.red.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(r.replaceAll('_', ' '),
              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
        ),
    ],
  );
}

class OdooMoPickerDialog extends StatefulWidget {
  final int localOrderId;
  final String orderLabel;

  /// Pre-fills the search box (e.g. the order number) so the matching Odoo
  /// chain is shown first instead of an unfiltered list.
  final String initialQuery;
  const OdooMoPickerDialog({
    super.key,
    required this.localOrderId,
    required this.orderLabel,
    this.initialQuery = '',
  });
  @override
  State<OdooMoPickerDialog> createState() => _OdooMoPickerDialogState();
}

class _OdooMoPickerDialogState extends State<OdooMoPickerDialog> {
  List<dynamic>? _chains;
  String _query = '';
  late final TextEditingController _searchCtrl;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _query = widget.initialQuery;
    _searchCtrl = TextEditingController(text: _query);
    _load();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _chains = null;
      _error = null;
    });
    final chains = await ApiService.fetchOdooMos(q: _query);
    if (!mounted) return;
    setState(() {
      _chains = chains;
      if (chains == null) {
        _error = ApiService.lastApiDetail ?? 'Failed to load Odoo MOs';
      }
    });
  }

  Widget _errorView() => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, color: Colors.red, size: 40),
            const SizedBox(height: 12),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Text(
                _error ?? 'Failed to load Odoo MOs',
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.red),
              ),
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: _load,
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('Retry'),
            ),
          ],
        ),
      );

  Future<void> _link(Map<String, dynamic> chain) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Link order to Odoo MO?'),
        content: Text(
          '${widget.orderLabel} will be linked to ${chain['root_name']} '
          '(state: ${chain['state']}). Linking is link_only and never posts to Odoo '
          'on its own - you must set sync_mode = full separately.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Link')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _busy = true);
    final r = await ApiService.linkOdooOrder(
      (chain['root_id'] as num?)?.toInt() ?? 0,
      localMoId: widget.localOrderId,
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (r != null) {
      Navigator.pop(context, 'linked');
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Link failed: ${ApiService.lastApiDetail ?? 'unknown error'}'),
      ));
    }
  }

  @override
  Widget build(BuildContext context) {
    final shown = (_chains ?? []).cast<Map<String, dynamic>>();
    return AlertDialog(
      title: Text('Link ${widget.orderLabel}'),
      content: SizedBox(
        width: 640,
        height: 440,
        child: Column(children: [
          Row(children: [
            Expanded(
              child: TextField(
                controller: _searchCtrl,
                autofocus: true,
                decoration: const InputDecoration(
                  labelText: 'Search by MO number / Source / Production Order No.',
                  border: OutlineInputBorder(),
                  prefixIcon: Icon(Icons.search),
                ),
                onChanged: (v) => setState(() => _query = v),
                onSubmitted: (_) => _load(),
              ),
            ),
            const SizedBox(width: 8),
            IconButton(onPressed: _load, icon: const Icon(Icons.search)),
          ]),
          const SizedBox(height: 12),
          Expanded(
            child: _error != null
                ? _errorView()
                : _chains == null
                    ? const Center(child: CircularProgressIndicator())
                    : shown.isEmpty
                        ? const Center(child: Text('No Odoo MOs match'))
                        : ListView.builder(
                            itemCount: shown.length,
                            itemBuilder: (context, i) {
                              final c = shown[i];
                              return ListTile(
                                dense: true,
                                title: Text(c['root_name']?.toString() ?? ''),
                                subtitle: Text(
                                  '${c['mo_count']} MO(s) - ${c['total_rods']} rods - started ${c['start'] ?? '?'}',
                                ),
                                leading: stateChip(c['state']?.toString() ?? 'draft'),
                                trailing: TextButton(
                                  onPressed: _busy ? null : () => _link(c),
                                  child: const Text('Link'),
                                ),
                              );
                            },
                          ),
          ),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
      ],
    );
  }
}

class UnlinkedReviewDialog extends StatefulWidget {
  const UnlinkedReviewDialog({super.key});
  @override
  State<UnlinkedReviewDialog> createState() => _UnlinkedReviewDialogState();
}

class _UnlinkedReviewDialogState extends State<UnlinkedReviewDialog> {
  Map<String, dynamic>? _data;
  List<Map<String, dynamic>> _rows = [];
  final Set<int> _skipped = {};
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _data = null;
      _error = null;
    });
    final data = await ApiService.fetchOdooUnlinkedOrders();
    if (!mounted) return;
    setState(() {
      _data = data;
      if (data != null) {
        _rows = (data['review'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
      } else {
        _error = ApiService.lastApiDetail ?? 'Failed to load unlinked orders';
      }
    });
  }

  Widget _errorView() => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, color: Colors.red, size: 40),
            const SizedBox(height: 12),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Text(
                _error ?? 'Failed to load unlinked orders',
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.red),
              ),
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: _load,
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('Retry'),
            ),
          ],
        ),
      );

  void _snack(String message) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _link(Map<String, dynamic> row, Map<String, dynamic> cand) async {
    final risks = (cand['risk'] as List<dynamic>? ?? []).cast<String>();
    final note = risks.isEmpty
        ? 'Links as link_only; nothing is posted to Odoo automatically.'
        : 'Warning: ${risks.join(', ')}. Links as link_only; nothing is posted automatically.';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Link order?'),
        content: Text('${row['po_number']} -> ${cand['root_name']} (${cand['matched_on']}). $note'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Link')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _busy = true);
    final r = await ApiService.linkOdooOrder(
      (cand['root_id'] as num?)?.toInt() ?? 0,
      localMoId: (row['local_mo_id'] as num?)?.toInt(),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    _snack(r == null
        ? 'Link failed: ${ApiService.lastApiDetail ?? 'unknown error'}'
        : 'Linked to ${r['odoo_mo_name']}');
    _load();
  }

  /// Rows that can be linked in bulk: exactly ONE candidate, matched on a code
  /// field (Source / Production Order No. / MO number) and without a quantity
  /// mismatch. Anything ambiguous or heuristic stays a manual decision.
  List<Map<String, dynamic>> _exactRows() {
    return _rows.where((r) {
      if (_skipped.contains(r['local_mo_id'])) return false;
      final cands = (r['candidates'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
      if (cands.length != 1) return false;
      final c = cands.first;
      final risks = (c['risk'] as List<dynamic>? ?? []).cast<String>();
      return c['matched_on'].toString().startsWith('code') && !risks.contains('qty_mismatch');
    }).toList();
  }

  Future<void> _linkAllExact() async {
    final exact = _exactRows();
    if (exact.isEmpty) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Link all exact matches?'),
        content: Text(
          '${exact.length} order(s) have exactly one Odoo MO chain with the same code '
          '(Source / Production Order No. / MO number) and a matching quantity. '
          'They will be linked as link_only; nothing is posted to Odoo.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Link all')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _busy = true);
    var linked = 0;
    final failed = <String>[];
    for (final row in exact) {
      final cand = (row['candidates'] as List<dynamic>).cast<Map<String, dynamic>>().first;
      final r = await ApiService.linkOdooOrder(
        (cand['root_id'] as num?)?.toInt() ?? 0,
        localMoId: (row['local_mo_id'] as num?)?.toInt(),
      );
      if (r != null) {
        linked++;
      } else {
        failed.add('${row['po_number']}: ${ApiService.lastApiDetail ?? 'unknown error'}');
      }
      if (!mounted) return;
    }
    setState(() => _busy = false);
    _snack(failed.isEmpty
        ? 'Linked $linked order(s)'
        : 'Linked $linked, ${failed.length} failed - ${failed.first}');
    _load();
  }

  Future<void> _ignore(Map<String, dynamic> row) async {
    setState(() => _busy = true);
    final ok = await ApiService.ignoreOdooOrder((row['local_mo_id'] as num?)?.toInt() ?? 0);
    if (!mounted) return;
    setState(() => _busy = false);
    _snack(ok
        ? '${row['po_number']} marked as ignored'
        : 'Ignore failed: ${ApiService.lastApiDetail ?? 'unknown error'}');
    _load();
  }

  Future<void> _browse(Map<String, dynamic> row) async {
    final result = await showDialog<String>(
      context: context,
      builder: (_) => OdooMoPickerDialog(
        localOrderId: (row['local_mo_id'] as num?)?.toInt() ?? 0,
        orderLabel: row['po_number']?.toString() ?? '',
        initialQuery: row['po_number']?.toString() ?? '',
      ),
    );
    if (result == 'linked' && mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    final visible = _rows.where((r) => !_skipped.contains(r['local_mo_id'])).toList();
    return AlertDialog(
      title: Row(children: [
        const Text('Unlinked orders'),
        const Spacer(),
        if (_data != null)
          Text(
            '${_data!['matched']?.length ?? 0} code matches, ${_data!['unmatched']?.length ?? 0} need review',
            style: const TextStyle(fontSize: 12, color: Colors.black54),
          ),
      ]),
      content: SizedBox(
        width: 760,
        height: 520,
        child: _error != null
            ? _errorView()
            : _data == null
                ? const Center(child: CircularProgressIndicator())
                : visible.isEmpty
                    ? const Center(child: Text('Nothing left to review'))
                    : ListView.builder(
                        itemCount: visible.length,
                        itemBuilder: (context, i) => _rowCard(visible[i]),
                      ),
      ),
      actions: [
        if (_error == null && _exactRows().isNotEmpty)
          FilledButton.icon(
            onPressed: _busy ? null : _linkAllExact,
            icon: const Icon(Icons.link, size: 18),
            label: Text('Link all exact matches (${_exactRows().length})'),
          ),
        TextButton(onPressed: _busy ? null : _load, child: const Text('Reload')),
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
      ],
    );
  }

  Widget _rowCard(Map<String, dynamic> row) {
    final cands = (row['candidates'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
    final reports = row['reports_from'] == null
        ? 'no reports'
        : '${row['reports_from']} .. ${row['reports_to']}';
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text(row['po_number']?.toString() ?? '',
                style: const TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(width: 10),
            Text('target ${row['target_qty']} rods, $reports',
                style: const TextStyle(fontSize: 12, color: Colors.black54)),
            const Spacer(),
            TextButton(
              onPressed: _busy ? null : () => _ignore(row),
              child: const Text('Ignore'),
            ),
            IconButton(
              tooltip: 'Skip for now',
              onPressed: () => setState(() => _skipped.add((row['local_mo_id'] as num?)?.toInt() ?? 0)),
              icon: const Icon(Icons.visibility_off, size: 18),
            ),
          ]),
          if (cands.isEmpty)
            const Padding(
              padding: EdgeInsets.only(top: 4),
              child: Text('No Odoo MO found - create it in Odoo first, then browse.',
                  style: TextStyle(color: Colors.orange)),
            ),
          for (final c in cands.take(3))
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('${c['root_name']}   (${c['matched_on']})',
                        style: const TextStyle(fontSize: 13)),
                    Text(
                      '${c['mo_count']} MO(s), ${c['total_rods']} rods, state ${c['state']}'
                      '${c['date_gap'] != null ? ", ${c['date_gap']}d from reports" : ""}'
                      '${c['qty_mismatch'] != null ? " - ${c['qty_mismatch']}" : ""}',
                      style: const TextStyle(fontSize: 11, color: Colors.black54),
                    ),
                    riskChips(c['risk'] as List<dynamic>? ?? []),
                  ]),
                ),
                TextButton(
                  onPressed: _busy ? null : () => _link(row, c),
                  child: const Text('Link'),
                ),
              ]),
            ),
          TextButton.icon(
            onPressed: _busy ? null : () => _browse(row),
            icon: const Icon(Icons.search, size: 16),
            label: const Text('Browse Odoo MOs'),
          ),
        ]),
      ),
    );
  }
}
