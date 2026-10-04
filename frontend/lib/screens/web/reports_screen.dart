
// lib/screens/web/reports_screen.dart
// Columns: Date | Shift | Machine | Operator | PO | Submitted | Status
// Clicking a row opens a detail side-panel with all report fields.
// All columns are sortable. Search bar searches across all columns.
// Batch archive: select multiple rows with checkboxes, then click "Archive selected".
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../models.dart';
import '../../api_service.dart';
import '../../widgets/resizable_panel.dart';
import '../../widgets/report_detail_panel.dart';

class ReportsScreen extends StatefulWidget {
  final User user;
  const ReportsScreen({super.key, required this.user});
  @override State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  List<Map<String, dynamic>> _reports = [];
  bool _loading = true;
  String _filter = '';
  DateTimeRange? _dateRange;
  Map<String, dynamic>? _selected;
  int? _sortColumnIndex;
  bool _sortAscending = true;
  bool _showArchived = false;
  final Set<int> _checkedIds = {};
  bool _batchArchiving = false;

  @override void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() { _loading = true; _selected = null; _checkedIds.clear(); });
    final now   = DateTime.now();
    final start = _dateRange?.start ?? now.subtract(const Duration(days: 90));
    final end   = _dateRange?.end   ?? now;
    final raw   = await ApiService.fetchReports(startDate: start, endDate: end);
    setState(() {
      _reports = (raw ?? []).cast<Map<String, dynamic>>();
      _loading = false;
    });
  }

  bool _matchesAll(Map<String, dynamic> r, String q) {
    if (q.isEmpty) return true;
    final lq = q.toLowerCase();
    return (r['report_date'] ?? '').toString().toLowerCase().contains(lq) ||
        (r['shift_name'] ?? '').toString().toLowerCase().contains(lq) ||
        (r['machine_name'] ?? '').toString().toLowerCase().contains(lq) ||
        (r['operator_name'] ?? '').toString().toLowerCase().contains(lq) ||
        (r['po_number'] ?? '').toString().toLowerCase().contains(lq) ||
        _fmtSync(r['sync_at']).toLowerCase().contains(lq) ||
        (r['status'] ?? '').toString().toLowerCase().contains(lq);
  }

  List<Map<String, dynamic>> get _filtered {
    var list = _reports
        .where((r) => _matchesAll(r, _filter))
        .where((r) => _showArchived || (r['is_archived'] != true))
        .toList();
    if (_sortColumnIndex != null) {
      list.sort((a, b) {
        Comparable keyA, keyB;
        switch (_sortColumnIndex) {
          case 0: keyA = (a['report_date'] ?? '').toString(); keyB = (b['report_date'] ?? '').toString(); break;
          case 1: keyA = (a['shift_name'] ?? '').toString();  keyB = (b['shift_name'] ?? '').toString();  break;
          case 2: keyA = (a['machine_name'] ?? '').toString();keyB = (b['machine_name'] ?? '').toString();break;
          case 3: keyA = (a['operator_name'] ?? '').toString();keyB = (b['operator_name'] ?? '').toString();break;
          case 4: keyA = (a['po_number'] ?? '').toString();   keyB = (b['po_number'] ?? '').toString();   break;
          case 5: keyA = (a['sync_at'] ?? '').toString();     keyB = (b['sync_at'] ?? '').toString();     break;
          case 6: keyA = (a['status'] ?? '').toString();      keyB = (b['status'] ?? '').toString();      break;
          default: keyA = (a['report_date'] ?? '').toString(); keyB = (b['report_date'] ?? '').toString();
        }
        return _sortAscending ? Comparable.compare(keyA, keyB) : Comparable.compare(keyB, keyA);
      });
    }
    return list;
  }

  String _fmtSync(dynamic raw) {
    if (raw == null) return '-';
    try { return DateFormat('dd MMM HH:mm').format(DateTime.parse(raw.toString()).toLocal()); }
    catch (_) { return raw.toString(); }
  }

  // ── Batch archive ──────────────────────────────────────────────────────────
  Future<void> _batchArchive() async {
    if (_checkedIds.isEmpty) return;
    setState(() => _batchArchiving = true);
    int success = 0;
    for (final id in _checkedIds) {
      final ok = await ApiService.archiveReport(id, true);
      if (ok) {
        success++;
        final idx = _reports.indexWhere((r) => r['id'] == id);
        if (idx != -1) _reports[idx]['is_archived'] = true;
      }
    }
    setState(() {
      _batchArchiving = false;
      _checkedIds.clear();
      if (_selected != null && _selected!['is_archived'] == true && !_showArchived) {
        _selected = null;
      }
    });
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Archived $success item(s)'),
        backgroundColor: success > 0 ? Colors.green : Colors.red));
    }
  }

  // ── Single-item archive (from detail panel) ────────────────────────────────
  Future<void> _archiveSelected() async {
    if (_selected == null) return;
    final id = _selected!['id'] as int?;
    if (id == null) return;
    final currentlyArchived = _selected!['is_archived'] == true;
    final ok = await ApiService.archiveReport(id, !currentlyArchived);
    if (ok) {
      setState(() {
        _selected!['is_archived'] = !currentlyArchived;
        final idx = _reports.indexWhere((r) => r['id'] == id);
        if (idx != -1) _reports[idx]['is_archived'] = !currentlyArchived;
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(!currentlyArchived ? 'Report archived' : 'Report unarchived'),
          backgroundColor: Colors.green));
      }
    } else {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Failed to update archive status'),
          backgroundColor: Colors.red));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _filtered;
    final allFilteredIds = filtered
        .map((r) => r['id'] as int?)
        .whereType<int>()
        .toSet();
    final allChecked = allFilteredIds.isNotEmpty &&
        allFilteredIds.every((id) => _checkedIds.contains(id));
    final someChecked = _checkedIds.isNotEmpty;

    final mainContent = Padding(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // ── filter bar ─────────────────────────────────────────────────
        Row(children: [
          SizedBox(width: 240,
            child: TextField(
              decoration: const InputDecoration(
                hintText: 'Search all columns...',
                prefixIcon: Icon(Icons.search), isDense: true),
              onChanged: (v) => setState(() { _filter = v; _checkedIds.clear(); }))),
          const SizedBox(width: 12),
          OutlinedButton.icon(
            icon: const Icon(Icons.date_range, size: 18),
            label: Text(_dateRange == null ? 'Last 90 days'
              : '${DateFormat("dd MMM").format(_dateRange!.start)}'
                ' - ${DateFormat("dd MMM").format(_dateRange!.end)}'),
            onPressed: () async {
              final p = await showDateRangePicker(
                context: context,
                firstDate: DateTime(2025), lastDate: DateTime.now(),
                initialDateRange: _dateRange);
              if (p != null) { setState(() { _dateRange = p; _checkedIds.clear(); }); _load(); }
            }),
          if (_dateRange != null) ...[
            const SizedBox(width: 4),
            IconButton(icon: const Icon(Icons.clear, size: 18),
              tooltip: 'Clear',
              onPressed: () { setState(() { _dateRange = null; _checkedIds.clear(); }); _load(); }),
          ],
          const Spacer(),
          // ── Batch action bar (visible when rows are checked) ──────────
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
            Text('${filtered.length} records',
              style: const TextStyle(color: Colors.grey, fontSize: 13)),
          ]),
          const SizedBox(width: 12),
          FilledButton.icon(icon: const Icon(Icons.refresh, size: 18),
            label: const Text('Refresh'), onPressed: _load),
        ]),
        const SizedBox(height: 14),
        // ── data table ─────────────────────────────────────────────────
        Expanded(
          child: _loading
            ? const Center(child: CircularProgressIndicator())
            : filtered.isEmpty
              ? const Center(child: Text('No records found'))
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
                      dataRowColor: WidgetStateProperty.resolveWith((states) {
                        if (states.contains(WidgetState.selected)) {
                          return Colors.deepPurple.withValues(alpha: 0.08);
                        }
                        if (states.contains(WidgetState.hovered)) {
                          return Colors.deepPurple.withValues(alpha: 0.04);
                        }
                        return null;
                      }),
                      columns: [
                        // ── Select-all checkbox column ──────────────────
                        DataColumn(label: Checkbox(
                          tristate: true,
                          value: allChecked ? true : (someChecked ? null : false),
                          onChanged: (v) {
                            setState(() {
                              if (v == true) {
                                _checkedIds.addAll(allFilteredIds);
                              } else {
                                _checkedIds.removeAll(allFilteredIds);
                              }
                            });
                          },
                          materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        )),
                        DataColumn(label: const Text('Date'),
                          onSort: (col, asc) => setState(() { _sortColumnIndex = col; _sortAscending = asc; })),
                        DataColumn(label: const Text('Shift'),
                          onSort: (col, asc) => setState(() { _sortColumnIndex = col; _sortAscending = asc; })),
                        DataColumn(label: const Text('Machine'),
                          onSort: (col, asc) => setState(() { _sortColumnIndex = col; _sortAscending = asc; })),
                        DataColumn(label: const Text('Operator'),
                          onSort: (col, asc) => setState(() { _sortColumnIndex = col; _sortAscending = asc; })),
                        DataColumn(label: const Text('PO'),
                          onSort: (col, asc) => setState(() { _sortColumnIndex = col; _sortAscending = asc; })),
                        DataColumn(label: const Text('Submitted'),
                          onSort: (col, asc) => setState(() { _sortColumnIndex = col; _sortAscending = asc; })),
                        DataColumn(label: const Text('Status'),
                          onSort: (col, asc) => setState(() { _sortColumnIndex = col; _sortAscending = asc; })),
                      ],
                      rows: filtered.map((r) {
                        final id = r['id'] as int?;
                        final isChecked = id != null && _checkedIds.contains(id);
                        final isSel = _selected != null && _selected!['id'] == r['id'];
                        return DataRow(
                          selected: isSel,
                          color: isChecked
                            ? WidgetStateProperty.all(Colors.brown.withValues(alpha: 0.07))
                            : null,
                          onSelectChanged: (_) =>
                            setState(() => _selected = isSel ? null : r),
                          cells: [
                            // ── Row checkbox ──────────────────────────
                            DataCell(Checkbox(
                              value: isChecked,
                              onChanged: id == null ? null : (v) {
                                setState(() {
                                  if (v == true) _checkedIds.add(id);
                                  else _checkedIds.remove(id);
                                });
                              },
                              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                            )),
                             DataCell(Row(children: [
                               if (r['is_archived'] == true)
                                 const Padding(
                                   padding: EdgeInsets.only(right: 4),
                                   child: Icon(Icons.archive, size: 13, color: Colors.brown)),
                               Text(r['report_date'] ?? '',
                                 style: TextStyle(
                                   fontSize: 13,
                                   color: r['is_archived'] == true ? Colors.grey : null,
                                   fontStyle: r['is_archived'] == true ? FontStyle.italic : null)),
                             ])),
                             DataCell(Text(r['shift_name']    ?? '', style: TextStyle(fontSize: 13, color: r['is_archived'] == true ? Colors.grey : null))),
                             DataCell(Text(r['machine_name']  ?? '', style: TextStyle(fontSize: 13, color: r['is_archived'] == true ? Colors.grey : null))),
                             DataCell(Text(r['operator_name'] ?? '', style: TextStyle(fontSize: 13, color: r['is_archived'] == true ? Colors.grey : null))),
                             DataCell(Text(r['po_number'] ?? '',
                               style: TextStyle(fontSize: 13,
                                 fontWeight: FontWeight.w600,
                                 color: r['is_archived'] == true ? Colors.grey : Colors.deepPurple))),
                             DataCell(Text(_fmtSync(r['sync_at']),
                               style: const TextStyle(fontSize: 12, color: Colors.grey))),
                             DataCell(_StatusChip(r['status'] ?? 'original')),
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

    if (_selected == null) return mainContent;

    return ResizablePanelLayout(
      initialPanelWidth: 420,
      minPanelWidth: 300,
      maxPanelWidth: 900,
      main: mainContent,
      panel: ReportDetailPanel(
        report: _selected!,
        onClose: () => setState(() => _selected = null),
        onArchiveToggle: () => _archiveSelected(),
      ),
    );
  }
}

// ── Status chip ──────────────────────────────────────────────────────────────
class _StatusChip extends StatelessWidget {
  final String status;
  const _StatusChip(this.status);
  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      'edited'   => Colors.orange,
      'obsolete' => Colors.red,
      _          => Colors.green,
    };
    return Chip(
      label: Text(status, style: const TextStyle(fontSize: 11, color: Colors.white)),
      backgroundColor: color, padding: EdgeInsets.zero,
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap);
  }
}
