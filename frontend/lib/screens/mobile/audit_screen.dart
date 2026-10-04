import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';
import 'package:intl/intl.dart';

import '../../api_service.dart';
import '../../local_db.dart';
import '../../models.dart';
import '../../app_state.dart';
import '../../utils/logger.dart';

class AuditPage extends StatefulWidget {
  final PurchaseOrder? initialPO;

  const AuditPage({super.key, this.initialPO});

  @override
  State<AuditPage> createState() => _AuditPageState();
}

class _AuditPageState extends State<AuditPage> {
  PurchaseOrder? _selectedPO;
  Map<String, dynamic>? _auditData;
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    if (widget.initialPO != null) {
      _selectedPO = widget.initialPO;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _fetchAudit(widget.initialPO!);
      });
    }
  }

  Future<void> _fetchAudit(PurchaseOrder po) async {
    setState(() {
      _selectedPO = po;
      _isLoading = true;
    });

    Map<String, dynamic>? data;
    if (po.id != null) {
      AppLog.d('AuditPage: fetching server audit for PO id ${po.id}');
      data = await ApiService.getPoAudit(po.id!);
      if (data != null) {
        AppLog.d(
          'AuditPage: server audit response keys: ${data.keys.toList()}',
        );
        data = _normalizeServerAuditData(data, po);
      } else {
        AppLog.w('AuditPage: server audit failed for PO id ${po.id}');
      }
    } else {
      AppLog.w('AuditPage: PO id is null, cannot request server audit');
    }

    if (data == null) {
      AppLog.d('AuditPage: falling back to local DB for PO ${po.poNumber}');
      final reportRows = await LocalDB.instance.getReportsByPoNumber(
        po.poNumber ?? '',
      );
      AppLog.d(
        'AuditPage: found ${reportRows.length} report rows for PO ${po.poNumber} locally',
      );
      data = _buildAuditData(po, reportRows);
    }

    data['generated_at'] = DateFormat('dd.MM.yyyy HH:mm').format(DateTime.now());

    setState(() {
      _auditData = data;
      _isLoading = false;
    });
  }

  Map<String, dynamic> _normalizeServerAuditData(
    Map<String, dynamic> response,
    PurchaseOrder po,
  ) {
    if (response.containsKey('audit_totals') &&
        response.containsKey('materials_consumed')) {
      return {
        ...response,
        'po_diameter': response['po_diameter'] ?? po.diameter,
        'po_length': response['po_length'] ?? po.length,
        'po_pd': response['po_pd'] ?? po.pd,
        'po_cu': response['po_cu'] ?? po.cu,
        'report_rows': response['report_rows'] ?? response['reports'] ?? [],
      };
    }

    return {
      'po_number': response['po_number'] ?? po.poNumber,
      'target_qty': response['target_qty'] ?? po.targetQty,
      'produced_qty': response['produced_qty'] ?? 0,
      'remaining_qty': response['remaining_qty'] ?? po.targetQty,
      'audit_totals': {
        'total_boxes_submitted':
            response['audit_totals']?['total_boxes_submitted'] ?? 0,
        'total_rods_produced':
            response['audit_totals']?['total_rods_produced'] ?? 0,
        'total_waste_kg': response['audit_totals']?['total_waste_kg'] ?? 0.0,
        'machine_counter_difference':
            response['audit_totals']?['machine_counter_difference'] ?? 0,
        'discrepancy_boxes_vs_machine':
            response['audit_totals']?['discrepancy_boxes_vs_machine'] ?? 0,
      },
      'materials_consumed': response['materials_consumed'] ?? [],
      'report_rows': response['report_rows'] ?? response['reports'] ?? [],
      'msg': response['msg'],
    };
  }

  Map<String, dynamic> _buildAuditData(
    PurchaseOrder po,
    List<Map<String, dynamic>> rows,
  ) {
    final List<Map<String, dynamic>> reports = rows
        .map((row) {
          try {
            return jsonDecode(row['report_data'] as String)
                as Map<String, dynamic>;
          } catch (_) {
            return <String, dynamic>{};
          }
        })
        .where((report) => report.isNotEmpty)
        .toList();

    if (reports.isEmpty) {
      return {
        'po_number': po.poNumber,
        'target_qty': po.targetQty,
        'produced_qty': 0,
        'remaining_qty': po.targetQty,
        'audit_totals': {
          'total_boxes_submitted': 0,
          'total_rods_produced': 0,
          'total_waste_kg': 0.0,
          'machine_counter_difference': 0,
          'discrepancy_boxes_vs_machine': 0,
        },
        'materials_consumed': [],
        'report_rows': [],
      };
    }

    int totalRods = 0;
    int totalBoxes = 0;
    double totalWaste = 0.0;
    final List<int> counters = [];

    final Map<String, Map<String, Map<String, double>>> materialTree = {};
    final Map<String, String> materialUnits = {};

    double toDouble(dynamic value) {
      if (value == null) return 0.0;
      if (value is double) return value;
      if (value is int) return value.toDouble();
      return double.tryParse(value.toString()) ?? 0.0;
    }

    int toInt(dynamic value) {
      if (value == null) return 0;
      if (value is int) return value;
      if (value is double) return value.toInt();
      final normalized = value.toString().trim();
      final parsed = int.tryParse(normalized);
      if (parsed != null) return parsed;
      final digits = normalized.replaceAll(RegExp(r'[^0-9\-]'), '');
      return int.tryParse(digits) ?? 0;
    }

    void addMaterial(
      String category,
      String type,
      String batch,
      double amount,
      String unit,
    ) {
      if (amount <= 0) return;
      materialUnits[category] = unit;
      materialTree.putIfAbsent(category, () => {});
      materialTree[category]!.putIfAbsent(type, () => {});
      materialTree[category]![type]![batch] =
          (materialTree[category]![type]![batch] ?? 0.0) + amount;
    }

    final List<Map<String, dynamic>> reportRows = [];

    for (final report in reports) {
      final int producedRods = report['produced_rods'] is num
          ? (report['produced_rods'] as num).toInt()
          : toInt(report['produced_rods']);
      final int machineCounter = report['machine_counter'] is num
          ? (report['machine_counter'] as num).toInt()
          : toInt(report['machine_counter']);
      final double rowDifference = report['difference'] != null
          ? toDouble(report['difference'])
          : (machineCounter - producedRods).toDouble();
      final double rowDiffPercent = report['diff_percent'] != null
          ? toDouble(report['diff_percent']
              .toString()
              .replaceAll('%', ''))
          : machineCounter > 0
              ? (rowDifference / machineCounter) * 100
              : 0.0;
      final double scrap = toDouble(report['waste_kg'] ?? report['scrap']);
      final String shiftTime = report['shift_time_range']?.toString().trim().isNotEmpty == true
          ? report['shift_time_range'].toString()
          : '${report['start_time'] ?? ''} - ${report['end_time'] ?? ''}';
      final String operatorName = report['operator_name']?.toString().trim().isNotEmpty == true
          ? report['operator_name'].toString()
          : report['operator']?.toString() ?? 'Unknown';

      totalRods += producedRods;
      totalBoxes += (report['boxes_produced'] is num
          ? (report['boxes_produced'] as num).toInt()
          : int.tryParse(report['boxes_produced']?.toString() ?? '') ?? 0);
      totalWaste += scrap;

      if (machineCounter > 0) {
        counters.add(machineCounter);
      }

      reportRows.add({
        'date': report['report_date']?.toString() ?? '',
        'time': shiftTime,
        'operator': operatorName,
        'produced_rods': producedRods,
        'machine_counter': machineCounter,
        'difference': rowDifference,
        'difference_percent': rowDiffPercent,
        'scrap': scrap,
      });

      final materialSpecs = [
        {'key': 'acetate_list', 'category': 'Acetate', 'unit': 'kg'},
        {'key': 'paper_list', 'category': 'Paper', 'unit': 'Bob'},
        {'key': 'pva_list', 'category': 'PVA Glue', 'unit': 'kg'},
        {'key': 'hm_list', 'category': 'Hot Melt Glue', 'unit': 'kg'},
        {'key': 'tri_list', 'category': 'Triacetin', 'unit': 'kg'},
      ];

      for (final spec in materialSpecs) {
        final items = report[spec['key']] as List<dynamic>?;
        if (items == null) continue;

        for (final item in items) {
          if (item is! Map<String, dynamic>) continue;
          final type = item['type']?.toString().trim().isNotEmpty == true
              ? item['type'].toString()
              : 'Unknown';
          final batch = item['batch']?.toString().trim().isNotEmpty == true
              ? item['batch'].toString()
              : 'No Batch';
          double used = 0.0;
          if (item.containsKey('used') && item['used'] != null) {
            used = toDouble(item['used']);
          } else {
            final start = toDouble(item['start']);
            final stop = toDouble(item['stop']);
            used = (start - stop).abs();
          }
          addMaterial(
            spec['category'] as String,
            type,
            batch,
            used,
            spec['unit'] as String,
          );
        }
      }
    }

    final int mcStart = counters.isNotEmpty
        ? counters.reduce((a, b) => a < b ? a : b)
        : 0;
    final int mcEnd = counters.isNotEmpty
        ? counters.reduce((a, b) => a > b ? a : b)
        : 0;
    final int mcDiff = counters.isNotEmpty ? mcEnd - mcStart : 0;
    final int discrepancy = totalRods - mcDiff;

    final List<Map<String, dynamic>> categories = [];
    materialTree.forEach((category, types) {
      double categoryTotal = 0.0;
      final List<Map<String, dynamic>> breakdown = [];
      final String unit = materialUnits[category] ?? '';

      types.forEach((typeName, batches) {
        double typeTotal = 0.0;
        final List<Map<String, dynamic>> batchItems = [];
        batches.forEach((batchName, amount) {
          batchItems.add({'batch_number': batchName, 'consumed': amount});
          typeTotal += amount;
        });

        breakdown.add({
          'type_name': typeName,
          'type_total': double.parse(typeTotal.toStringAsFixed(2)),
          'batches': batchItems,
        });
        categoryTotal += typeTotal;
      });

      categories.add({
        'category': category,
        'category_total': double.parse(categoryTotal.toStringAsFixed(2)),
        'unit': unit,
        'breakdown': breakdown,
      });
    });

    categories.sort(
      (a, b) => a['category'].toString().compareTo(b['category'].toString()),
    );

    return {
      'po_number': po.poNumber,
      'po_diameter': po.diameter,
      'po_length': po.length,
      'po_pd': po.pd,
      'po_cu': po.cu,
      'target_qty': po.targetQty,
      'produced_qty': totalRods,
      'remaining_qty': (po.targetQty - totalRods) < 0
          ? 0
          : po.targetQty - totalRods,
      'audit_totals': {
        'total_boxes_submitted': totalBoxes,
        'total_rods_produced': totalRods,
        'total_waste_kg': double.parse(totalWaste.toStringAsFixed(2)),
        'machine_counter_value': mcEnd,
        'machine_counter_difference': mcDiff,
        'discrepancy_boxes_vs_machine': discrepancy,
      },
      'materials_consumed': categories,
      'report_rows': reportRows,
    };
  }

  // PDF generation and print helper
  Future<void> _generatePdf() async {
    if (_auditData == null) return;

    final pdf = pw.Document();
    final totals = _auditData!['audit_totals'];
    final categories = _auditData!['materials_consumed'] as List<dynamic>;

    // Calculate the same metrics for PDF as on screen
    final reportRows = (_auditData!['report_rows'] as List<dynamic>? ?? [])
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();

    int totalReportRods = 0;
    int totalReportMachineCounter = 0;
    double totalReportDifference = 0.0;
    double totalReportScrap = 0.0;
    int discrepancy = 0;
    int machineCounter = 0;
    double diffPercent = 0.0;

    final List<List<String>> reportTable = [
      [
        'Date',
        'Time',
        'Operator',
        'Rods Produced',
        'Machine Counter',
        'Difference',
        'Scrap',
      ],
    ];

    for (var row in reportRows) {
      final int reportRods = row['produced_rods'] is num
          ? (row['produced_rods'] as num).toInt()
          : int.tryParse(row['produced_rods']?.toString() ?? '') ?? 0;
      final int reportMachineCounter = row['machine_counter'] is num
          ? (row['machine_counter'] as num).toInt()
          : int.tryParse(row['machine_counter']?.toString() ?? '') ?? 0;
      final double reportDiff = row['difference'] is num
          ? (row['difference'] as num).toDouble()
          : double.tryParse(row['difference']?.toString() ?? '') ?? 0.0;
      final double reportScrap = row['scrap'] is num
          ? (row['scrap'] as num).toDouble()
          : double.tryParse(row['scrap']?.toString() ?? '') ?? 0.0;

      totalReportRods += reportRods;
      totalReportMachineCounter += reportMachineCounter;
      totalReportDifference += reportDiff;
      totalReportScrap += reportScrap;

      reportTable.add([
        row['date']?.toString() ?? '',
        row['time']?.toString() ?? '',
        row['operator']?.toString() ?? '',
        reportRods.toString(),
        reportMachineCounter.toString(),
        reportDiff.toStringAsFixed(2),
        reportScrap.toStringAsFixed(2),
      ]);
    }

    if (reportRows.isNotEmpty) {
      reportTable.add([
        'TOTAL',
        '',
        '',
        totalReportRods.toString(),
        totalReportMachineCounter.toString(),
        totalReportDifference.toStringAsFixed(2),
        totalReportScrap.toStringAsFixed(2),
      ]);
      machineCounter = totalReportMachineCounter;
      discrepancy = totalReportMachineCounter - totalReportRods;
      diffPercent = machineCounter > 0
          ? (discrepancy / machineCounter) * 100
          : 0.0;
    }

    pw.TableRow buildHeaderRow() {
      return pw.TableRow(
        decoration: const pw.BoxDecoration(color: PdfColors.blueGrey800),
        children: [
          pw.Padding(
            padding: const pw.EdgeInsets.all(6),
            child: pw.Text(
              'Category',
              style: pw.TextStyle(
                fontWeight: pw.FontWeight.bold,
                color: PdfColors.white,
                fontSize: 10,
              ),
            ),
          ),
          pw.Padding(
            padding: const pw.EdgeInsets.all(6),
            child: pw.Text(
              'Material Type',
              style: pw.TextStyle(
                fontWeight: pw.FontWeight.bold,
                color: PdfColors.white,
                fontSize: 10,
              ),
            ),
          ),
          pw.Padding(
            padding: const pw.EdgeInsets.all(6),
            child: pw.Text(
              'Batch',
              style: pw.TextStyle(
                fontWeight: pw.FontWeight.bold,
                color: PdfColors.white,
                fontSize: 10,
              ),
            ),
          ),
          pw.Padding(
            padding: const pw.EdgeInsets.all(6),
            child: pw.Text(
              'Used',
              style: pw.TextStyle(
                fontWeight: pw.FontWeight.bold,
                color: PdfColors.white,
                fontSize: 10,
              ),
            ),
          ),
        ],
      );
    }

    List<pw.TableRow> materialRows = [buildHeaderRow()];

    for (var category in categories) {
      final categoryName = category['category']?.toString() ?? 'Unknown';
      final unit = category['unit']?.toString() ?? '';
      final breakdowns = category['breakdown'] as List<dynamic>;
      final categoryTotal = category['category_total']?.toString() ?? '';
      bool categoryPrinted = false;

      for (var type in breakdowns) {
        final typeName = type['type_name']?.toString() ?? 'Unknown';
        final batches = type['batches'] as List<dynamic>;
        final typeTotal = type['type_total']?.toString() ?? '';
        bool typePrinted = false;

        for (var batch in batches) {
          materialRows.add(
            pw.TableRow(
              decoration: pw.BoxDecoration(
                color: categoryPrinted ? PdfColors.white : PdfColors.grey100,
              ),
              children: [
                pw.Padding(
                  padding: const pw.EdgeInsets.all(6),
                  child: pw.Text(
                    categoryPrinted ? '' : categoryName,
                    style: pw.TextStyle(fontSize: 10),
                  ),
                ),
                pw.Padding(
                  padding: const pw.EdgeInsets.all(6),
                  child: pw.Text(
                    typePrinted ? '' : typeName,
                    style: pw.TextStyle(fontSize: 10),
                  ),
                ),
                pw.Padding(
                  padding: const pw.EdgeInsets.all(6),
                  child: pw.Text(
                    batch['batch_number']?.toString() ?? 'No Batch',
                    style: pw.TextStyle(fontSize: 10),
                  ),
                ),
                pw.Padding(
                  padding: const pw.EdgeInsets.all(6),
                  child: pw.Text(
                    '${batch['consumed'] ?? ''} $unit',
                    style: pw.TextStyle(fontSize: 10),
                  ),
                ),
              ],
            ),
          );
          categoryPrinted = true;
          typePrinted = true;
        }

        if (batches.isNotEmpty) {
          materialRows.add(
            pw.TableRow(
              decoration: const pw.BoxDecoration(color: PdfColors.grey200),
              children: [
                pw.Padding(
                  padding: const pw.EdgeInsets.all(6),
                  child: pw.Text(''),
                ),
                pw.Padding(
                  padding: const pw.EdgeInsets.all(6),
                  child: pw.Text(
                    'Total $typeName',
                    style: pw.TextStyle(
                      fontSize: 10,
                      fontWeight: pw.FontWeight.bold,
                    ),
                  ),
                ),
                pw.Padding(
                  padding: const pw.EdgeInsets.all(6),
                  child: pw.Text(''),
                ),
                pw.Padding(
                  padding: const pw.EdgeInsets.all(6),
                  child: pw.Text(
                    '$typeTotal $unit',
                    style: pw.TextStyle(
                      fontSize: 10,
                      fontWeight: pw.FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
          );
        }
      }

      if (breakdowns.length > 1) {
        materialRows.add(
          pw.TableRow(
            decoration: const pw.BoxDecoration(color: PdfColors.blue100),
            children: [
              pw.Padding(
                padding: const pw.EdgeInsets.all(6),
                child: pw.Text(
                  'Total $categoryName',
                  style: pw.TextStyle(
                    fontSize: 10,
                    fontWeight: pw.FontWeight.bold,
                    color: PdfColors.blue900,
                  ),
                ),
              ),
              pw.Padding(
                padding: const pw.EdgeInsets.all(6),
                child: pw.Text(''),
              ),
              pw.Padding(
                padding: const pw.EdgeInsets.all(6),
                child: pw.Text(''),
              ),
              pw.Padding(
                padding: const pw.EdgeInsets.all(6),
                child: pw.Text(
                  '$categoryTotal $unit',
                  style: pw.TextStyle(
                    fontSize: 10,
                    fontWeight: pw.FontWeight.bold,
                    color: PdfColors.blue900,
                  ),
                ),
              ),
            ],
          ),
        );
      }
    }

    // Build PDF page
    pdf.addPage(
      pw.MultiPage(
        pageFormat: PdfPageFormat.a4,
        margin: const pw.EdgeInsets.all(32),
        build: (pw.Context context) {
          return [
            pw.Header(
              level: 0,
              child: pw.Text(
                'PURCHASE ORDER AUDIT REPORT',
                style: pw.TextStyle(
                  fontSize: 22,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
            ),
            pw.SizedBox(height: 10),
            pw.Text(
              'PO Number: ${_auditData!['po_number']}',
              style: pw.TextStyle(fontSize: 14, fontWeight: pw.FontWeight.bold),
            ),
            pw.Text(
              'Specification: ${_auditData!['po_diameter'] ?? ''} x ${_auditData!['po_length'] ?? ''}  PD ${_auditData!['po_pd'] ?? ''}  CU ${_auditData!['po_cu'] ?? ''}',
              style: pw.TextStyle(fontSize: 14, fontWeight: pw.FontWeight.bold),
            ),
            pw.SizedBox(height: 4),
            pw.Text('Target Quantity: ${_auditData!['target_qty']} pcs'),
            pw.Text('Report generated: ${_auditData!['generated_at'] ?? ''}'),
            pw.SizedBox(height: 20),
            if (reportRows.isNotEmpty) ...[
              pw.Text(
                'Report Entries',
                style: pw.TextStyle(fontSize: 16, fontWeight: pw.FontWeight.bold),
              ),
              pw.Divider(),
              pw.SizedBox(height: 6),
              pw.Table.fromTextArray(
                headers: reportTable.first,
                data: reportTable.sublist(1),
                headerStyle: pw.TextStyle(
                  fontWeight: pw.FontWeight.bold,
                  fontSize: 9,
                ),
                cellStyle: pw.TextStyle(fontSize: 9),
                cellAlignment: pw.Alignment.centerLeft,
                headerDecoration: const pw.BoxDecoration(
                  color: PdfColors.grey300,
                ),
              ),
              pw.SizedBox(height: 12),
            ],
            pw.Text(
              'Production Summary',
              style: pw.TextStyle(fontSize: 16, fontWeight: pw.FontWeight.bold),
            ),
            pw.Divider(),
            pw.SizedBox(height: 6),
            pw.Text('Total rods produced: $totalReportRods pcs'),
            pw.Text(
              'Remaining to Produce: ${_auditData!['remaining_qty']} pcs',
            ),
            pw.Text('Boxes Submitted: ${totals['total_boxes_submitted']}'),
            pw.Text('Machine counter: $machineCounter'),
            pw.Text(
              'Difference: $discrepancy pcs (${diffPercent.toStringAsFixed(2)}%)',
              style: pw.TextStyle(
                fontWeight: pw.FontWeight.bold,
                color: diffPercent.abs() > 1.0
                    ? PdfColors.red
                    : PdfColors.black,
              ),
            ),
            pw.Text('Total Scrap Waste: ${totals['total_waste_kg']} kg'),
            pw.SizedBox(height: 16),
            pw.Text(
              'Remaining to Produce: ${_auditData!['remaining_qty']} pcs',
              style: pw.TextStyle(
                fontSize: 11,
                fontWeight: pw.FontWeight.bold,
              ),
            ),
            pw.SizedBox(height: 25),
            pw.Text(
              'Materials Consumption Details',
              style: pw.TextStyle(fontSize: 16, fontWeight: pw.FontWeight.bold),
            ),
            pw.Divider(),
            pw.SizedBox(height: 10),
            pw.Table(
              border: pw.TableBorder.all(color: PdfColors.grey300, width: 0.5),
              columnWidths: {
                0: const pw.FlexColumnWidth(2),
                1: const pw.FlexColumnWidth(2),
                2: const pw.FlexColumnWidth(1.5),
                3: const pw.FlexColumnWidth(1.5),
              },
              children: materialRows,
            ),
          ];
        },
      ),
    );

    await Printing.layoutPdf(
      onLayout: (PdfPageFormat format) async => pdf.save(),
      name: 'PO_Audit_${_auditData!['po_number']}.pdf',
    );
  }

  @override
  Widget build(BuildContext context) {
    // Полностью вернули список из твоего глобального класса AppData
    List<PurchaseOrder> availablePOs = AppData.activePOs;

    return Scaffold(
      appBar: AppBar(
        title: const Text('PO Audit'),
        actions: [
          if (_auditData != null)
            IconButton(
              icon: const Icon(Icons.picture_as_pdf),
              tooltip: 'Save / Print PDF',
              onPressed: _generatePdf,
            ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 1. SELECTOR BLOCK (Dropdown)
            Card(
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 16.0,
                  vertical: 8.0,
                ),
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<PurchaseOrder>(
                    hint: const Text("Select a Purchase Order..."),
                    value: _selectedPO,
                    isExpanded: true,
                    items: availablePOs.map((po) {
                      return DropdownMenuItem<PurchaseOrder>(
                        value: po,
                        child: Text("${po.poNumber} (Target: ${po.targetQty})"),
                      );
                    }).toList(),
                    onChanged: (val) {
                      if (val != null) _fetchAudit(val);
                    },
                  ),
                ),
              ),
            ),
            const SizedBox(height: 16),

            // 2. DATA DISPLAY BLOCK
            Expanded(child: _buildContent()),
          ],
        ),
      ),
    );
  }

  Widget _buildContent() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_auditData == null) {
      return const Center(child: Text("Select an order to view statistics"));
    }

    final totals = _auditData!['audit_totals'];
    final categories = _auditData!['materials_consumed'] as List<dynamic>;
    final reportRows = (_auditData!['report_rows'] as List<dynamic>? ?? [])
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();

    final reportTableRows = <DataRow>[];
    int totalReportRods = 0;
    int totalReportMachineCounter = 0;
    double totalReportDifference = 0.0;
    double totalReportScrap = 0.0;

    for (var row in reportRows) {
      final int reportRods = row['produced_rods'] is num
          ? (row['produced_rods'] as num).toInt()
          : int.tryParse(row['produced_rods']?.toString() ?? '') ?? 0;
      final int reportMachineCounter = row['machine_counter'] is num
          ? (row['machine_counter'] as num).toInt()
          : int.tryParse(row['machine_counter']?.toString() ?? '') ?? 0;
      final double reportDiff = row['difference'] is num
          ? (row['difference'] as num).toDouble()
          : double.tryParse(row['difference']?.toString() ?? '') ?? 0.0;
      final double reportDiffPercent = row['difference_percent'] is num
          ? (row['difference_percent'] as num).toDouble()
          : double.tryParse(row['difference_percent']?.toString() ?? '') ?? 0.0;
      final double reportScrap = row['scrap'] is num
          ? (row['scrap'] as num).toDouble()
          : double.tryParse(row['scrap']?.toString() ?? '') ?? 0.0;

      totalReportRods += reportRods;
      totalReportMachineCounter += reportMachineCounter;
      totalReportDifference += reportDiff;
      totalReportScrap += reportScrap;

      final String differenceText =
          '${reportDiff.toStringAsFixed(2)} (${reportDiffPercent.toStringAsFixed(2)}%)';

      reportTableRows.add(
        DataRow(
          cells: [
            DataCell(Text(row['date']?.toString() ?? '')),
            DataCell(Text(row['time']?.toString() ?? '')),
            DataCell(Text(row['operator']?.toString() ?? '')),
            DataCell(Text(reportRods.toString())),
            DataCell(Text(reportMachineCounter.toString())),
            DataCell(Text(differenceText)),
            DataCell(Text(reportScrap.toStringAsFixed(2))),
          ],
        ),
      );
    }

    int machineCounter = totalReportMachineCounter;
    int rodsProduced = totalReportRods;
    int discrepancy = machineCounter - rodsProduced;
    double diffPercent = machineCounter > 0
        ? (discrepancy / machineCounter) * 100
        : 0.0;
    Color cardColor = diffPercent.abs() > 1.0
        ? Colors.red.shade50
        : Colors.blue.shade50;

    if (reportRows.isNotEmpty) {
      final double totalReportDifferencePercent = totalReportMachineCounter > 0
          ? (totalReportDifference / totalReportMachineCounter) * 100
          : 0.0;
      final String totalDifferenceText =
          '${totalReportDifference.toStringAsFixed(2)} (${totalReportDifferencePercent.toStringAsFixed(2)}%)';

      reportTableRows.add(
        DataRow(
          color: WidgetStateProperty.all(Colors.grey.shade200),
          cells: [
            const DataCell(Text('TOTAL',
                style: TextStyle(fontWeight: FontWeight.bold))),
            const DataCell(Text('')),
            const DataCell(Text('')),
            DataCell(Text(totalReportRods.toString(),
                style: const TextStyle(fontWeight: FontWeight.bold))),
            DataCell(Text(totalReportMachineCounter.toString(),
                style: const TextStyle(fontWeight: FontWeight.bold))),
            DataCell(Text(totalDifferenceText,
                style: const TextStyle(fontWeight: FontWeight.bold))),
            DataCell(Text(totalReportScrap.toStringAsFixed(2),
                style: const TextStyle(fontWeight: FontWeight.bold))),
          ],
        ),
      );
    }

    // Генерируем строки таблицы динамически
    List<DataRow> tableRows = [];

    for (var cat in categories) {
      String categoryName = cat['category'].toString();
      String unit = cat['unit'].toString();
      var breakdowns = cat['breakdown'] as List<dynamic>;

      for (var type in breakdowns) {
        String typeName = type['type_name'].toString();
        var batches = type['batches'] as List<dynamic>;

        // 1. Строки батчей
        for (var b in batches) {
          tableRows.add(
            DataRow(
              cells: [
                DataCell(
                  Text(
                    categoryName,
                    style: const TextStyle(color: Colors.grey),
                  ),
                ),
                DataCell(Text(typeName)),
                DataCell(
                  Text(
                    b['batch_number'].toString(),
                    style: const TextStyle(fontStyle: FontStyle.italic),
                  ),
                ),
                DataCell(Text("${b['consumed']} $unit")),
              ],
            ),
          );
          // Очищаем имена, чтобы не дублировать визуально
          categoryName = "";
          typeName = "";
        }

        // 2. Итог по ТИПУ (если батчей больше одного)
        if (batches.length > 1) {
          tableRows.add(
            DataRow(
              color: WidgetStateProperty.all(Colors.grey.shade50),
              cells: [
                const DataCell(Text("")),
                DataCell(
                  Text(
                    "Total ${type['type_name']}",
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 13,
                    ),
                  ),
                ),
                const DataCell(Text("—")),
                DataCell(
                  Text(
                    "${type['type_total']} $unit",
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 13,
                    ),
                  ),
                ),
              ],
            ),
          );
        }
      }

      // 3. Общий итог по КАТЕГОРИИ (если типов больше одного)
      if (breakdowns.length > 1) {
        tableRows.add(
          DataRow(
            color: WidgetStateProperty.all(
              Colors.blue.shade50.withValues(alpha: 0.5),
            ),
            cells: [
              DataCell(
                Text(
                  "Total ${cat['category']}",
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Colors.blue,
                  ),
                ),
              ),
              const DataCell(Text("")),
              const DataCell(Text("")),
              DataCell(
                Text(
                  "${cat['category_total']} $unit",
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Colors.blue,
                  ),
                ),
              ),
            ],
          ),
        );
      }
    }

    if (reportRows.isNotEmpty) {
      machineCounter = totalReportMachineCounter;
      rodsProduced = totalReportRods;
      discrepancy = machineCounter - rodsProduced;
      diffPercent = machineCounter > 0
          ? (discrepancy / machineCounter) * 100
          : 0.0;
      cardColor = diffPercent.abs() > 1.0
          ? Colors.red.shade50
          : Colors.blue.shade50;
    }

    return ListView(
      children: [
        // Карточка: Production Summary
        Card(
          color: cardColor,
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: const [
                    Icon(Icons.analytics, size: 32, color: Colors.blue),
                    SizedBox(width: 12),
                    Text(
                      "Production Summary",
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ],
                ),
                const Divider(height: 24, thickness: 1),
                // PO Number
                Text(
                  'PO: ${_auditData!['po_number'] ?? ''}',
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 4),
                // Specification line
                Text(
                  'Specification: ${_auditData!['po_diameter'] ?? ''} x ${_auditData!['po_length'] ?? ''}  PD ${_auditData!['po_pd'] ?? ''}  CU ${_auditData!['po_cu'] ?? ''}',
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 8),
                // Target quantity first
                Text(
                  'Target Quantity: ${_auditData!['target_qty']} pcs',
                  style: const TextStyle(fontSize: 14),
                ),
                const SizedBox(height: 4),
                // Report generated after
                if (_auditData!['generated_at'] != null)
                  Text(
                    'Report generated: ${_auditData!['generated_at']}',
                    style: const TextStyle(fontSize: 13, color: Colors.grey),
                  ),
                const SizedBox(height: 12),
                Text(
                  "Total rods produced: $rodsProduced pcs",
                  style: const TextStyle(fontSize: 15),
                ),
                const SizedBox(height: 6),
                Text(
                  "Boxes submitted: ${totals['total_boxes_submitted']}",
                  style: const TextStyle(fontSize: 15),
                ),
                const SizedBox(height: 6),
                Text(
                  "Machine counter: $machineCounter",
                  style: const TextStyle(fontSize: 15),
                ),
                const SizedBox(height: 6),
                Text(
                  "Difference: $discrepancy pcs (${diffPercent.toStringAsFixed(2)}%)",
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.bold,
                    color: diffPercent.abs() > 1.0
                        ? Colors.red.shade700
                        : Colors.black87,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  "Waste: ${totals['total_waste_kg']} kg",
                  style: const TextStyle(fontSize: 15),
                ),
                const SizedBox(height: 16),
                const Text(
                  "Report Entries",
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 8),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    headingRowColor:
                        WidgetStateProperty.all(Colors.grey.shade100),
                    columns: const [
                      DataColumn(
                        label: Text(
                          'Date',
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                      ),
                      DataColumn(
                        label: Text(
                          'Time',
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                      ),
                      DataColumn(
                        label: Text(
                          'Operator',
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                      ),
                      DataColumn(
                        label: Text(
                          'Rods Produced',
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                      ),
                      DataColumn(
                        label: Text(
                          'Machine Counter',
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                      ),
                      DataColumn(
                        label: Text(
                          'Difference',
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                      ),
                      DataColumn(
                        label: Text(
                          'Scrap',
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                      ),
                    ],
                    rows: reportTableRows,
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  "Remaining to Produce: ${_auditData!['remaining_qty']} pcs",
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 24),

        // Таблица: Materials Consumption
        const Text(
          "Materials Consumption",
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        Card(
          elevation: 1,
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              headingRowColor: WidgetStateProperty.all(Colors.grey.shade100),
              columns: const [
                DataColumn(
                  label: Text(
                    'Category',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
                DataColumn(
                  label: Text(
                    'Material Type',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
                DataColumn(
                  label: Text(
                    'Batch #',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
                DataColumn(
                  label: Text(
                    'Consumed',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
              ],
              rows: tableRows,
            ),
          ),
        ),
      ],
    );
  }
}
