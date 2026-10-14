// lib/screens/web/odoo_sync_screen.dart
// Odoo ERP integration console: material mapping, order sync mode, shadow log
// and reconciliation. Superadmin only (the endpoints enforce it).
import 'dart:convert';
import 'package:flutter/material.dart';

import '../../api_service.dart';
import 'odoo_review_dialogs.dart';

class OdooSyncScreen extends StatefulWidget {
  const OdooSyncScreen({super.key});
  @override
  State<OdooSyncScreen> createState() => _OdooSyncScreenState();
}

class _OdooSyncScreenState extends State<OdooSyncScreen> {
  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 5,
      child: Column(children: [
        const Material(
          color: Colors.white,
          child: TabBar(
            isScrollable: true,
            labelColor: Colors.deepPurple,
            unselectedLabelColor: Colors.black54,
            tabs: [
              Tab(text: 'Creation Mode'),
              Tab(text: 'Material Mapping'),
              Tab(text: 'Order Sync'),
              Tab(text: 'Shadow Log'),
              Tab(text: 'Reconcile'),
            ],
          ),
        ),
        const Divider(height: 1, thickness: 1),
        const Expanded(
          child: TabBarView(children: [
            _CreationModeTab(),
            _MaterialMappingTab(),
            _OrderSyncTab(),
            _ShadowLogTab(),
            _ReconcileTab(),
          ]),
        ),
      ]),
    );
  }
}

Widget _card(String title, List<Widget> children) => Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.deepPurple)),
          const SizedBox(height: 12),
          ...children,
        ]),
      ),
    );

void _snack(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
}

Widget _errorBanner(String message) => Card(
      margin: const EdgeInsets.only(bottom: 16),
      color: Colors.red.shade50,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(children: [
          const Icon(Icons.error_outline, color: Colors.red),
          const SizedBox(width: 12),
          Expanded(child: Text(message)),
        ]),
      ),
    );


class _CreationModeTab extends StatefulWidget {
  const _CreationModeTab();
  @override
  State<_CreationModeTab> createState() => _CreationModeTabState();
}

class _CreationModeTabState extends State<_CreationModeTab> {
  String _mode = 'hybrid';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final mode = await ApiService.fetchOdooMode();
    if (!mounted) return;
    setState(() {
      if (mode != null) _mode = mode;
    });
  }

  Future<void> _save() async {
    final ok = await ApiService.updateOdooMode(_mode);
    if (!mounted) return;
    _snack(context, ok ? 'Odoo mode saved' : 'Failed to save Odoo mode');
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            _card('Order / Material Creation Mode', [
              RadioListTile<String>(
                value: 'hybrid',
                groupValue: _mode,
                title: const Text('Hybrid (default)'),
                subtitle: const Text('Odoo syncs automatically; manual + New MO / + Add Material remain enabled for offline operation.'),
                onChanged: (v) => setState(() => _mode = v!),
              ),
              RadioListTile<String>(
                value: 'strict',
                groupValue: _mode,
                title: const Text('Strict ERP'),
                subtitle: const Text('Manual creation restricted to superadmin.'),
                onChanged: (v) => setState(() => _mode = v!),
              ),
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerRight,
                child: ElevatedButton.icon(
                  onPressed: _save,
                  icon: const Icon(Icons.save, size: 18),
                  label: const Text('Save Odoo Mode'),
                ),
              ),
            ]),
          ]),
        ),
      ),
    );
  }
}

class _MaterialMappingTab extends StatefulWidget {
  const _MaterialMappingTab();
  @override
  State<_MaterialMappingTab> createState() => _MaterialMappingTabState();
}

class _MaterialMappingTabState extends State<_MaterialMappingTab> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  bool _suggest = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final data = await ApiService.fetchOdooMaterialMapping(suggest: _suggest);
    if (!mounted) return;
    setState(() {
      _data = data;
      _loading = false;
    });
  }

  Future<void> _confirm(int materialId, int? odooProductId, int? uomId, {bool force = false}) async {
    final r = await ApiService.confirmOdooMaterialMapping(
      materialId: materialId, odooProductId: odooProductId, odooUomId: uomId, force: force);
    if (!mounted) return;
    _snack(context, r == null ? 'Failed to save mapping: ${ApiService.lastApiDetail ?? 'unknown error'}' : 'Mapping saved');
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final materials = (_data?['materials'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
    final unmapped = (_data?['unmapped_components'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 960),
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _data == null
                  ? _errorBanner('Failed to load materials: ${ApiService.lastApiDetail ?? 'unknown error'}')
                  : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Row(children: [
                    Expanded(
                      child: Text('${_data?['mapped_count'] ?? 0} of ${_data?['total'] ?? 0} materials mapped',
                        style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                    ),
                    const Text('Fetch Odoo suggestions'),
                    Switch(value: _suggest, onChanged: (v) => setState(() => _suggest = v)),
                    const SizedBox(width: 12),
                    ElevatedButton.icon(
                      onPressed: _load,
                      icon: const Icon(Icons.refresh, size: 18),
                      label: const Text('Reload'),
                    ),
                  ]),
                  const SizedBox(height: 8),
                  for (final m in materials) _materialCard(m),
                  if (unmapped.isNotEmpty)
                    _card('Unmapped BOM components', [
                      for (final u in unmapped)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 2),
                          child: Text('${u['category']}: ${u['product_name']}'),
                        ),
                    ]),
                ]),
        ),
      ),
    );
  }

  Future<void> _pickProduct(Map<String, dynamic> m) async {
    final picked = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _ProductPickerDialog(
        category: m['category']?.toString() ?? '',
        title: '${m['category']} - ${m['type_name']}',
      ),
    );
    if (picked == null || !mounted) return;
    final r = await ApiService.confirmOdooMaterialMapping(
      materialId: m['material_id'] as int,
      odooProductId: (picked['id'] as num?)?.toInt(),
      odooUomId: (picked['uom_id'] as num?)?.toInt(),
    );
    if (!mounted) return;
    _snack(context, r == null ? 'Failed to save mapping: ${ApiService.lastApiDetail ?? 'unknown error'}' : 'Mapping saved');
    _load();
  }

  Widget _materialCard(Map<String, dynamic> m) {
    final mapped = m['mapped'] == true;
    final suggestions = (m['suggestions'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
    return _card('${m['category']} - ${m['type_name']}', [
      if (mapped)
        Row(children: [
          const Icon(Icons.link, size: 16, color: Colors.green),
          const SizedBox(width: 6),
          Text('Odoo product #${m['odoo_product_id']} (uom #${m['odoo_uom_id']})'),
          const Spacer(),
          TextButton(
            onPressed: () => _confirm(m['material_id'] as int, null, null, force: true),
            child: const Text('Unlink'),
          ),
        ])
      else ...[
        if (suggestions.isNotEmpty)
          const Text('Suggestions:',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: Colors.black54)),
        for (final s in suggestions)
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.lightbulb_outline),
            title: Text(s['name']?.toString() ?? ''),
            subtitle: Text('Odoo product #${s['odoo_product_id']} (score ${(s['score'] as num?)?.toStringAsFixed(2)})'),
            trailing: TextButton(
              onPressed: () => _confirm(
                m['material_id'] as int,
                (s['odoo_product_id'] as num?)?.toInt(),
                (s['uom_id'] as num?)?.toInt(),
              ),
              child: const Text('Map'),
            ),
          ),
        Row(children: [
          Expanded(
            child: Text(
              suggestions.isEmpty
                  ? 'No automatic match - pick the Odoo product manually.'
                  : 'Suggestions wrong? Pick the product manually.',
              style: const TextStyle(fontSize: 12, color: Colors.black54),
            ),
          ),
          TextButton.icon(
            onPressed: () => _pickProduct(m),
            icon: const Icon(Icons.search, size: 18),
            label: const Text('Browse products'),
          ),
        ]),
      ],
    ]);
  }
}

class _ProductPickerDialog extends StatefulWidget {
  final String category;
  final String title;
  const _ProductPickerDialog({required this.category, required this.title});
  @override
  State<_ProductPickerDialog> createState() => _ProductPickerDialogState();
}

class _ProductPickerDialogState extends State<_ProductPickerDialog> {
  List<dynamic>? _products;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final products = await ApiService.fetchOdooProducts(category: widget.category);
    if (!mounted) return;
    setState(() => _products = products);
  }

  @override
  Widget build(BuildContext context) {
    final all = (_products ?? []).cast<Map<String, dynamic>>();
    final shown = _query.isEmpty
        ? all
        : all.where((p) => (p['name']?.toString().toLowerCase() ?? '').contains(_query.toLowerCase())).toList();
    return AlertDialog(
      title: Text(widget.title),
      content: SizedBox(
        width: 560,
        height: 420,
        child: Column(children: [
          TextField(
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Search Odoo products',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.search),
            ),
            onChanged: (v) => setState(() => _query = v),
          ),
          const SizedBox(height: 12),
          Expanded(
            child: _products == null
                ? const Center(child: CircularProgressIndicator())
                : shown.isEmpty
                    ? const Center(child: Text('No products found'))
                    : ListView.builder(
                        itemCount: shown.length,
                        itemBuilder: (context, i) {
                          final p = shown[i];
                          final uomCat = p['uom_category']?.toString() ?? '';
                          final expected = widget.category.toLowerCase() == 'paper' ? 'Length' : 'Weight';
                          final mismatch = uomCat.isNotEmpty && !uomCat.toLowerCase().contains(expected.toLowerCase());
                          return ListTile(
                            dense: true,
                            title: Text(p['name']?.toString() ?? ''),
                            subtitle: Text('uom: ${p['uom_name'] ?? '?'} ($uomCat)'),
                            trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                              if (mismatch)
                                const Tooltip(
                                  message: 'UoM category does not match the material - consumption may be skipped',
                                  child: Icon(Icons.warning_amber, color: Colors.orange),
                                ),
                              TextButton(
                                onPressed: () => Navigator.pop(context, p),
                                child: const Text('Link'),
                              ),
                            ]),
                          );
                        },
                      ),
          ),
        ]),
      ),
      actions: [
        TextButton(
          onPressed: _products == null ? null : _load,
          child: const Text('Reload'),
        ),
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
      ],
    );
  }
}

class _OrderSyncTab extends StatefulWidget {
  const _OrderSyncTab();
  @override
  State<_OrderSyncTab> createState() => _OrderSyncTabState();
}

class _OrderSyncTabState extends State<_OrderSyncTab> {
  List<dynamic>? _orders;
  String? _suggestError;
  bool _loading = true;
  bool _suggest = true;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final data = await ApiService.fetchOdooOrdersSync(suggest: _suggest);
    if (!mounted) return;
    setState(() {
      _orders = data?['orders'] as List<dynamic>?;
      _suggestError = data?['suggest_error']?.toString();
      _loading = false;
    });
  }

  List<Map<String, dynamic>> _suggestionsOf(Map<String, dynamic> o) =>
      (o['suggestions'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();

  /// One-click is only safe for a code match (Source / Production Order No. / MO
  /// number) without a quantity mismatch; anything else asks for confirmation.
  bool _isSafe(Map<String, dynamic> s) {
    final risks = (s['risk'] as List<dynamic>? ?? []).cast<String>();
    return s['matched_on'].toString().startsWith('code') && !risks.contains('qty_mismatch');
  }

  Future<bool> _confirmRisky(Map<String, dynamic> o, Map<String, dynamic> s) async {
    final reasons = <String>[
      if (!s['matched_on'].toString().startsWith('code')) 'matched by spec and dates only, not by code',
      if (s['qty_mismatch'] != null) '${s['qty_mismatch']}',
    ];
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Link ${o['po_number']} to ${s['root_name']}?'),
        content: Text('This match needs a human check: ${reasons.join('; ')}.\n\n'
            'Linking is link_only and never posts to Odoo on its own.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Link')),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _linkSuggestion(Map<String, dynamic> o, Map<String, dynamic> s) async {
    if (!_isSafe(s) && !await _confirmRisky(o, s)) return;
    if (!mounted) return;
    setState(() => _busy = true);
    final r = await ApiService.linkOdooOrder(
      (s['root_id'] as num?)?.toInt() ?? 0,
      localMoId: (o['id'] as num?)?.toInt(),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    _snack(context, r == null
        ? 'Link failed: ${ApiService.lastApiDetail ?? 'unknown error'}'
        : '${o['po_number']} linked to ${s['root_name']}');
    _load();
  }

  /// Orders whose FIRST suggestion is safe and which have exactly one suggestion.
  List<Map<String, dynamic>> _exactOrders(List<Map<String, dynamic>> orders) => orders.where((o) {
        if (o['odoo_mo_id'] != null) return false;
        final s = _suggestionsOf(o);
        return s.length == 1 && _isSafe(s.first);
      }).toList();

  Future<void> _linkAllExact(List<Map<String, dynamic>> exact) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Link all exact matches?'),
        content: Text('${exact.length} order(s) have exactly one Odoo MO chain with the same '
            'code and a matching quantity. They will be linked as link_only; nothing is '
            'posted to Odoo.'),
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
    for (final o in exact) {
      final s = _suggestionsOf(o).first;
      final r = await ApiService.linkOdooOrder(
        (s['root_id'] as num?)?.toInt() ?? 0,
        localMoId: (o['id'] as num?)?.toInt(),
      );
      if (r != null) {
        linked++;
      } else {
        failed.add('${o['po_number']}: ${ApiService.lastApiDetail ?? 'unknown error'}');
      }
      if (!mounted) return;
    }
    setState(() => _busy = false);
    _snack(context, failed.isEmpty
        ? 'Linked $linked order(s)'
        : 'Linked $linked, ${failed.length} failed - ${failed.first}');
    _load();
  }

  Future<void> _setMode(int id, String mode) async {
    final ok = await ApiService.setOrderSyncMode(id, mode);
    if (!mounted) return;
    _snack(context, ok ? 'Sync mode updated' : 'Failed to update sync mode: ${ApiService.lastApiDetail ?? 'unknown error'}');
    _load();
  }

  Future<void> _closeOrder(int id, String poNumber) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Close Order $poNumber'),
        content: const Text(
            'Finalize this order: compute cumulative production + consolidated '
            'quality, mark it completed, and (for full-sync orders) push the '
            'summary PDF to Odoo.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Close Order')),
        ],
      ),
    );
    if (confirm != true || !mounted) return;
    final r = await ApiService.closeOrder(id);
    if (!mounted) return;
    _snack(context, r != null
        ? 'Order ${r['po_number']} completed (Odoo attached: ${r['odoo_attached']})'
        : 'Failed to close order: ${ApiService.lastApiDetail ?? 'unknown error'}');
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final orders = _orders?.cast<Map<String, dynamic>>() ?? [];
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 960),
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _orders == null
                  ? _errorBanner('Failed to load orders: ${ApiService.lastApiDetail ?? 'unknown error'}')
                  : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Row(children: [
                    Expanded(
                      child: Text(
                          '${orders.where((o) => o['odoo_mo_id'] != null).length} of ${orders.length} orders linked',
                          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                    ),
                    if (_exactOrders(orders).isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(right: 12),
                        child: FilledButton.icon(
                          onPressed: _busy ? null : () => _linkAllExact(_exactOrders(orders)),
                          icon: const Icon(Icons.link, size: 18),
                          label: Text('Link all exact matches (${_exactOrders(orders).length})'),
                        ),
                      ),
                    const Text('Fetch Odoo suggestions'),
                    Switch(value: _suggest, onChanged: (v) => setState(() => _suggest = v)),
                    const SizedBox(width: 12),
                    ElevatedButton.icon(
                      onPressed: _busy ? null : _load,
                      icon: const Icon(Icons.refresh, size: 18),
                      label: const Text('Reload'),
                    ),
                  ]),
                  const SizedBox(height: 8),
                  if (_suggestError != null)
                    _errorBanner('Could not fetch Odoo suggestions: $_suggestError'),
                  for (final o in orders) _orderCard(o),
                ]),
        ),
      ),
    );
  }

  Widget _orderCard(Map<String, dynamic> o) {
    final state = o['odoo_state']?.toString() ?? 'unlinked';
    final mode = o['sync_mode']?.toString() ?? 'link_only';
    final drift = o['odoo_qty_drift'];
    final linked = o['odoo_mo_id'] != null;
    final suggestions = _suggestionsOf(o);
    return _card('${o['po_number']}', [
      Row(children: [
        _chip(state),
        const SizedBox(width: 8),
        if (linked) Text('MO #${o['odoo_mo_id']} ${o['odoo_mo_name'] ?? ''}'),
        if (drift != null)
          Padding(
            padding: const EdgeInsets.only(left: 8),
            child: Text('qty drift: $drift', style: const TextStyle(color: Colors.orange)),
          ),
      ]),
      if (!linked) ...[
        if (suggestions.isNotEmpty)
          const Text('Suggestions:',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: Colors.black54)),
        for (final s in suggestions)
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: Icon(
              _isSafe(s) ? Icons.lightbulb_outline : Icons.warning_amber_rounded,
              color: _isSafe(s) ? null : Colors.orange,
            ),
            title: Text('${s['root_name']}   (${s['matched_on']})'),
            subtitle: Text(
              '${s['mo_count']} MO(s) - ${s['total_rods']} rods - ${s['state']}'
              '${s['qty_mismatch'] != null ? ' - ${s['qty_mismatch']}' : ''}',
            ),
            trailing: TextButton(
              onPressed: _busy ? null : () => _linkSuggestion(o, s),
              child: const Text('Link'),
            ),
          ),
        Row(children: [
          Expanded(
            child: Text(
              suggestions.isEmpty
                  ? (_suggest
                      ? 'No automatic match - pick the Odoo MO manually.'
                      : 'Suggestions are off - switch them on or pick the Odoo MO manually.')
                  : 'Suggestions wrong? Pick the Odoo MO manually.',
              style: const TextStyle(fontSize: 12, color: Colors.black54),
            ),
          ),
          TextButton.icon(
            onPressed: _busy
                ? null
                : () async {
                    final result = await showDialog<String>(
                      context: context,
                      builder: (_) => OdooMoPickerDialog(
                        localOrderId: (o['id'] as num?)?.toInt() ?? 0,
                        orderLabel: o['po_number']?.toString() ?? '',
                        initialQuery: o['po_number']?.toString() ?? '',
                      ),
                    );
                    if (result == 'linked' && mounted) _load();
                  },
            icon: const Icon(Icons.search, size: 18),
            label: const Text('Browse Odoo MOs...'),
          ),
        ]),
      ],
      if (linked)
        Row(children: [
          const Text('Sync mode:'),
          const SizedBox(width: 12),
          ChoiceChip(
            label: const Text('link_only'),
            selected: mode == 'link_only',
            onSelected: (_) => _setMode(o['id'] as int, 'link_only'),
          ),
          const SizedBox(width: 8),
          ChoiceChip(
            label: const Text('full'),
            selected: mode == 'full',
            onSelected: (_) => _setMode(o['id'] as int, 'full'),
          ),
          const Spacer(),
          TextButton.icon(
            onPressed: _busy ? null : () => _closeOrder(o['id'] as int, '${o['po_number']}'),
            icon: const Icon(Icons.task_alt, size: 18),
            label: const Text('Close Order'),
          ),
        ]),
    ]);
  }

  Widget _chip(String state) {
    final color = switch (state) {
      'open' => Colors.green,
      'done' => Colors.blueGrey,
      'cancel' => Colors.red,
      'check' => Colors.orange,
      'missing' => Colors.deepOrange,
      _ => Colors.grey,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(4)),
      child: Text(state, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
    );
  }
}


class _ShadowLogTab extends StatefulWidget {
  const _ShadowLogTab();
  @override
  State<_ShadowLogTab> createState() => _ShadowLogTabState();
}

class _ShadowLogTabState extends State<_ShadowLogTab> {
  Map<String, dynamic>? _data;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final data = await ApiService.fetchOdooShadowLog();
    if (!mounted) return;
    setState(() {
      _data = data;
      _loading = false;
    });
  }

  Future<void> _requeue() async {
    final r = await ApiService.requeueOdooShadow();
    if (!mounted) return;
    _snack(context, r == null ? 'Requeue failed: ${ApiService.lastApiDetail ?? 'unknown error'}' : 'Requeued ${r['requeued']} items');
    _load();
  }

  Future<void> _toggleShadow(bool value) async {
    final ok = await ApiService.setOdooShadowMode(value);
    if (!mounted) return;
    _snack(context, ok
        ? (value ? 'Shadow mode ON - writes are recorded, not sent' : 'Shadow mode OFF - writes will be sent to Odoo')
        : 'Failed: ${ApiService.lastApiDetail ?? 'unknown error'}');
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final items = (_data?['items'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
    // Tri-state: null = we do not know (fetch failed) - never render a false OFF.
    final shadow = _data == null ? null : _data!['shadow_mode'] == true;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 960),
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _data == null
                  ? _errorBanner('Failed to load shadow state: ${ApiService.lastApiDetail ?? 'unknown error'}')
                  : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  _card('Shadow mode', [
                    Row(children: [
                      Icon(
                        shadow == null
                            ? Icons.help_outline
                            : (shadow ? Icons.visibility_off : Icons.flash_on),
                        color: shadow == null
                            ? Colors.grey
                            : (shadow ? Colors.orange : Colors.green),
                      ),
                      const SizedBox(width: 8),
                      Text(shadow == null
                          ? 'UNKNOWN - could not read shadow state from the server'
                          : (shadow ? 'ON - writes are recorded, not sent' : 'OFF - writes are sent to Odoo')),
                      const Spacer(),
                      Switch(value: shadow ?? false, onChanged: shadow == null ? null : _toggleShadow),
                      const SizedBox(width: 8),
                      ElevatedButton.icon(
                        onPressed: shadow == false ? _requeue : null,
                        icon: const Icon(Icons.replay, size: 18),
                        label: const Text('Requeue shadowed items'),
                      ),
                    ]),
                  ]),
                  for (final item in items) _shadowCard(item),
                ]),
        ),
      ),
    );
  }

  Widget _shadowCard(Map<String, dynamic> item) {
    final actions = item['actions'] as List<dynamic>? ?? [];
    return _card(
      'run #${item['run_id']} to MO #${item['odoo_mo_id']} ${item['link_only'] == true ? '(link_only)' : ''}',
      [
        if (item['note'] != null) Text(item['note'].toString()),
        for (final a in actions)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Text(
              const JsonEncoder.withIndent('  ').convert(a),
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
      ],
    );
  }
}


class _ReconcileTab extends StatefulWidget {
  const _ReconcileTab();
  @override
  State<_ReconcileTab> createState() => _ReconcileTabState();
}

class _ReconcileTabState extends State<_ReconcileTab> {
  bool _busy = false;
  String _cutover = '';
  String _verifyWait = '';
  String _errorRetry = '';
  String _maxAttempts = '';
  String _pollSeconds = '';
  String _reconcileMinutes = '';

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final s = await ApiService.fetchOdooSyncSettings();
    if (mounted && s != null) {
      setState(() {
        _cutover = s['odoo_sync_from_date']?.toString() ?? '';
        _verifyWait = s['odoo_verification_wait_minutes']?.toString() ?? '';
        _errorRetry = s['odoo_error_retry_minutes']?.toString() ?? '';
        _maxAttempts = s['odoo_max_attempts']?.toString() ?? '';
        _pollSeconds = s['odoo_poll_seconds']?.toString() ?? '';
        _reconcileMinutes = s['odoo_reconcile_minutes']?.toString() ?? '';
      });
    }
  }

  Future<void> _reconcile() async {
    setState(() => _busy = true);
    final r = await ApiService.reconcileOdoo();
    if (!mounted) return;
    setState(() => _busy = false);
    _snack(context, r == null
        ? 'Reconcile failed: ${ApiService.lastApiDetail ?? 'unknown error'}'
        : 'Reconciled ${r['checked']} orders, ${r['changed']?.length ?? 0} changed');
  }

  Future<void> _reviewUnlinked() async {
    await showDialog<void>(
      context: context,
      builder: (_) => const UnlinkedReviewDialog(),
    );
  }

  Future<void> _saveSettings() async {
    int? intOrNull(String v) {
      final t = v.trim();
      return t.isEmpty ? null : int.tryParse(t);
    }

    final ok = await ApiService.setOdooSyncSettings({
      'odoo_sync_from_date': _cutover.trim().isEmpty ? null : _cutover.trim(),
      'odoo_verification_wait_minutes': intOrNull(_verifyWait),
      'odoo_error_retry_minutes': intOrNull(_errorRetry),
      'odoo_max_attempts': intOrNull(_maxAttempts),
      'odoo_poll_seconds': intOrNull(_pollSeconds),
      'odoo_reconcile_minutes': intOrNull(_reconcileMinutes),
    });
    if (!mounted) return;
    _snack(context, ok ? 'Settings saved' : 'Failed to save settings');
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            _card('Reconcile linked orders', [
              const Text('Re-reads the Odoo MO chain of every linked order (state, current MO, quantity drift).'),
              const SizedBox(height: 12),
              Align(
                alignment: Alignment.centerRight,
                child: ElevatedButton.icon(
                  onPressed: _busy ? null : _reconcile,
                  icon: const Icon(Icons.sync, size: 18),
                  label: const Text('Run reconcile'),
                ),
              ),
            ]),
            _card('Review unlinked orders', [
              const Text('Proposes Odoo MOs for the existing orders that are not linked yet (read-only).'),
              const SizedBox(height: 12),
              Align(
                alignment: Alignment.centerRight,
                child: ElevatedButton.icon(
                  onPressed: _busy ? null : _reviewUnlinked,
                  icon: const Icon(Icons.search, size: 18),
                  label: const Text('Find matches'),
                ),
              ),
            ]),
            _card('Posting settings', [
              const Text('Runs started before the cutover date are never posted to Odoo (link_only).'),
              const SizedBox(height: 12),
              TextField(
                controller: TextEditingController(text: _cutover),
                onChanged: (v) => _cutover = v,
                decoration: const InputDecoration(
                  labelText: 'Cutover date (YYYY-MM-DD)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: TextEditingController(text: _verifyWait),
                onChanged: (v) => _verifyWait = v,
                decoration: const InputDecoration(
                  labelText: 'Verification retry wait (min, default 10)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: TextEditingController(text: _errorRetry),
                onChanged: (v) => _errorRetry = v,
                decoration: const InputDecoration(
                  labelText: 'Error retry wait (min, default 5)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: TextEditingController(text: _maxAttempts),
                onChanged: (v) => _maxAttempts = v,
                decoration: const InputDecoration(
                  labelText: 'Max attempts (default 5)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: TextEditingController(text: _pollSeconds),
                onChanged: (v) => _pollSeconds = v,
                decoration: const InputDecoration(
                  labelText: 'Dispatcher poll interval (sec, default 30)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: TextEditingController(text: _reconcileMinutes),
                onChanged: (v) => _reconcileMinutes = v,
                decoration: const InputDecoration(
                  labelText: 'Reconcile interval (min, default 10, 0 = off)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              Align(
                alignment: Alignment.centerRight,
                child: ElevatedButton.icon(
                  onPressed: _saveSettings,
                  icon: const Icon(Icons.save, size: 18),
                  label: const Text('Save settings'),
                ),
              ),
            ]),
          ]),
        ),
      ),
    );
  }
}
