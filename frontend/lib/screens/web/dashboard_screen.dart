// lib/screens/web/dashboard_screen.dart
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../models.dart';
import '../../api_service.dart';
import '../../app_state.dart';
import '../../widgets/resizable_panel.dart';
import '../../widgets/report_detail_panel.dart';

class DashboardScreen extends StatefulWidget {
  final User user;
  const DashboardScreen({super.key, required this.user});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  bool _loading = true;
  int _totalReports = 0, _totalRods = 0, _openPOs = 0;
  double _totalWaste = 0;
  List<Map<String, dynamic>> _recentReports = [];
  Map<String, dynamic>? _selectedReport;

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() { _loading = true; _selectedReport = null; });
    try {
      final now   = DateTime.now();
      final start = now.subtract(const Duration(days: 30));
      final reports = (await ApiService.fetchReports(
          startDate: start, endDate: now) ?? []).cast<Map<String, dynamic>>();
      int rods = 0; double waste = 0;
      for (final r in reports) {
        rods  += (r['produced_rods'] as num? ?? 0).toInt();
        waste += (r['waste_kg']      as num? ?? 0).toDouble();
      }
      setState(() {
        _totalReports = reports.length;
        _totalRods    = rods;
        _totalWaste   = waste;
        _openPOs      = AppData.activePOs.where((p) => !p.isHidden).length;
        _recentReports = reports.take(8).cast<Map<String, dynamic>>().toList();
        _loading = false;
      });
    } catch (_) { setState(() => _loading = false); }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());

    final mainContent = RefreshIndicator(
      onRefresh: _load,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text("Welcome, ${widget.user.name}",
            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
          Text(DateFormat("EEEE, d MMMM yyyy").format(DateTime.now()),
            style: TextStyle(fontSize: 13, color: Colors.grey[600])),
          const SizedBox(height: 24),
          LayoutBuilder(builder: (ctx, constraints) {
            final cols = constraints.maxWidth > 900 ? 4 : 2;
            return GridView.count(
              crossAxisCount: cols, shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisSpacing: 16, mainAxisSpacing: 16, childAspectRatio: 2.2,
              children: [
                _KpiCard("Total Reports", "$_totalReports",
                  Icons.description, Colors.blue),
                _KpiCard("Rods Produced",
                  NumberFormat.compact().format(_totalRods),
                  Icons.precision_manufacturing, Colors.green),
                _KpiCard("Total Waste",
                  "${_totalWaste.toStringAsFixed(1)} kg",
                  Icons.delete_outline, Colors.orange),
                _KpiCard("Open POs", "$_openPOs",
                  Icons.receipt_long, Colors.purple),
              ],
            );
          }),
          const SizedBox(height: 32),
          const Text("Recent Reports",
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const SizedBox(height: 12),
          Card(
            margin: EdgeInsets.zero,
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                showCheckboxColumn: false,
                headingRowColor: WidgetStateProperty.all(const Color(0xFFF5F5F5)),
                columnSpacing: 20,
                dataRowColor: WidgetStateProperty.resolveWith((states) {
                  if (states.contains(WidgetState.selected)) {
                    return Colors.deepPurple.withValues(alpha: 0.08);
                  }
                  if (states.contains(WidgetState.hovered)) {
                    return Colors.deepPurple.withValues(alpha: 0.04);
                  }
                  return null;
                }),
                columns: const [
                  DataColumn(label: Text("Date")),
                  DataColumn(label: Text("Shift")),
                  DataColumn(label: Text("Machine")),
                  DataColumn(label: Text("Operator")),
                  DataColumn(label: Text("PO")),
                  DataColumn(label: Text("Rods Produced"), numeric: true),
                  DataColumn(label: Text("Submitted")),
                ],
                rows: _recentReports.map((r) {
                  final isSel = _selectedReport != null &&
                      _selectedReport!['id'] == r['id'];
                  // Format sync_at timestamp
                  String submitted = '-';
                  try {
                    final raw = r['sync_at']?.toString();
                    if (raw != null && raw.isNotEmpty) {
                      submitted = DateFormat('dd MMM HH:mm')
                          .format(DateTime.parse(raw).toLocal());
                    }
                  } catch (_) {}
                  return DataRow(
                    selected: isSel,
                    onSelectChanged: (_) =>
                      setState(() => _selectedReport = isSel ? null : r),
                    cells: [
                      DataCell(Text(r["report_date"] ?? "")),
                      DataCell(Text(r["shift_name"]  ?? "")),
                      DataCell(Text(r["machine_name"] ?? "")),
                      DataCell(Text(r["operator_name"] ?? "")),
                      DataCell(Text(r["po_number"] ?? "",
                        style: const TextStyle(
                          fontWeight: FontWeight.w600,
                          color: Colors.deepPurple))),
                      DataCell(Text("${r["produced_rods"] ?? 0}")),
                      DataCell(Text(submitted,
                        style: const TextStyle(fontSize: 12, color: Colors.grey))),
                    ],
                  );
                }).toList(),
              ),
            ),
          ),
        ]),
      ),
    );

    if (_selectedReport == null) {
      return mainContent;
    }

    return ResizablePanelLayout(
      initialPanelWidth: 420,
      minPanelWidth: 300,
      maxPanelWidth: 900,
      main: mainContent,
      panel: ReportDetailPanel(
        report: _selectedReport!,
        onClose: () => setState(() => _selectedReport = null),
      ),
    );
  }
}

class _KpiCard extends StatelessWidget {
  final String label, value;
  final IconData icon;
  final Color color;
  const _KpiCard(this.label, this.value, this.icon, this.color);
  @override
  Widget build(BuildContext context) => Card(
    margin: EdgeInsets.zero,
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      child: Row(children: [
        CircleAvatar(
          backgroundColor: color.withValues(alpha: 0.12),
          child: Icon(icon, color: color, size: 22)),
        const SizedBox(width: 14),
        Column(crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.center, children: [
          Text(label, style: TextStyle(fontSize: 11, color: Colors.grey[600],
            fontWeight: FontWeight.w500)),
          Text(value, style: const TextStyle(
            fontSize: 20, fontWeight: FontWeight.bold)),
        ]),
      ]),
    ),
  );
}
