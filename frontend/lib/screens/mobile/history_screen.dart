import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:printing/printing.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:pdf/pdf.dart';
import 'package:path_provider/path_provider.dart';
import '../../api_service.dart';
import '../../local_db.dart';
import 'package:intl/intl.dart';
import '../../models.dart';
import '../../widgets/dev_banner.dart';
import 'operator_screen.dart';
import '../../sync_manager.dart';

class HistoryScreen extends StatefulWidget {
  final User operator;

  const HistoryScreen({super.key, required this.operator});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  List<dynamic> _reports = [];
  bool _isLoading = true;
  DateTimeRange _selectedRange = DateTimeRange(
    start: DateTime.now().subtract(const Duration(days: 3)),
    end: DateTime.now(),
  );
  int _selectedTab = 0; // 0 = Server, 1 = Local

  @override
  void initState() {
    super.initState();
    _loadHistory();
  }

  Future<void> _loadHistory() async {
    setState(() => _isLoading = true);

    if (_selectedTab == 0) {
      List<dynamic>? serverData;
      try {
        serverData = await ApiService.fetchReports(
          startDate: _selectedRange.start,
          endDate: _selectedRange.end,
        );
      } catch (_) {
        serverData = null;
      }

      if (serverData != null && serverData.isNotEmpty) {
        setState(() {
          _reports = serverData!;
          _isLoading = false;
        });
      } else {
        final filtered = await _loadLocalFiltered();
        setState(() {
          _reports = filtered;
          _isLoading = false;
        });
      }
    } else {
      final filtered = await _loadLocalFiltered();
      setState(() {
        _reports = filtered;
        _isLoading = false;
      });
    }
  }

  Future<List<Map<String, dynamic>>> _loadLocalFiltered() async {
    final allLocal = await LocalDB.instance.getAllReports();
    final rangeStart = _selectedRange.start;
    final rangeEnd = _selectedRange.end.add(const Duration(days: 1));
    final List<Map<String, dynamic>> parsedLocal = [];
    for (final r in allLocal) {
      try {
        final raw = r['report_data'];
        Map<String, dynamic> data;
        if (raw is String) {
          data = jsonDecode(raw) as Map<String, dynamic>;
        } else {
          data = raw as Map<String, dynamic>;
        }
        data['status'] ??= r['status'] ?? 'pending';
        data['id'] ??= r['id'];
        data['_local_status'] = r['status'] as String? ?? 'pending';
        data['_sync_attempts'] = r['sync_attempts'] as int? ?? 0;
        data['_last_sync_error'] = r['last_sync_error'] as String?;
        parsedLocal.add(data);
      } catch (_) {}
    }

    return parsedLocal.where((data) {
      try {
        final dateStr = data['report_date']?.toString() ?? data['shift_date']?.toString() ?? '';
        if (dateStr.isEmpty) return true;
        final date = DateTime.tryParse(dateStr);
        if (date == null) return true;
        return date.isAfter(rangeStart.subtract(const Duration(days: 1))) &&
            date.isBefore(rangeEnd);
      } catch (_) {
        return true;
      }
    }).toList();
  }

  Future<void> _selectDateRange() async {
    final picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime.now().subtract(const Duration(days: 365)),
      lastDate: DateTime.now(),
      initialDateRange: _selectedRange,
    );

    if (picked != null) {
      setState(() {
        _selectedRange = picked;
      });
      await _loadHistory();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Production History"),
        backgroundColor: Colors.deepPurple,
        foregroundColor: Colors.white,
        bottom: const DevBannerBar(),
        actions: [
          IconButton(
            icon: const Icon(Icons.date_range),
            tooltip: 'Select date range',
            onPressed: _selectDateRange,
          ),
          IconButton(
            icon: const Icon(Icons.sync),
            tooltip: "Force Sync",
            onPressed: () async {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text("Syncing with server...")),
              );
              await SyncManager.syncReports();
              _loadHistory();
            },
          ),
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadHistory),
        ],
      ),
      body: Column(
        children: [
          // Tab bar: Server | Local
          Container(
            margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: BoxDecoration(
              color: Colors.grey[200],
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                Expanded(
                  child: GestureDetector(
                    onTap: () {
                      setState(() => _selectedTab = 0);
                      _loadHistory();
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      decoration: BoxDecoration(
                        color: _selectedTab == 0 ? Colors.deepPurple : Colors.transparent,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        "Server",
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: _selectedTab == 0 ? Colors.white : Colors.black54,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ),
                ),
                Expanded(
                  child: GestureDetector(
                    onTap: () {
                      setState(() => _selectedTab = 1);
                      _loadHistory();
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      decoration: BoxDecoration(
                        color: _selectedTab == 1 ? Colors.deepPurple : Colors.transparent,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        "Local",
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: _selectedTab == 1 ? Colors.white : Colors.black54,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          _isLoading
              ? const Expanded(child: Center(child: CircularProgressIndicator()))
              : Expanded(
                  child: Column(
                    children: [
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              "Range: ${DateFormat('dd.MM.yyyy').format(_selectedRange.start)} — ${DateFormat('dd.MM.yyyy').format(_selectedRange.end)}",
                              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
                            ),
                            Text(
                              "${_reports.length} reports",
                              style: const TextStyle(fontSize: 12, color: Colors.grey),
                            ),
                          ],
                        ),
                      ),
                      Expanded(
                        child: _reports.isEmpty
                            ? const Center(
                                child: Text(
                                  "No reports found",
                                  style: TextStyle(fontSize: 18, color: Colors.grey),
                                ),
                              )
                            : ListView.builder(
                                itemCount: _reports.length,
                                padding: const EdgeInsets.all(8),
                                itemBuilder: (context, index) {
                                  final reportData = _reports[index] as Map<String, dynamic>;
                                  final effectiveStatus = reportData['status']?.toString() ?? 'synced';
                                  final localStatus = reportData['_local_status'] as String?;
                                  final date = DateTime.tryParse(
                                        reportData['report_date']?.toString() ?? '',
                                      ) ??
                                      DateTime.now();
                                  final savedOperatorName =
                                      reportData['operator_name']?.toString() ?? 'Unknown';
                                  final recordId = reportData['id'] as int? ?? 0;

                                  return Card(
                                    elevation: 2,
                                    margin: const EdgeInsets.symmetric(vertical: 6, horizontal: 4),
                                    child: ListTile(
                                      leading: _getStatusIcon(effectiveStatus),
                                      title: Row(
                                        children: [
                                          Expanded(
                                            child: Text(
                                              "PO: ${reportData['po_number'] ?? 'N/A'}${effectiveStatus == 'edited' ? ' (EDITED)' : ''}",
                                              style: const TextStyle(fontWeight: FontWeight.bold),
                                            ),
                                          ),
                                          if (localStatus == 'pending')
                                            Container(
                                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                              decoration: BoxDecoration(
                                                color: Colors.orange.shade100,
                                                borderRadius: BorderRadius.circular(4),
                                              ),
                                              child: const Text(
                                                "Not sent",
                                                style: TextStyle(fontSize: 10, color: Colors.deepOrange),
                                              ),
                                            ),
                                        ],
                                      ),
                                      subtitle: Text(
                                        "Machine: ${reportData['machine_name'] ?? 'N/A'}\n"
                                        "Date: ${DateFormat('dd.MM.yyyy').format(date)}  Shift: ${reportData['shift_name'] ?? 'N/A'}\n"
                                        "Operator: $savedOperatorName${effectiveStatus == 'edited' ? ' • EDITED' : ''}\n"
                                        "Submitted: ${_formatSubmittedAt(reportData)}",
                                      ),
                                      isThreeLine: true,
                                      trailing: const Icon(Icons.chevron_right),
                                      onTap: () {
                                        _showFullDetails(reportData, effectiveStatus, recordId, savedOperatorName);
                                      },
                                    ),
                                  );
                                },
                              ),
                      ),
                    ],
                  ),
                ),
        ],
      ),
    );
  }

  String _formatSubmittedAt(Map<String, dynamic> data) {
    final syncAt = data['sync_at']?.toString() ?? '';
    if (syncAt.isNotEmpty) {
      final dt = DateTime.tryParse(syncAt);
      if (dt != null) return DateFormat('dd.MM.yyyy HH:mm').format(dt.toLocal());
    }
    return 'N/A';
  }

  Widget _getStatusIcon(String status) {
    switch (status) {
      case 'synced':
        return const Icon(Icons.check_circle, color: Colors.green, size: 36);
      case 'pending':
        return const Icon(Icons.cloud_upload, color: Colors.orange, size: 36);
      case 'draft':
        return const Icon(Icons.edit_note, color: Colors.blue, size: 36);
      case 'obsolete':
        return const Icon(Icons.cancel, color: Colors.grey, size: 36);
      case 'edited':
        return const Icon(Icons.edit, color: Colors.purple, size: 36);
      default:
        return const Icon(Icons.help_outline, color: Colors.grey, size: 36);
    }
  }

  void _showFullDetails(
    Map<String, dynamic> data,
    String effectiveStatus,
    int localId,
    String? savedOperator,
  ) {
    final localStatus = data['_local_status'] as String?;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.8,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        builder: (_, controller) => Container(
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
          ),
          padding: const EdgeInsets.all(20),
          child: ListView(
            controller: controller,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    "Report Details",
                    style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: Colors.deepPurple),
                  ),
                  Row(
                    children: [
                      IconButton(
                        icon: const Icon(Icons.print, color: Colors.black54),
                        tooltip: 'Print / Save PDF',
                        onPressed: () => _printReportPdf(data),
                      ),
                      _getStatusIcon(effectiveStatus),
                    ],
                  ),
                ],
              ),
              // Pending status banner
              if (localStatus == 'pending')
                Container(
                  margin: const EdgeInsets.only(top: 8, bottom: 4),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: Colors.orange.shade50,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.orange.shade300),
                  ),
                  child: const Row(
                    children: [
                      Icon(Icons.info_outline, color: Colors.deepOrange, size: 20),
                      SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          "This report has not been sent to the server yet. It will be sent automatically when the network is available.",
                          style: TextStyle(fontSize: 13, color: Colors.deepOrange),
                        ),
                      ),
                    ],
                  ),
                ),
              if (effectiveStatus == 'edited')
                Padding(
                  padding: const EdgeInsets.only(top: 8.0, bottom: 4.0),
                  child: Text(
                    'EDITED REPORT',
                    style: const TextStyle(color: Colors.purple, fontWeight: FontWeight.bold),
                  ),
                ),
              const Divider(thickness: 2),

              _buildDetailRow("Operator", savedOperator ?? "Unknown"),
              _buildDetailRow("Date", () {
                final dateStr = data['report_date']?.toString() ?? data['shift_date']?.toString() ?? '';
                final dt = DateTime.tryParse(dateStr);
                return dt != null ? DateFormat('dd.MM.yyyy').format(dt) : dateStr;
              }()),
              _buildDetailRow("Shift", "${data['shift_name']} (${data['shift_time_range'] ?? ''})"),
              _buildDetailRow("Machine", data['machine_name']),
              _buildDetailRow("PO Number", data['po_number']),

              const SizedBox(height: 16),
              const Text("Technical Specs", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.blueGrey)),
              const Divider(),
              _buildDetailRow("Lot Number", data['lot_number']),
              _buildDetailRow("Box Type", data['box_type'].toString()),
              _buildDetailRow("Diameter / Length", "${data['diameter']} / ${data['length']}"),
              _buildDetailRow("PD / Weight", "${data['pd']} / ${data['weight']}"),

              const SizedBox(height: 16),
              const Text("Production Output", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.blueGrey)),
              const Divider(),
              _buildDetailRow("Boxes Produced", data['boxes_produced'].toString()),
              _buildDetailRow("Produced Rods", data['produced_rods'].toString()),
              _buildDetailRow("Machine Counter", data['machine_counter'].toString()),
              _buildDetailRow("Difference", "${data['difference']} (${data['diff_percent']})"),
              _buildDetailRow("Waste (kg)", data['waste_kg'].toString()),
              _buildDetailRow("Efficiency (%)", data['machine_efficiency'].toString()),

              const SizedBox(height: 16),
              const Text("Materials Used (Total)", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.blueGrey)),
              const Divider(),
              _buildDetailRow("Acetate", data['total_acetate']?.toString() ?? "0.0"),
              _buildDetailRow("Paper", data['total_paper']?.toString() ?? "0.0"),
              _buildDetailRow("PVA Glue", data['total_pva']?.toString() ?? "0.0"),
              _buildDetailRow("Hot Melt Glue", data['total_hm']?.toString() ?? "0.0"),
              _buildDetailRow("Triacetin", data['total_triacetin']?.toString() ?? "0.0"),

              const SizedBox(height: 16),
              const Text("Material Breakdown", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.blueGrey)),
              const Divider(),
              _buildDetailMaterialSection("Acetate", data['acetate_list'] as List<dynamic>?),
              _buildDetailMaterialSection("Paper", data['paper_list'] as List<dynamic>?),
              _buildDetailMaterialSection("PVA Glue", data['pva_list'] as List<dynamic>?),
              _buildDetailMaterialSection("Hot Melt Glue", data['hm_list'] as List<dynamic>?),
              _buildDetailMaterialSection("Triacetin", data['tri_list'] as List<dynamic>?),

              const SizedBox(height: 16),
              const Text("Remarks", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.blueGrey)),
              const Divider(),
              Text(
                data['remarks']?.isNotEmpty == true ? data['remarks'] : "No comments.",
                style: const TextStyle(fontSize: 14, fontStyle: FontStyle.italic),
              ),
              if (data['edited_by'] != null) ...[
                const SizedBox(height: 16),
                const Text("Edit Metadata", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.blueGrey)),
                const Divider(),
                _buildDetailRow("Edited By", data['edited_by']?.toString()),
                _buildDetailRow("Edited At", data['edited_at']?.toString()),
              ],
              const SizedBox(height: 24),
              // EDIT button: only for synced reports (not pending)
              if (effectiveStatus == 'synced' &&
                  (widget.operator.role == UserRole.superAdmin || savedOperator == widget.operator.name))
                OutlinedButton.icon(
                  icon: const Icon(Icons.edit, color: Colors.blue),
                  label: const Text("EDIT REPORT"),
                  style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: Colors.blue),
                    minimumSize: const Size(double.infinity, 50),
                  ),
                  onPressed: () {
                    Navigator.pop(context);
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) => ReportPage(
                          operator: widget.operator,
                          initialData: data,
                          localId: localId,
                          initialStatus: effectiveStatus,
                        ),
                      ),
                    ).then((_) => _loadHistory());
                  },
                ),
              // DELETE button: only for drafts (not pending, not synced)
              if (effectiveStatus == 'draft' && savedOperator == widget.operator.name)
                OutlinedButton.icon(
                  icon: const Icon(Icons.delete_forever, color: Colors.red),
                  label: const Text("DELETE DRAFT", style: TextStyle(color: Colors.red)),
                  style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: Colors.red),
                    minimumSize: const Size(double.infinity, 50),
                  ),
                  onPressed: () async {
                    await LocalDB.instance.deleteReport(localId);
                    if (context.mounted) {
                      Navigator.pop(context);
                      _loadHistory();
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text("Draft deleted")),
                      );
                    }
                  },
                ),
              const SizedBox(height: 20),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDetailRow(String label, String? value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.grey, fontSize: 14)),
          Text(value ?? "-", style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
        ],
      ),
    );
  }

  Widget _buildDetailMaterialSection(String title, List<dynamic>? items) {
    if (items == null || items.isEmpty) return const SizedBox();

    List<Widget> children = [];
    children.add(Text(title, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15, color: Colors.blueGrey)));
    children.add(const SizedBox(height: 6));

    children.add(Row(
      children: const [
        Expanded(flex: 4, child: Text('Material Type', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey, fontSize: 13))),
        Expanded(flex: 2, child: Text('Batch', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey, fontSize: 13))),
        Expanded(flex: 2, child: Text('Start', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey, fontSize: 13))),
        Expanded(flex: 2, child: Text('Stop', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey, fontSize: 13))),
        Expanded(flex: 2, child: Text('Used', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey, fontSize: 13), textAlign: TextAlign.right)),
      ],
    ));
    children.add(const SizedBox(height: 4));

    double overallTotal = 0.0;

    for (final it in items) {
      final String type = (it['type'] ?? it['material_type'] ?? 'Unknown').toString().trim();
      final String batch = (it['batch'] != null && it['batch'].toString().trim().isNotEmpty)
          ? it['batch'].toString().trim()
          : 'No Batch';
      final String start = it['start']?.toString().trim().isNotEmpty == true ? it['start'].toString() : '-';
      final String stop = it['stop']?.toString().trim().isNotEmpty == true ? it['stop'].toString() : '-';

      double used = 0.0;
      if (it.containsKey('used') && it['used'] != null) {
        used = double.tryParse(it['used'].toString().replaceAll(',', '.')) ?? 0.0;
      } else {
        final startValue = double.tryParse(it['start']?.toString().replaceAll(',', '.') ?? '') ?? 0.0;
        final stopValue = double.tryParse(it['stop']?.toString().replaceAll(',', '.') ?? '') ?? 0.0;
        used = startValue - stopValue;
      }

      overallTotal += used;

      children.add(Padding(
        padding: const EdgeInsets.symmetric(vertical: 2.0),
        child: Row(
          children: [
            Expanded(flex: 4, child: Text(type)),
            Expanded(flex: 2, child: Text(batch)),
            Expanded(flex: 2, child: Text(start)),
            Expanded(flex: 2, child: Text(stop)),
            Expanded(flex: 2, child: Text(used.toStringAsFixed(2), textAlign: TextAlign.right)),
          ],
        ),
      ));
    }

    children.add(const Divider());
    children.add(Padding(
      padding: const EdgeInsets.only(top: 4.0),
      child: Row(
        children: [
          Expanded(flex: 4, child: Text('Overall Total', style: const TextStyle(fontWeight: FontWeight.bold))),
          const Expanded(flex: 2, child: SizedBox()),
          const Expanded(flex: 2, child: SizedBox()),
          const Expanded(flex: 2, child: SizedBox()),
          Expanded(flex: 2, child: Text(overallTotal.toStringAsFixed(2), textAlign: TextAlign.right, style: const TextStyle(fontWeight: FontWeight.bold))),
        ],
      ),
    ));

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: children);
  }

  Future<void> _printReportPdf(Map<String, dynamic> data) async {
    final pdf = pw.Document();

    pdf.addPage(
      pw.MultiPage(
        pageFormat: PdfPageFormat.a4,
        build: (context) {
          List<pw.Widget> rows = [];

          void addRow(String label, String value) {
            rows.add(pw.Row(
              mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
              children: [
                pw.Expanded(child: pw.Text(label, style: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 10))),
                pw.Text(value, style: pw.TextStyle(fontSize: 10)),
              ],
            ));
            rows.add(pw.SizedBox(height: 4));
          }

          void addSection(String title) {
            rows.add(pw.SizedBox(height: 12));
            rows.add(pw.Text(title, style: pw.TextStyle(fontSize: 12, fontWeight: pw.FontWeight.bold)));
            rows.add(pw.Divider());
          }

          addSection('General Info');
          addRow('Operator', data['operator_name'] ?? 'Unknown');
          final dateStr = data['report_date']?.toString() ?? data['shift_date']?.toString() ?? '';
          final reportDt = DateTime.tryParse(dateStr);
          addRow('Date', reportDt != null ? DateFormat('dd.MM.yyyy').format(reportDt) : dateStr);
          addRow('Shift', '${data['shift_name']} (${data['shift_time_range'] ?? ''})');
          addRow('Machine', data['machine_name'] ?? 'Unknown');
          addRow('PO Number', data['po_number'] ?? 'Unknown');
          addRow('Lot Number', data['lot_number'] ?? '');

          addSection('PO Specifications');
          addRow('Box Type', data['box_type'].toString());
          addRow('Diameter / Length', '${data['diameter']} / ${data['length']}');
          addRow('PD / Weight', '${data['pd']} / ${data['weight']}');

          addSection('Production Log');
          addRow('Boxes Produced', data['boxes_produced'].toString());
          addRow('Produced Rods', data['produced_rods'].toString());
          addRow('Machine Counter', data['machine_counter'].toString());
          addRow('Difference', '${data['difference']} (${data['diff_percent']})');
          addRow('Waste (kg)', data['waste_kg'].toString());
          addRow('Efficiency (%)', data['machine_efficiency'].toString());

          addSection('Total Materials');
          addRow('Acetate', data['total_acetate']?.toString() ?? '0.0');
          addRow('Paper', data['total_paper']?.toString() ?? '0.0');
          addRow('PVA Glue', data['total_pva']?.toString() ?? '0.0');
          addRow('Hot Melt Glue', data['total_hm']?.toString() ?? '0.0');
          addRow('Triacetin', data['total_triacetin']?.toString() ?? '0.0');

          void addMaterials(String title, List<dynamic>? items) {
            if (items == null || items.isEmpty) return;
            addSection(title);

            double toDouble(dynamic v) {
              if (v == null) return 0.0;
              if (v is num) return v.toDouble();
              return double.tryParse(v.toString()) ?? 0.0;
            }

            double overall = 0.0;
            final List<List<String>> table = [];
            table.add(['Material Type', 'Batch', 'Start', 'Stop', 'Used']);

            for (final it in items) {
              final String type = (it['type'] ?? it['material_type'] ?? 'Unknown').toString().trim();
              final String batch = (it['batch']?.toString().trim().isNotEmpty == true) ? it['batch'].toString().trim() : 'No Batch';
              final String start = it['start']?.toString().trim().isNotEmpty == true ? it['start'].toString() : '-';
              final String stop = it['stop']?.toString().trim().isNotEmpty == true ? it['stop'].toString() : '-';
              final double used = it.containsKey('used') && it['used'] != null ? toDouble(it['used']) : (toDouble(it['start']) - toDouble(it['stop']));
              overall += used;
              table.add([type, batch, start, stop, used.toStringAsFixed(2)]);
            }

            table.add(['', 'Overall Total', '', '', overall.toStringAsFixed(2)]);

            rows.add(pw.Table.fromTextArray(
              headers: table.first,
              data: table.sublist(1),
              headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 9),
              cellStyle: pw.TextStyle(fontSize: 9),
              cellAlignment: pw.Alignment.centerLeft,
              headerDecoration: const pw.BoxDecoration(color: PdfColors.grey300),
            ));
            rows.add(pw.SizedBox(height: 6));
          }

          addMaterials('Acetate', data['acetate_list'] as List<dynamic>?);
          addMaterials('Paper', data['paper_list'] as List<dynamic>?);
          addMaterials('PVA Glue', data['pva_list'] as List<dynamic>?);
          addMaterials('Hot Melt Glue', data['hm_list'] as List<dynamic>?);
          addMaterials('Triacetin', data['tri_list'] as List<dynamic>?);

          addSection('Remarks');
          rows.add(pw.Text(
            data['remarks']?.toString().isNotEmpty == true ? data['remarks'] : 'No comments.',
            style: pw.TextStyle(fontSize: 10),
          ));

          if (data['edited_by'] != null) {
            addSection('Edit Metadata');
            addRow('Edited By', data['edited_by'] ?? '');
            addRow('Edited At', data['edited_at'] ?? '');
          }

          return [pw.Header(level: 0, text: 'Production Report'), ...rows];
        },
      ),
    );

    final pdfBytes = await pdf.save();
    await _savePdfLocally(pdfBytes, data);
    await Printing.layoutPdf(onLayout: (format) => pdf.save());
  }

  Future<void> _savePdfLocally(List<int> pdfBytes, Map<String, dynamic> data) async {
    try {
      final directory = await getApplicationDocumentsDirectory();
      final reportsDir = Directory('${directory.path}/reports');
      if (!await reportsDir.exists()) {
        await reportsDir.create(recursive: true);
      }

      final dateStr = data['report_date']?.toString() ?? data['shift_date']?.toString() ?? '';
      final dt = DateTime.tryParse(dateStr) ?? DateTime.now();
      final dateFormatted = DateFormat('yyyy.MM.dd').format(dt);
      final po = (data['po_number'] ?? 'PO').toString().replaceAll(RegExp(r'[^\w]'), '_');
      final machine = (data['machine_name'] ?? 'Machine').toString().replaceAll(RegExp(r'[^\w]'), '_');
      final shift = (data['shift_name'] ?? 'Shift').toString().replaceAll(RegExp(r'[^\w]'), '_');
      final fileName = '${dateFormatted}_${po}_${machine}_$shift.pdf';

      final file = File('${reportsDir.path}/$fileName');
      await file.writeAsBytes(pdfBytes);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✅ PDF saved: $fileName'),
            backgroundColor: Colors.green,
            duration: const Duration(seconds: 4),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('❌ Error saving PDF: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }
}