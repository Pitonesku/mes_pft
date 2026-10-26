// lib/screens/web/orders_screen.dart
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:printing/printing.dart';
import '../../models.dart';
import '../../app_state.dart';
import '../../api_service.dart';
import '../../features/pdf_export/order_summary_pdf.dart';
import '../../widgets/sync_button.dart';
import '../../widgets/resizable_panel.dart';
import '../../widgets/quality_report_dialog.dart';

class OrdersScreen extends StatefulWidget {
  final User user;
  final String? initialFilter;
  const OrdersScreen({super.key, required this.user, this.initialFilter});
  @override State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  bool _loading = false;
  String _filter = '';
  PurchaseOrder? _selected;
  bool _showAudit = false;
  int? _sortColumnIndex;
  bool _sortAscending = true;
  bool _showArchived = false;
  final Set<int> _checkedIds = {};
  bool _batchArchiving = false;

  @override
  void initState() {
    super.initState();
    if (widget.initialFilter != null) _filter = widget.initialFilter!;
    // Load fresh POs on first frame so direct navigation / F5 don't show a
    // stale or empty AppData.activePOs list.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _refresh();
    });
  }

  bool _matchesAll(PurchaseOrder p, String q) {
    if (q.isEmpty) return true;
    final lq = q.toLowerCase();
    return p.poNumber.toLowerCase().contains(lq) ||
        p.diameter.toString().contains(lq) ||
        p.length.toString().contains(lq) ||
        p.targetQty.toString().contains(lq) ||
        p.producedQty.toString().contains(lq) ||
        p.remainingQty.toString().contains(lq) ||
        p.boxType.toString().contains(lq) ||
        p.acetateType.toLowerCase().contains(lq) ||
        p.paperType.toLowerCase().contains(lq) ||
        p.hmGlueType.toLowerCase().contains(lq) ||
        p.pvaGlueType.toLowerCase().contains(lq) ||
        p.triacetinType.toLowerCase().contains(lq);
  }

  List<PurchaseOrder> get _filtered {
    var list = AppData.activePOs
        .where((p) => _matchesAll(p, _filter))
        .where((p) => _showArchived || !p.isArchived)
        .toList();
    if (_sortColumnIndex != null) {
      list.sort((a, b) {
        Comparable keyA, keyB;
        switch (_sortColumnIndex) {
          case 0: // PO Number
            keyA = a.poNumber;
            keyB = b.poNumber;
            break;
          case 1: // Diameter
            keyA = a.diameter;
            keyB = b.diameter;
            break;
          case 2: // Length
            keyA = a.length;
            keyB = b.length;
            break;
          case 3: // Target
            keyA = a.targetQty;
            keyB = b.targetQty;
            break;
          case 4: // Produced
            keyA = a.producedQty;
            keyB = b.producedQty;
            break;
          case 5: // Remaining
            keyA = a.remainingQty;
            keyB = b.remainingQty;
            break;
          case 6: // Progress
            keyA = a.targetQty > 0 ? (a.producedQty / a.targetQty) : 0.0;
            keyB = b.targetQty > 0 ? (b.producedQty / b.targetQty) : 0.0;
            break;
          case 7: // Visible
            keyA = a.isHidden ? 1 : 0;
            keyB = b.isHidden ? 1 : 0;
            break;
          default:
            keyA = a.poNumber;
            keyB = b.poNumber;
        }
        return _sortAscending
            ? Comparable.compare(keyA, keyB)
            : Comparable.compare(keyB, keyA);
      });
    }
    return list;
  }

  Future<void> _refresh() async {
    setState(() { _loading = true; _selected = null; _checkedIds.clear(); });
    await AppData.loadDataFromServer(forceSync: true);
    setState(() => _loading = false);
  }

  Future<void> _batchArchive() async {
    if (_checkedIds.isEmpty) return;
    setState(() => _batchArchiving = true);
    int success = 0;
    for (final id in _checkedIds) {
      final po = AppData.activePOs.firstWhere((p) => p.id == id,
          orElse: () => AppData.activePOs.first);
      if (po.id != id) continue;
      po.isArchived = true;
      final ok = await ApiService.updatePurchaseOrder(id, po);
      if (ok) success++;
      else po.isArchived = false;
    }
    setState(() {
      _batchArchiving = false;
      _checkedIds.clear();
      if (_selected != null && _selected!.isArchived && !_showArchived) {
        _selected = null;
      }
    });
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Archived $success item(s)'),
        backgroundColor: success > 0 ? Colors.green : Colors.red));
    }
  }

  void _select(PurchaseOrder po) => setState(() {
    _selected = _selected?.id == po.id ? null : po;
    _showAudit = false;
  });

  @override
  Widget build(BuildContext context) {
    final filtered = _filtered;
    final allFilteredIds = filtered.map((p) => p.id).whereType<int>().toSet();
    final allChecked = allFilteredIds.isNotEmpty &&
        allFilteredIds.every((id) => _checkedIds.contains(id));
    final someChecked = _checkedIds.isNotEmpty;

    final mainContent = Padding(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          SizedBox(width: 280,
            child: TextField(
              decoration: const InputDecoration(
                hintText: 'Search all columns...',
                prefixIcon: Icon(Icons.search), isDense: true),
              onChanged: (v) => setState(() { _filter = v; _checkedIds.clear(); }))),
          const Spacer(),
          // â”€â”€ Batch action bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
          if (someChecked) ...[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: Colors.brown.shade50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.brown.shade200)),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Text('${_checkedIds.length} selected',
                  style: TextStyle(fontSize: 13, color: Colors.brown.shade700,
                    fontWeight: FontWeight.w600)),
                const SizedBox(width: 12),
                _batchArchiving
                  ? const SizedBox(width: 18, height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : FilledButton.icon(
                      style: FilledButton.styleFrom(
                        backgroundColor: Colors.brown,
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6)),
                      icon: const Icon(Icons.archive, size: 16),
                      label: const Text('Archive selected', style: TextStyle(fontSize: 13)),
                      onPressed: _batchArchive),
                const SizedBox(width: 8),
                IconButton(
                  icon: const Icon(Icons.close, size: 16),
                  tooltip: 'Clear selection',
                  onPressed: () => setState(() => _checkedIds.clear()),
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(minWidth: 28, minHeight: 28)),
              ]),
            ),
            const SizedBox(width: 12),
          ],
          Row(mainAxisSize: MainAxisSize.min, children: [
            Checkbox(
              value: _showArchived,
              onChanged: (v) => setState(() => _showArchived = v ?? false),
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
            GestureDetector(
              onTap: () => setState(() => _showArchived = !_showArchived),
              child: Text('Show archived',
                style: TextStyle(fontSize: 13,
                  color: _showArchived ? Colors.deepPurple : Colors.grey)),
            ),
            const SizedBox(width: 16),
          Text('${filtered.length} orders',
              style: const TextStyle(color: Colors.grey, fontSize: 13)),
          ]),
          const SizedBox(width: 12),
          IconButton(
            icon: const Icon(Icons.cloud_sync, size: 22, color: Colors.deepPurple),
            tooltip: 'Sync with Odoo',
            onPressed: () => showDialog(
              context: context,
              builder: (_) => const SyncOdooDialog(),
            ),
          ),
          OutlinedButton.icon(
            icon: const Icon(Icons.add, size: 18),
            label: const Text('New MO'),
            onPressed: () => _openPoForm(context, null)),
          const SizedBox(width: 8),
          FilledButton.icon(
            icon: _loading
              ? const SizedBox(width: 16, height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.refresh, size: 18),
            label: const Text('Refresh'),
            onPressed: _loading ? null : _refresh),
        ]),
        const SizedBox(height: 14),
        Expanded(
          child: filtered.isEmpty
            ? const Center(child: Text('No manufacturing orders found'))
            : Card(
              margin: EdgeInsets.zero,
              child: SingleChildScrollView(
                child: SizedBox(
                  width: double.infinity,
                  child: DataTable(
                    showCheckboxColumn: false,
                    sortColumnIndex: _sortColumnIndex,
                    sortAscending: _sortAscending,
                    headingRowColor: WidgetStateProperty.all(const Color(0xFFF5F5F5)),
                    columnSpacing: 18,
                    dataRowColor: WidgetStateProperty.resolveWith((s) {
                      if (s.contains(WidgetState.selected)) {
                        return Colors.deepPurple.withValues(alpha: 0.08);
                      }
                      if (s.contains(WidgetState.hovered)) {
                        return Colors.deepPurple.withValues(alpha: 0.04);
                      }
                      return null;
                    }),
                    columns: [
                      // â”€â”€ Select-all checkbox column â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                      DataColumn(label: Checkbox(
                        tristate: true,
                        value: allChecked ? true : (someChecked ? null : false),
                        onChanged: (v) {
                          setState(() {
                            if (v == true) _checkedIds.addAll(allFilteredIds);
                            else _checkedIds.removeAll(allFilteredIds);
                          });
                        },
                        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      )),
                      DataColumn(
                        label: const Text('MO Number'),
                        onSort: (col, asc) =>
                            setState(() { _sortColumnIndex = col; _sortAscending = asc; }),
                      ),
                      DataColumn(
                        label: const Text('Diameter'),
                        onSort: (col, asc) =>
                            setState(() { _sortColumnIndex = col; _sortAscending = asc; }),
                      ),
                      DataColumn(
                        label: const Text('Length'),
                        onSort: (col, asc) =>
                            setState(() { _sortColumnIndex = col; _sortAscending = asc; }),
                      ),
                      DataColumn(
                        label: const Text('Target'),
                        numeric: true,
                        onSort: (col, asc) =>
                            setState(() { _sortColumnIndex = col; _sortAscending = asc; }),
                      ),
                      DataColumn(
                        label: const Text('Produced'),
                        numeric: true,
                        onSort: (col, asc) =>
                            setState(() { _sortColumnIndex = col; _sortAscending = asc; }),
                      ),
                      DataColumn(
                        label: const Text('Remaining'),
                        numeric: true,
                        onSort: (col, asc) =>
                            setState(() { _sortColumnIndex = col; _sortAscending = asc; }),
                      ),
                      DataColumn(
                        label: const Text('Progress'),
                        onSort: (col, asc) =>
                            setState(() { _sortColumnIndex = col; _sortAscending = asc; }),
                      ),
                       DataColumn(
                         label: const Text('Visible'),
                         onSort: (col, asc) =>
                             setState(() { _sortColumnIndex = col; _sortAscending = asc; }),
                       ),
                       DataColumn(
                         label: const Text('Created on'),
                         onSort: (col, asc) =>
                             setState(() { _sortColumnIndex = col; _sortAscending = asc; }),
                       ),
                     ],
                    rows: filtered.map((po) {
                      final pct = po.targetQty > 0
                        ? (po.producedQty / po.targetQty).clamp(0.0,1.0) : 0.0;
                      final isSel = _selected?.id == po.id;
                      final isChecked = po.id != null && _checkedIds.contains(po.id);
                      return DataRow(
                        selected: isSel,
                        color: isChecked
                          ? WidgetStateProperty.all(Colors.brown.withValues(alpha: 0.07))
                          : null,
                        onSelectChanged: (_) => _select(po),
                        cells: [
                          // â”€â”€ Row checkbox â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                          DataCell(Checkbox(
                            value: isChecked,
                            onChanged: po.id == null ? null : (v) {
                              setState(() {
                                if (v == true) _checkedIds.add(po.id!);
                                else _checkedIds.remove(po.id);
                              });
                            },
                            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                          )),
                          DataCell(Row(mainAxisSize: MainAxisSize.min, children: [
                            Text(po.moNumber, style: TextStyle(
                              fontWeight: FontWeight.w600,
                              color: po.isHidden ? Colors.grey : Colors.deepPurple)),
                            if (po.isOdooLinked) ...[
                              const SizedBox(width: 4),
                              Chip(
                                label: const Text('ODOO', style: TextStyle(fontSize: 9, color: Colors.white, fontWeight: FontWeight.bold)),
                                backgroundColor: Colors.blue,
                                padding: EdgeInsets.zero,
                                visualDensity: VisualDensity.compact,
                                materialTapTargetSize: MaterialTapTargetSize.shrinkWrap),
                            ] else ...[
                              const SizedBox(width: 4),
                              Chip(
                                label: const Text('LOCAL', style: TextStyle(fontSize: 9, color: Colors.white, fontWeight: FontWeight.bold)),
                                backgroundColor: Colors.orange,
                                padding: EdgeInsets.zero,
                                visualDensity: VisualDensity.compact,
                                materialTapTargetSize: MaterialTapTargetSize.shrinkWrap),
                            ],
                          ])),
                          DataCell(Text('${po.diameter} mm',
                            style: const TextStyle(fontSize: 13))),
                          DataCell(Text('${po.length} mm',
                            style: const TextStyle(fontSize: 13))),
                          DataCell(Text(NumberFormat.compact().format(po.targetQty))),
                          DataCell(Text(NumberFormat.compact().format(po.producedQty))),
                          DataCell(Text(NumberFormat.compact().format(po.remainingQty))),
                          DataCell(SizedBox(width: 110,
                            child: Column(mainAxisSize: MainAxisSize.min,
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                LinearProgressIndicator(value: pct,
                                  backgroundColor: Colors.grey[200],
                                  color: pct > 0.9 ? Colors.green : Colors.deepPurple),
                                const SizedBox(height: 2),
                                Text('${(pct*100).toStringAsFixed(1)}%',
                                  style: const TextStyle(fontSize: 10)),
                              ]))),
                          DataCell(Icon(
                            po.isHidden ? Icons.visibility_off : Icons.visibility,
                            size: 18,
                            color: po.isHidden ? Colors.grey : Colors.green)),
                          DataCell(Text(
                            DateFormat('dd MMM yyyy').format(po.createdAt.toLocal()),
                            style: TextStyle(
                              fontSize: 12,
                              color: Colors.grey[600],
                            ),
                          )),
                        ],
                      );
                    }).toList(),
                  ),
                ),
              ),
            ),
        ),
      ]),
    );

    if (_selected == null) {
      return mainContent;
    }

    final detailPanel = _PoDetailPanel(
      po: _selected!,
      showAudit: _showAudit,
      isSuperadmin: widget.user.role == UserRole.superAdmin,
      onClose: () => setState(() => _selected = null),
      onToggleAudit: () => setState(() => _showAudit = !_showAudit),
      onEdit: () => _openPoForm(context, _selected!),
      onDeleted: () { setState(() { AppData.activePOs.remove(_selected!); _selected = null; }); },
      onVisibilityChanged: () => setState(() {}),
    );

    return ResizablePanelLayout(
      initialPanelWidth: 420,
      minPanelWidth: 300,
      maxPanelWidth: 900,
      main: mainContent,
      panel: detailPanel,
    );
  }

  // â”€â”€ Open PO create/edit form dialog â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  Future<void> _openPoForm(BuildContext context, PurchaseOrder? existing) async {
    final result = await showDialog<PurchaseOrder?>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => Dialog(
        insetPadding: const EdgeInsets.all(40),
        child: SizedBox(
          width: 700,
          child: _PoFormDialog(existing: existing),
        ),
      ),
    );
    if (result != null) {
      setState(() {
        if (existing != null) {
          final idx = AppData.activePOs.indexWhere((p) => p.id == existing.id);
          if (idx != -1) AppData.activePOs[idx] = result;
          if (_selected?.id == existing.id) _selected = result;
        } else {
          AppData.activePOs.add(result);
        }
      });
    }
  }
}
// â”€â”€ PO detail side panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class _PoDetailPanel extends StatefulWidget {
  final PurchaseOrder po;
  final bool showAudit;
  final bool isSuperadmin;
  final VoidCallback onClose, onToggleAudit, onEdit, onDeleted, onVisibilityChanged;
  const _PoDetailPanel({
    required this.po, required this.showAudit, required this.isSuperadmin,
    required this.onClose, required this.onToggleAudit, required this.onEdit,
    required this.onDeleted, required this.onVisibilityChanged,
  });
  @override State<_PoDetailPanel> createState() => _PoDetailPanelState();
}

class _PoDetailPanelState extends State<_PoDetailPanel> {
  Map<String, dynamic>? _auditData;
  bool _auditLoading = false;

  @override
  void didUpdateWidget(_PoDetailPanel old) {
    super.didUpdateWidget(old);
    // fetch audit whenever showAudit flips to true or PO changes
    if (widget.showAudit && (!old.showAudit || old.po.id != widget.po.id)) {
      _loadAudit();
    }
  }

  Future<void> _loadAudit() async {
    if (widget.po.id == null) return;
    setState(() => _auditLoading = true);
    final data = await ApiService.getPoAudit(widget.po.id!);
    setState(() { _auditData = data; _auditLoading = false; });
  }

  Widget _row(String label, String value, {Color? vc}) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SizedBox(width: 140, child: Text(label, style: TextStyle(
        fontSize: 12, color: Colors.grey[600], fontWeight: FontWeight.w500))),
      Expanded(child: Text(value, style: TextStyle(
        fontSize: 13, fontWeight: FontWeight.w600, color: vc))),
    ]),
  );

  Widget _sec(String title, List<Widget> ch) => Column(
    crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SizedBox(height: 14),
      Text(title, style: const TextStyle(fontSize: 12,
        fontWeight: FontWeight.bold, color: Colors.deepPurple)),
      const Divider(height: 8),
      ...ch,
    ]);

  @override
  Widget build(BuildContext context) {
    final po = widget.po;
    final pct = po.targetQty > 0
      ? (po.producedQty / po.targetQty).clamp(0.0,1.0) : 0.0;

    return Container(
      width: 380,
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border(left: BorderSide(color: Colors.grey.shade200)),
        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha:0.06),
          blurRadius: 8, offset: const Offset(-2,0))]),
      child: Column(children: [
        // header with action buttons
        Container(
          color: const Color(0xFFF5F5F5),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          child: Row(children: [
            const Icon(Icons.receipt_long, size: 18, color: Colors.deepPurple),
            const SizedBox(width: 6),
            Expanded(child: Row(children: [
              Flexible(child: Text(po.moNumber,
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                overflow: TextOverflow.ellipsis)),
              if (po.isOdooLinked) ...[
                const SizedBox(width: 6),
                Chip(
                  label: const Text('ODOO', style: TextStyle(fontSize: 9, color: Colors.white, fontWeight: FontWeight.bold)),
                  backgroundColor: Colors.blue,
                  padding: EdgeInsets.zero,
                  visualDensity: VisualDensity.compact,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap),
              ] else ...[
                const SizedBox(width: 6),
                Chip(
                  label: const Text('LOCAL', style: TextStyle(fontSize: 9, color: Colors.white, fontWeight: FontWeight.bold)),
                  backgroundColor: Colors.orange,
                  padding: EdgeInsets.zero,
                  visualDensity: VisualDensity.compact,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap),
              ],
            ])),
            // Toggle audit/stats
            IconButton(
              icon: Icon(Icons.bar_chart_rounded, size: 18,
                color: widget.showAudit ? Colors.deepPurple : Colors.grey[600]),
              tooltip: widget.showAudit ? 'Show details' : 'Show statistics',
              onPressed: widget.onToggleAudit,
              padding: EdgeInsets.zero, constraints: const BoxConstraints(minWidth:30, minHeight:30)),
            // Edit
            IconButton(
              icon: const Icon(Icons.edit, size: 18, color: Colors.orange),
              tooltip: 'Edit MO',
              onPressed: widget.onEdit,
              padding: EdgeInsets.zero, constraints: const BoxConstraints(minWidth:30, minHeight:30)),
            // Archive/unarchive
            ActionSyncButton(
              isIcon: true,
              color: Colors.brown,
              successMsg: po.isArchived ? 'MO unarchived' : 'MO archived',
              errorMsg: 'Failed to update archive status',
              onSync: () async {
                po.isArchived = !po.isArchived;
                final ok = await ApiService.updatePurchaseOrder(po.id!, po);
                if (!ok) po.isArchived = !po.isArchived;
                return ok;
              },
              onSuccess: () => setState(() {}),
              child: Icon(po.isArchived ? Icons.unarchive : Icons.archive, size: 18)),
            // Hide/show
            ActionSyncButton(
              isIcon: true,
              color: Colors.blueGrey,
              successMsg: po.isHidden ? 'MO is now visible to operators' : 'MO hidden from operators',
              errorMsg: 'Failed to update visibility',
              onSync: () async {
                po.isHidden = !po.isHidden;
                final ok = await ApiService.updatePurchaseOrder(po.id!, po);
                if (!ok) po.isHidden = !po.isHidden;
                return ok;
              },
              onSuccess: widget.onVisibilityChanged,
              child: Icon(po.isHidden ? Icons.visibility : Icons.visibility_off, size: 18)),
            // Delete
            IconButton(
              icon: const Icon(Icons.delete_outline, size: 18, color: Colors.red),
              tooltip: 'Delete PO',
              onPressed: () => _confirmDelete(context),
              padding: EdgeInsets.zero, constraints: const BoxConstraints(minWidth:30, minHeight:30)),
            // Close
            IconButton(
              icon: const Icon(Icons.close, size: 18),
              onPressed: widget.onClose, tooltip: 'Close',
              padding: EdgeInsets.zero, constraints: const BoxConstraints(minWidth:30, minHeight:30)),
          ]),
        ),
        const Divider(height: 1),
        if (po.isOdooLinked)
          Container(
            color: const Color(0xFFE8F0FE),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            child: Row(children: [
              const Icon(Icons.cloud_done, size: 16, color: Colors.blue),
              const SizedBox(width: 6),
              Expanded(child: Text('Odoo MO: ${po.odooMoName ?? po.moNumber}',
                  style: const TextStyle(fontSize: 12, color: Colors.blue, fontWeight: FontWeight.w600))),
              TextButton(
                onPressed: () async {
                  await ApiService.dispatchOdooNow();
                  if (!mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Dispatched pending quantities to Odoo')));
                },
                child: const Text('Push Pending Quantities', style: TextStyle(fontSize: 12)),
              ),
            ]),
          ),
        Expanded(child: widget.showAudit ? _buildAudit() : _buildDetails(po, pct)),
      ]),
    );
  }

  Widget _buildDetails(PurchaseOrder po, double pct) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: LinearProgressIndicator(value: pct, minHeight: 8,
            backgroundColor: Colors.grey[200],
            color: pct > 0.9 ? Colors.green : Colors.deepPurple)),
          const SizedBox(width: 8),
          Text('${(pct*100).toStringAsFixed(1)}%',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
        ]),
        const SizedBox(height: 4),
        Text('${NumberFormat.compact().format(po.producedQty)} / '
          '${NumberFormat.compact().format(po.targetQty)} pcs',
          style: TextStyle(fontSize: 11, color: Colors.grey[600])),
        if (po.isHidden)
          Container(margin: const EdgeInsets.only(top: 8),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(color: Colors.grey[200],
              borderRadius: BorderRadius.circular(4)),
            child: const Text('Hidden from operators',
              style: TextStyle(fontSize: 11, color: Colors.grey))),
        _sec('General', [
          _row('PO Number',  po.poNumber),
          _row('Created',    po.createdAt.toLocal().toString().split(' ').first),
          _row('Target qty', '${NumberFormat.compact().format(po.targetQty)} pcs'),
          _row('Produced',   '${NumberFormat.compact().format(po.producedQty)} pcs'),
          _row('Remaining',  '${NumberFormat.compact().format(po.remainingQty)} pcs'),
        ]),
        _sec('Filter Specs', [
          _row('Diameter', '${po.diameter} mm'),
          _row('Length',   '${po.length} mm'),
          _row('PD',       '${po.pd}'),
          _row('CU',       '${po.cu}'),
          _row('Weight',   '${po.weight} mg'),
          _row('Box type', '${po.boxType}'),
          if (po.triacetin > 0)
            _row('Triacetin', '${po.triacetin}% ± ${po.triacetinTolerance ?? '-'}'),
        ]),
        _sec('Materials', [
          _row('Acetate',   po.acetateType),
          _row('Paper',     po.paperType),
          _row('PVA Glue',  po.pvaGlueType),
          _row('HM Glue',   po.hmGlueType),
          _row('Triacetin', po.triacetinType),
        ]),
      ]),
    );
  }

  // â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  double _toDouble(dynamic v) {
    if (v == null) return 0.0;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? 0.0;
  }

  int _toInt(dynamic v) {
    if (v == null) return 0;
    if (v is int) return v;
    if (v is num) return v.toInt();
    return int.tryParse(v.toString()) ?? 0;
  }

  // â”€â”€ PDF generation (matches Android audit PDF) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  Future<void> _printMoQualityReport(BuildContext context) async {
    final po = widget.po;
    final d = await ApiService.fetchQualityData(poId: po.id, window: 'po');
    if (!mounted) return;
    if (d == null) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No quality data for this order')));
      return;
    }
    showDialog(
      context: context,
      builder: (_) => QualityReportDialog(data: d, machine: ''),
    );
  }

  Future<void> _generatePdf(BuildContext context) async {
    final data = _auditData;
    final po = widget.po;
    if (data == null || po.id == null) return;

    final quality = await ApiService.fetchQualityData(poId: po.id!, window: 'po');
    final report = (quality?['report'] as Map?)?.cast<String, dynamic>();
    final certificate = (report?['certificate'] as List?) ?? const [];

    final pdfBytes = await OrderSummaryPdfService.build(
      data: data,
      po: po,
      certificate: certificate,
    );

    await Printing.layoutPdf(
      onLayout: (_) => pdfBytes,
      name: 'PO_Audit_${data['po_number'] ?? po.poNumber}.pdf',
    );
  }

  Future<void> _finalizeAndPushSummary() async {
    final po = widget.po;
    final data = _auditData;
    final poId = po.id;
    if (poId == null || data == null) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No audit data available for this order')));
      return;
    }

    // Consolidated quality certificate for the trailing section.
    final quality = await ApiService.fetchQualityData(poId: poId, window: 'po');
    final report = (quality?['report'] as Map?)?.cast<String, dynamic>();
    final certificate = (report?['certificate'] as List?) ?? const [];

    final pdfBytes = await OrderSummaryPdfService.build(
      data: data,
      po: po,
      certificate: certificate,
    );
    final filename = 'Order_Summary_${po.poNumber.replaceAll('/', '-')}.pdf';

    final uploaded = await ApiService.uploadOrderSummaryPdf(
      orderId: poId,
      pdfBytes: pdfBytes,
      filename: filename,
    );
    if (!mounted) return;
    if (!uploaded) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to upload the Order Summary PDF')));
      return;
    }

    final result = await ApiService.closeOrder(poId);
    if (!mounted) return;
    final attached = result?['odoo_attached'] == true;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(attached
          ? 'Order finalized — summary attached to Odoo'
          : 'Order finalized — summary stored locally'),
    ));
    await AppData.loadDataFromServer(forceSync: true);
    if (mounted) setState(() {});
  }

  // â”€â”€ Main audit widget â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  Widget _buildAudit() {
    if (_auditLoading) return const Center(child: CircularProgressIndicator());
    if (_auditData == null) {
      return Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
        const Text('No audit data available'),
        const SizedBox(height: 12),
        FilledButton.icon(icon: const Icon(Icons.refresh),
          label: const Text('Load'), onPressed: _loadAudit),
      ]));
    }

    final data    = _auditData!;
    final totals  = (data['audit_totals']      as Map?)?.cast<String,dynamic>() ?? {};
    final mats    = (data['materials_consumed'] as List?) ?? [];
    final reports = (data['report_rows']        as List?) ?? [];

    // â”€â”€ Compute report table rows + totals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    int totalRods = 0, totalMachineCounter = 0;
    double totalDiff = 0, totalScrap = 0;

    final reportRows = reports.map((r) {
      final rr      = (r as Map).cast<String,dynamic>();
      final rods    = _toInt(rr['produced_rods']);
      final counter = _toInt(rr['machine_counter']);
      final diff    = _toDouble(rr['difference']);
      final diffPct = _toDouble(rr['difference_percent']);
      final scrap   = _toDouble(rr['scrap']);
      totalRods += rods;
      totalMachineCounter += counter;
      totalDiff += diff;
      totalScrap += scrap;
      return DataRow(cells: [
        DataCell(Text(rr['date']?.toString() ?? '-',     style: const TextStyle(fontSize: 11))),
        DataCell(Text(rr['time']?.toString() ?? '-',     style: const TextStyle(fontSize: 11))),
        DataCell(Text(rr['operator']?.toString() ?? '-', style: const TextStyle(fontSize: 11))),
        DataCell(Text(NumberFormat.compact().format(rods))),
        DataCell(Text(NumberFormat.compact().format(counter))),
        DataCell(Text('${diff.toStringAsFixed(0)} (${diffPct.toStringAsFixed(1)}%)',
          style: const TextStyle(fontSize: 11))),
        DataCell(Text(scrap.toStringAsFixed(2))),
      ]);
    }).toList();

    // TOTAL row
    if (reports.isNotEmpty) {
      final totalDiffPct = totalMachineCounter > 0
          ? (totalDiff / totalMachineCounter) * 100 : 0.0;
      reportRows.add(DataRow(
        color: WidgetStateProperty.all(Colors.grey.shade200),
        cells: [
          const DataCell(Text('TOTAL', style: TextStyle(fontWeight: FontWeight.bold))),
          const DataCell(Text('')),
          const DataCell(Text('')),
          DataCell(Text(NumberFormat.compact().format(totalRods),
            style: const TextStyle(fontWeight: FontWeight.bold))),
          DataCell(Text(NumberFormat.compact().format(totalMachineCounter),
            style: const TextStyle(fontWeight: FontWeight.bold))),
          DataCell(Text('${totalDiff.toStringAsFixed(0)} (${totalDiffPct.toStringAsFixed(1)}%)',
            style: const TextStyle(fontWeight: FontWeight.bold))),
          DataCell(Text(totalScrap.toStringAsFixed(2),
            style: const TextStyle(fontWeight: FontWeight.bold))),
        ],
      ));
    }

    // â”€â”€ Summary values â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    final producedQty  = _toInt(data['produced_qty']);
    final targetQty    = _toInt(data['target_qty']);
    final remainingQty = _toInt(data['remaining_qty']);
    final totalBoxes   = _toInt(totals['total_boxes_submitted']);
    final machCounter  = totalMachineCounter > 0
        ? totalMachineCounter : _toInt(totals['total_machine_counter']);
    final diffPcs      = machCounter - producedQty;
    final diffPctSumm  = machCounter > 0 ? (diffPcs / machCounter) * 100 : 0.0;
    final wasteKg      = _toDouble(totals['total_waste_kg']);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [

        // â”€â”€ PO header â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        Text('PO ${data["po_number"] ?? widget.po.poNumber}',
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold,
            color: Colors.deepPurple)),
        const SizedBox(height: 2),
        Text(
          'Spec: ${widget.po.diameter} Ã— ${widget.po.length}  '
          'PD ${widget.po.pd}  CU ${widget.po.cu}',
          style: TextStyle(fontSize: 11, color: Colors.grey[600])),
        Text(
          'Target: ${NumberFormat.decimalPattern().format(targetQty)} pcs',
          style: TextStyle(fontSize: 11, color: Colors.grey[600])),

        // â”€â”€ Report Entries â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _sec('Report Entries', [
          if (reports.isEmpty)
            const Text('No report entries', style: TextStyle(color: Colors.grey))
          else
            _ReportEntriesTable(rows: reportRows),
        ]),

        // â”€â”€ Production Summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _sec('Production Summary', [
          _row('Total rods produced', '${NumberFormat.decimalPattern().format(producedQty)} pcs'),
          _row('Remaining to produce','${NumberFormat.decimalPattern().format(remainingQty)} pcs'),
          _row('Boxes submitted',     '$totalBoxes'),
          _row('Machine counter',     NumberFormat.decimalPattern().format(machCounter)),
          _row('Difference',
            '${NumberFormat.decimalPattern().format(diffPcs)} pcs (${diffPctSumm.toStringAsFixed(2)}%)',
            vc: diffPctSumm.abs() > 1.0 ? Colors.red : null),
          _row('Total scrap waste',   '${wasteKg.toStringAsFixed(1)} kg'),
        ]),

        // â”€â”€ Materials Consumption Details â€” flat table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _sec('Materials Consumption Details', [
          if (mats.isEmpty)
            const Text('No material data', style: TextStyle(color: Colors.grey))
          else
            _MaterialsTable(mats: mats, toDouble: _toDouble),
        ]),

        // â”€â”€ Print PDF button â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            icon: const Icon(Icons.picture_as_pdf),
            label: const Text('Print / Save PDF'),
            style: FilledButton.styleFrom(backgroundColor: Colors.deepPurple),
            onPressed: () => _generatePdf(context),
          ),
        ),
        const SizedBox(height: 8),
        if (widget.isSuperadmin)
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              icon: const Icon(Icons.cloud_upload_outlined),
              label: const Text('Finalize & Push Summary'),
              style: FilledButton.styleFrom(backgroundColor: Colors.green),
              onPressed: () => _finalizeAndPushSummary(),
            ),
          ),
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            icon: const Icon(Icons.description),
            label: const Text('Print MO Quality Report'),
            onPressed: () => _printMoQualityReport(context),
          ),
        ),
        const SizedBox(height: 16),
      ]),
    );
  }

  Future<void> _confirmDelete(BuildContext context) async {
    final ok = await showDialog<bool>(context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete PO?'),
        content: Text('Delete "${widget.po.poNumber}"? This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false),
            child: const Text('CANCEL')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('DELETE', style: TextStyle(color: Colors.white))),
        ],
      ));
    if (ok != true) return;
    final success = await ApiService.deletePurchaseOrder(widget.po.id!);
    if (!mounted) return;
    if (success) {
      widget.onDeleted();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('PO deleted'), backgroundColor: Colors.green));
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Delete failed'), backgroundColor: Colors.red));
    }
  }
}

// â”€â”€ Responsive Report Entries table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Uses LayoutBuilder so columns fill the available panel width instead of
// requiring horizontal scrolling.
class _ReportEntriesTable extends StatelessWidget {
  final List<DataRow> rows;
  const _ReportEntriesTable({required this.rows});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (ctx, constraints) {
      final w = constraints.maxWidth;
      // Column flex widths (proportional)
      final colWidths = [
        w * 0.14, // Date
        w * 0.16, // Time
        w * 0.18, // Operator
        w * 0.13, // Rods
        w * 0.13, // Counter
        w * 0.14, // Diff
        w * 0.12, // Scrap
      ];
      return Table(
        columnWidths: {
          0: FixedColumnWidth(colWidths[0]),
          1: FixedColumnWidth(colWidths[1]),
          2: FixedColumnWidth(colWidths[2]),
          3: FixedColumnWidth(colWidths[3]),
          4: FixedColumnWidth(colWidths[4]),
          5: FixedColumnWidth(colWidths[5]),
          6: FixedColumnWidth(colWidths[6]),
        },
        border: TableBorder(
          horizontalInside: BorderSide(color: Colors.grey.shade200),
          bottom: BorderSide(color: Colors.grey.shade200),
        ),
        children: [
          // Header row
          TableRow(
            decoration: BoxDecoration(color: Colors.grey.shade100),
            children: [
              for (final h in ['Date','Time','Operator','Rods','Counter','Diff','Scrap'])
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
                  child: Text(h, style: const TextStyle(
                    fontSize: 11, fontWeight: FontWeight.bold))),
            ],
          ),
          // Data rows
          for (final row in rows)
            TableRow(
              decoration: row.color != null
                ? BoxDecoration(color: row.color!.resolve({}))
                : null,
              children: row.cells.map((cell) => Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 5),
                child: cell.child,
              )).toList(),
            ),
        ],
      );
    });
  }
}

// â”€â”€ Flat Materials Consumption table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Category | Material Type | Batch | Used
// Total rows (type and category) are shown in bold.
class _MaterialsTable extends StatelessWidget {
  final List<dynamic> mats;
  final double Function(dynamic) toDouble;
  const _MaterialsTable({required this.mats, required this.toDouble});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (ctx, constraints) {
      final w = constraints.maxWidth;
      return Table(
        columnWidths: {
          0: FixedColumnWidth(w * 0.26),
          1: FixedColumnWidth(w * 0.30),
          2: FixedColumnWidth(w * 0.24),
          3: FixedColumnWidth(w * 0.20),
        },
        border: TableBorder(
          horizontalInside: BorderSide(color: Colors.grey.shade200),
          bottom: BorderSide(color: Colors.grey.shade200),
        ),
        children: [
          // Header
          TableRow(
            decoration: BoxDecoration(color: Colors.grey.shade100),
            children: [
              for (final h in ['Category', 'Material Type', 'Batch', 'Used'])
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
                  child: Text(h, style: const TextStyle(
                    fontSize: 11, fontWeight: FontWeight.bold))),
            ],
          ),
          // Data rows
          for (final cat in mats) ..._buildCatRows(cat),
        ],
      );
    });
  }

  List<TableRow> _buildCatRows(dynamic cat) {
    final catMap   = (cat as Map).cast<String, dynamic>();
    final catName  = catMap['category']?.toString() ?? '-';
    final unit     = catMap['unit']?.toString() ?? 'kg';
    final breakdowns = (catMap['breakdown'] as List?) ?? [];
    double catTotal = 0;
    final rows = <TableRow>[];

    for (final typeEntry in breakdowns) {
      final te       = (typeEntry as Map).cast<String, dynamic>();
      final typeName = te['type_name']?.toString() ?? '-';
      final batches  = (te['batches'] as List?) ?? [];
      double typeTotal = 0;

      for (final b in batches) {
        final bm    = (b as Map).cast<String, dynamic>();
        final batch = bm['batch_number']?.toString() ?? 'No Batch';
        final used  = toDouble(bm['consumed'] ?? bm['total_used']);
        typeTotal += used;
        rows.add(TableRow(children: [
          _cell(catName, bold: false),
          _cell(typeName, bold: false),
          _cell(batch, bold: false),
          _cell('${used.toStringAsFixed(1)} $unit', bold: false, align: TextAlign.right),
        ]));
      }
      catTotal += typeTotal;
      // Type subtotal row
      rows.add(TableRow(
        decoration: BoxDecoration(color: Colors.blueGrey.shade50),
        children: [
          _cell('', bold: true),
          _cell('Total $typeName', bold: true),
          _cell('', bold: true),
          _cell('${typeTotal.toStringAsFixed(1)} $unit', bold: true, align: TextAlign.right),
        ],
      ));
    }
    // Category total row
    rows.add(TableRow(
      decoration: BoxDecoration(color: Colors.deepPurple.shade50),
      children: [
        _cell('Total $catName', bold: true),
        _cell('', bold: true),
        _cell('', bold: true),
        _cell('${catTotal.toStringAsFixed(1)} $unit', bold: true, align: TextAlign.right),
      ],
    ));
    return rows;
  }

  Widget _cell(String text, {required bool bold, TextAlign align = TextAlign.left}) =>
    Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 5),
      child: Text(text,
        textAlign: align,
        style: TextStyle(
          fontSize: 11,
          fontWeight: bold ? FontWeight.bold : FontWeight.normal)));
}

// â”€â”€ PO create/edit dialog â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class _PoFormDialog extends StatefulWidget {
  final PurchaseOrder? existing;
  const _PoFormDialog({this.existing});
  @override State<_PoFormDialog> createState() => _PoFormDialogState();
}
class _PoFormDialogState extends State<_PoFormDialog> {
  final _fk = GlobalKey<FormState>();
  late TextEditingController _poNum,_qty,_box,_dia,_len,_pd,_cu,_weight,_diaTol,_pdTol,_triPct,_triTol;
  String? _acetate,_paper,_pva,_hm,_tri;

  @override
  void initState() {
    super.initState();
    final p = widget.existing;
    _poNum  = TextEditingController(text: p?.poNumber ?? '');
    _qty    = TextEditingController(text: p != null ? _fmtK(p.targetQty) : '');
    _box    = TextEditingController(text: p?.boxType.toString() ?? '');
    _dia    = TextEditingController(text: p?.diameter.toString() ?? '');
    _len    = TextEditingController(text: p?.length.toString() ?? '');
    _pd     = TextEditingController(text: p?.pd.toString() ?? '');
    _cu     = TextEditingController(text: p?.cu.toString() ?? '');
    _weight = TextEditingController(text: p?.weight.toString() ?? '');
    _diaTol = TextEditingController(text: p?.diameterTolerance?.toString() ?? '');
    _pdTol  = TextEditingController(text: p?.pdTolerance?.toString() ?? '');
    _triPct = TextEditingController(text: p != null && p.triacetin > 0 ? p.triacetin.toString() : '');
    _triTol = TextEditingController(text: p?.triacetinTolerance?.toString() ?? '');
    _acetate = p?.acetateType; _paper = p?.paperType;
    _pva = p?.pvaGlueType; _hm = p?.hmGlueType; _tri = p?.triacetinType;
    if (p == null) _prefillDefaults();
  }
  @override void dispose() {
    for (final c in [_poNum,_qty,_box,_dia,_len,_pd,_cu,_weight,_diaTol,_pdTol,_triPct,_triTol]) {
      c.dispose();
    }
    super.dispose();
  }
  String _fmtK(int qty) { final k=qty/1000.0; return k==k.truncateToDouble()?k.toInt().toString():k.toStringAsFixed(1); }
  double _pN(String t) => double.tryParse(t.trim().replaceAll(',','.')) ?? 0.0;
  String? _nV(String? v) { if(v==null||v.trim().isEmpty) return 'Required'; if(double.tryParse(v.replaceAll(',','.'))==null) return 'Invalid'; return null; }

  Widget _f(TextEditingController c, String label, {bool n=false}) => TextFormField(
    controller: c,
    decoration: InputDecoration(labelText: label),
    keyboardType: n ? const TextInputType.numberWithOptions(decimal:true) : TextInputType.text,
    validator: n ? _nV : (v) => (v==null||v.trim().isEmpty)?'Required':null,
  );

  Widget _fo(TextEditingController c, String label) => TextFormField(
    controller: c,
    decoration: InputDecoration(labelText: label),
    keyboardType: const TextInputType.numberWithOptions(decimal: true),
    validator: (v) {
      final t = (v ?? '').trim();
      if (t.isEmpty) return null;
      return double.tryParse(t.replaceAll(',', '.')) == null ? 'Invalid' : null;
    },
  );

  Future<void> _prefillDefaults() async {
    final s = await ApiService.fetchQualitySettings();
    if (!mounted) return;
    setState(() {
      if (_diaTol.text.trim().isEmpty) _diaTol.text = '${s?['diameter_tolerance'] ?? ''}';
      if (_pdTol.text.trim().isEmpty) _pdTol.text = '${s?['pd_tolerance'] ?? ''}';
      if (_triPct.text.trim().isEmpty) _triPct.text = '${s?['triacetin_target'] ?? ''}';
      if (_triTol.text.trim().isEmpty) _triTol.text = '${s?['triacetin_tolerance'] ?? ''}';
    });
  }

  Widget _md(String label, MaterialCategory cat, String? val, ValueChanged<String?> onC) {
    final items = AppData.materialDictionary.where((m) => m.category==cat && !m.isHidden).toList();
    if (val!=null && !items.any((m)=>m.type==val)) val=null;
    return DropdownButtonFormField<String>(
      decoration: InputDecoration(labelText: label), initialValue: val,
      items: items.map((m)=>DropdownMenuItem(value:m.type,child:Text(m.type))).toList(),
      onChanged: onC,
      validator: (v)=>v==null||v.isEmpty?'Required':null);
  }

  @override
  Widget build(BuildContext context) {
    PurchaseOrder? pending;
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Container(color: Colors.deepPurple,
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
        child: Row(children: [
          Text(widget.existing==null?'New Purchase Order':'Edit PO',
            style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
          const Spacer(),
          IconButton(icon: const Icon(Icons.close, color: Colors.white),
            onPressed: () => Navigator.pop(context, null)),
        ])),
      Flexible(child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Form(key: _fk, child: Column(
          crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('General', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.blue[800])),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(child: _f(_poNum, 'PO Number *')),
            const SizedBox(width:16),
            Expanded(child: _f(_qty, 'Target (k pcs) *', n: true)),
            const SizedBox(width:16),
            Expanded(child: _f(_box, 'Box Type *', n: true)),
          ]),
          const SizedBox(height:20),
          Text('Tech Specs', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.blue[800])),
          const SizedBox(height:8),
          Row(children: [
            Expanded(child: _f(_dia, 'Diameter *', n: true)),
            const SizedBox(width:16),
            Expanded(child: _f(_len, 'Length *', n: true)),
            const SizedBox(width:16),
            Expanded(child: _f(_pd, 'PD *', n: true)),
            const SizedBox(width:16),
            Expanded(child: _f(_cu, 'CU *', n: true)),
            const SizedBox(width:16),
            Expanded(child: _f(_weight, 'Weight mg *', n: true)),
          ]),
          const SizedBox(height:12),
          Row(children: [
            Expanded(child: _fo(_diaTol, 'Diameter Tol Â± (mm)')),
            const SizedBox(width:16),
            Expanded(child: _fo(_pdTol, 'PD Tol Â± (mm WG)')),
            const SizedBox(width:16),
            Expanded(child: _fo(_triPct, 'Triacetin %')),
            const SizedBox(width:16),
            Expanded(child: _fo(_triTol, 'Triacetin Tol (%)')),
          ]),
          const SizedBox(height:20),
          Text('Materials', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.blue[800])),
          const SizedBox(height:8),
          Row(children: [
            Expanded(child: _md('Acetate *',  MaterialCategory.acetate,  _acetate, (v)=>setState(()=>_acetate=v))),
            const SizedBox(width:16),
            Expanded(child: _md('Paper *',    MaterialCategory.paper,    _paper,   (v)=>setState(()=>_paper=v))),
            const SizedBox(width:16),
            Expanded(child: _md('PVA Glue *', MaterialCategory.coldGlue, _pva,     (v)=>setState(()=>_pva=v))),
          ]),
          const SizedBox(height:12),
          Row(children: [
            Expanded(child: _md('HM Glue *',   MaterialCategory.hotMelt,   _hm,  (v)=>setState(()=>_hm=v))),
            const SizedBox(width:16),
            Expanded(child: _md('Triacetin *',  MaterialCategory.triacetin, _tri, (v)=>setState(()=>_tri=v))),
            const SizedBox(width:16),
            const Expanded(child: SizedBox()),
          ]),
          const SizedBox(height:24),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            TextButton(onPressed: () => Navigator.pop(context, null),
              child: const Text('CANCEL')),
            const SizedBox(width:12),
            ActionSyncButton(
              color: Colors.blue,
              successMsg: widget.existing==null?'PO created':'PO updated',
              errorMsg: 'Error - check fields or server connection',
              onSync: () async {
                if (!_fk.currentState!.validate()) return false;
                pending = PurchaseOrder(
                  id: widget.existing?.id,
                  poNumber: _poNum.text.trim(),
                  createdAt: widget.existing?.createdAt ?? DateTime.now(),
                  diameter: _pN(_dia.text), length: _pN(_len.text),
                  pd: _pN(_pd.text), weight: _pN(_weight.text),
                  cu: int.tryParse(_cu.text)??0, boxType: int.tryParse(_box.text)??0,
                  diameterTolerance: _diaTol.text.trim().isEmpty ? null : _pN(_diaTol.text),
                  pdTolerance: _pdTol.text.trim().isEmpty ? null : _pN(_pdTol.text),
                  triacetin: _pN(_triPct.text),
                  triacetinTolerance: _triTol.text.trim().isEmpty ? null : _pN(_triTol.text),
                  targetQty: ((_pN(_qty.text))*1000).round(),
                  acetateType: _acetate??'', paperType: _paper??'',
                  pvaGlueType: _pva??'', hmGlueType: _hm??'', triacetinType: _tri??'',
                  producedQty: widget.existing?.producedQty??0,
                  isHidden: widget.existing?.isHidden??false,
                );
                if (widget.existing==null) {
                  final created = await ApiService.addPurchaseOrder(pending!);
                  if (created==null) return false;
                  pending = created; return true;
                } else {
                  return await ApiService.updatePurchaseOrder(widget.existing!.id!, pending!);
                }
              },
              onSuccess: () => Navigator.pop(context, pending),
              child: Text(widget.existing==null?'CREATE ORDER':'SAVE CHANGES',

                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
            ),
          ]),
        ])),
      )),
    ]);
  }
}

// â”€â”€ On-demand Odoo sync dialog â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class SyncOdooDialog extends StatefulWidget {
  const SyncOdooDialog({super.key});
  @override
  State<SyncOdooDialog> createState() => _SyncOdooDialogState();
}

class _SyncOdooDialogState extends State<SyncOdooDialog> {
  String _scope = 'active';
  bool _busy = false;
  Map<String, dynamic>? _result;
  final Map<int, int?> _linkSelections = {};

  Future<void> _sync() async {
    setState(() => _busy = true);
    final r = await ApiService.syncOdooOrders(scope: _scope);
    if (!mounted) return;
    setState(() { _busy = false; _result = r; });
  }

  Future<void> _link(int odooMoId, {int? localMoId}) async {
    await ApiService.linkOdooOrder(odooMoId, localMoId: localMoId);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Order linked')));
    await _sync();
  }

  Widget _specBadge(Map<String, dynamic> u, int? localId) {
    final spec = u['spec'];
    if (localId == null || spec == null) return const SizedBox.shrink();
    PurchaseOrder? local;
    for (final p in AppData.activePOs) {
      if (p.id == localId) { local = p; break; }
    }
    if (local == null) return const SizedBox.shrink();
    final dia = (spec['diameter'] as num?)?.toDouble();
    final len = (spec['length'] as num?)?.toDouble();
    final pd = (spec['pd'] as num?)?.toDouble();
    final diaOk = dia == null || (local.diameter - dia).abs() < 0.05;
    final lenOk = len == null || (local.length - len).abs() < 0.5;
    final pdOk = pd == null || (local.pd - pd).abs() < 1.0;
    final ok = diaOk && lenOk && pdOk;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(color: ok ? Colors.green.shade50 : Colors.amber.shade100, borderRadius: BorderRadius.circular(4)),
      child: Text(ok ? 'Specs Verified' : '⚠️ Spec Mismatch', style: TextStyle(fontSize: 10, color: ok ? Colors.green.shade800 : Colors.orange.shade900, fontWeight: FontWeight.w600)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final unmatched = (_result?['unmatched'] as List?) ?? [];
    final localOrders = AppData.activePOs;
    return AlertDialog(
      title: const Text('Sync with Odoo'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Scope', style: TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            DropdownButtonFormField<String>(
              initialValue: _scope,
              items: const [
                DropdownMenuItem(value: 'active', child: Text('Active / Open MOs only')),
                DropdownMenuItem(value: '7d', child: Text('Last 7 Days')),
                DropdownMenuItem(value: '30d', child: Text('Last 30 Days')),
                DropdownMenuItem(value: 'custom', child: Text('Custom Date Range')),
              ],
              onChanged: (v) => setState(() => _scope = v ?? 'active'),
            ),
            const SizedBox(height: 16),
            if (_result != null) ...[
              Text('Linked existing: ${_result!['linked_existing']}   Â·   Created new: ${_result!['created_new']}',
                  style: const TextStyle(fontWeight: FontWeight.w600, color: Colors.deepPurple)),
              if (unmatched.isNotEmpty) ...[
                const SizedBox(height: 12),
                const Text('Unmatched â€” map or create:', style: TextStyle(fontWeight: FontWeight.w600)),
                for (final u in unmatched)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(children: [
                      Expanded(child: Text('${u['name']}${u['origin'] != null && u['origin'] != '' ? '  (origin: ${u['origin']})' : ''}',
                          style: const TextStyle(fontSize: 12))),
                      DropdownButton<int>(
                        hint: const Text('Map to localâ€¦', style: TextStyle(fontSize: 12)),
                        value: _linkSelections[u['odoo_mo_id']],
                        items: [
                          for (final p in localOrders)
                            DropdownMenuItem(value: p.id, child: Text(p.moNumber, style: const TextStyle(fontSize: 12))),
                        ],
                        onChanged: (v) => setState(() => _linkSelections[u['odoo_mo_id']] = v),
                      ),
                      _specBadge(u, _linkSelections[u['odoo_mo_id']]),
                      TextButton(
                        onPressed: () => _link(u['odoo_mo_id'], localMoId: _linkSelections[u['odoo_mo_id']]),
                        child: const Text('Link')),
                      TextButton(onPressed: () => _link(u['odoo_mo_id']), child: const Text('Create new')),
                    ]),
                  ),
              ],
            ],
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
        FilledButton.icon(
          onPressed: _busy ? null : _sync,
          icon: _busy
              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.cloud_sync, size: 18),
          label: Text(_result == null ? 'Start Sync' : 'Re-sync'),
        ),
      ],
    );
  }
}

