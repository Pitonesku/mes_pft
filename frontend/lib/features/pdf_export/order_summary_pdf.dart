// lib/features/pdf_export/order_summary_pdf.dart
//
// Reusable builder for the consolidated "MANUFACTURING ORDER AUDIT REPORT" PDF.
// This is the single source of truth for the document the Flutter client renders
// and uploads to Odoo as the Order Summary (mirroring the Orders screen
// "Print / Save PDF" layout), and it appends the Consolidated Quality section.
// Pure Dart + the `pdf` package only — no dart:html, no dart:io, no Flutter widgets.

import 'dart:typed_data';

import 'package:intl/intl.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../../models.dart';

/// Parameter labels for the Consolidated Quality table (mirrors the printable
/// "Quality Report" certificate ordering).
const _paramLabels = <String, String>{
  'length': 'Length',
  'diameter': 'Diameter',
  'pd': 'Pressure drop',
  'hardness': 'Hardness',
  'weight': 'Weight',
};

const _paramOrder = <String>['length', 'diameter', 'pd', 'hardness', 'weight'];

class OrderSummaryPdfService {
  /// Build the consolidated Order Summary PDF bytes.
  ///
  /// [data] is the PO audit payload (`audit_totals`, `materials_consumed`,
  /// `report_rows`, `produced_qty`, `target_qty`, `remaining_qty`, `po_number`).
  /// [certificate] is the consolidated quality matrix (`parameter`, `unit`,
  /// `nominal`, `lower`, `upper`, `mean`, `sd`) — optional but recommended.
  static Future<Uint8List> build({
    required Map<String, dynamic> data,
    required PurchaseOrder po,
    List<dynamic>? certificate,
  }) async {
    final totals = (data['audit_totals'] as Map?)?.cast<String, dynamic>() ?? {};
    final mats = (data['materials_consumed'] as List?) ?? const [];
    final reports = (data['report_rows'] as List?) ?? const [];
    final cert = certificate ?? const [];

    final pdf = pw.Document(title: 'MANUFACTURING ORDER AUDIT REPORT');
    pdf.addPage(pw.MultiPage(
      pageFormat: PdfPageFormat.a4,
      build: (ctx) {
        final rows = <pw.Widget>[];

        // ── Header ──────────────────────────────────────────────────────────
        rows.add(pw.Text('MANUFACTURING ORDER AUDIT REPORT',
            style: pw.TextStyle(fontSize: 18, fontWeight: pw.FontWeight.bold)));
        rows.add(pw.SizedBox(height: 8));
        rows.add(pw.Text('PO Number: ${data['po_number'] ?? po.poNumber}',
            style: pw.TextStyle(fontSize: 12, fontWeight: pw.FontWeight.bold)));
        rows.add(pw.Text(
            'Specification: ${po.diameter} x ${po.length}  PD ${po.pd}  CU ${po.cu}',
            style: const pw.TextStyle(fontSize: 10)));
        rows.add(pw.Text(
            'Target Quantity: ${NumberFormat.decimalPattern().format(po.targetQty)} pcs',
            style: const pw.TextStyle(fontSize: 10)));
        rows.add(pw.Text(
            'Report generated: ${DateFormat('dd.MM.yyyy HH:mm').format(DateTime.now())}',
            style: const pw.TextStyle(fontSize: 10)));
        rows.add(pw.SizedBox(height: 16));

        // ── Report Entries ──────────────────────────────────────────────────
        rows.add(pw.Text('Report Entries',
            style: pw.TextStyle(fontSize: 13, fontWeight: pw.FontWeight.bold)));
        rows.add(pw.Divider());

        int totalRods = 0, totalMachineCounter = 0;
        double totalDiff = 0, totalScrap = 0;

        final tableData = <List<String>>[];
        for (final r in reports) {
          final rr = (r as Map).cast<String, dynamic>();
          final rods = _toInt(rr['produced_rods']);
          final counter = _toInt(rr['machine_counter']);
          final diff = _toDouble(rr['difference']);
          final diffPct = _toDouble(rr['difference_percent']);
          final scrap = _toDouble(rr['scrap']);
          totalRods += rods;
          totalMachineCounter += counter;
          totalDiff += diff;
          totalScrap += scrap;
          tableData.add([
            rr['date']?.toString() ?? '-',
            rr['time']?.toString() ?? '-',
            rr['operator']?.toString() ?? '-',
            NumberFormat.decimalPattern().format(rods),
            NumberFormat.decimalPattern().format(counter),
            '${diff.toStringAsFixed(0)} (${diffPct.toStringAsFixed(2)}%)',
            scrap.toStringAsFixed(2),
          ]);
        }
        final totalDiffPct =
            totalMachineCounter > 0 ? (totalDiff / totalMachineCounter) * 100 : 0.0;
        tableData.add([
          'TOTAL', '', '',
          NumberFormat.decimalPattern().format(totalRods),
          NumberFormat.decimalPattern().format(totalMachineCounter),
          '${totalDiff.toStringAsFixed(0)} (${totalDiffPct.toStringAsFixed(2)}%)',
          totalScrap.toStringAsFixed(2),
        ]);

        rows.add(pw.Table.fromTextArray(
          headers: ['Date', 'Time', 'Operator', 'Rods Produced', 'Machine Counter', 'Difference', 'Scrap'],
          data: tableData,
          headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 8),
          cellStyle: const pw.TextStyle(fontSize: 8),
          headerDecoration: const pw.BoxDecoration(color: PdfColors.grey300),
          columnWidths: {
            0: const pw.FlexColumnWidth(2),
            1: const pw.FlexColumnWidth(2),
            2: const pw.FlexColumnWidth(2),
            3: const pw.FlexColumnWidth(2),
            4: const pw.FlexColumnWidth(2),
            5: const pw.FlexColumnWidth(2.5),
            6: const pw.FlexColumnWidth(1.5),
          },
        ));
        rows.add(pw.SizedBox(height: 16));

        // ── Production Summary ──────────────────────────────────────────────
        rows.add(pw.Text('Production Summary',
            style: pw.TextStyle(fontSize: 13, fontWeight: pw.FontWeight.bold)));
        rows.add(pw.Divider());
        void addSummaryRow(String label, String value) {
          rows.add(pw.Row(children: [
            pw.Expanded(
                child: pw.Text(label, style: const pw.TextStyle(fontSize: 10))),
            pw.Text(value,
                style: pw.TextStyle(fontSize: 10, fontWeight: pw.FontWeight.bold)),
          ]));
          rows.add(pw.SizedBox(height: 3));
        }

        final producedQty = _toInt(data['produced_qty']);
        final remainingQty = _toInt(data['remaining_qty']);
        final totalBoxes = _toInt(totals['total_boxes_submitted']);
        final machCounter =
            _toInt(totals['total_machine_counter'] ?? totalMachineCounter);
        final diffPcs = machCounter - producedQty;
        final diffPctSumm = machCounter > 0 ? (diffPcs / machCounter) * 100 : 0.0;
        final wasteKg = _toDouble(totals['total_waste_kg']);

        addSummaryRow('Total rods produced:',
            '${NumberFormat.decimalPattern().format(producedQty)} pcs');
        addSummaryRow('Remaining to Produce:',
            '${NumberFormat.decimalPattern().format(remainingQty)} pcs');
        addSummaryRow('Boxes Submitted:', '$totalBoxes');
        addSummaryRow(
            'Machine counter:', NumberFormat.decimalPattern().format(machCounter));
        addSummaryRow('Difference:',
            '${NumberFormat.decimalPattern().format(diffPcs)} pcs (${diffPctSumm.toStringAsFixed(2)}%)');
        addSummaryRow('Total Scrap Waste:', '${wasteKg.toStringAsFixed(1)} kg');
        rows.add(pw.SizedBox(height: 16));

        // ── Materials Consumption Details ───────────────────────────────────
        rows.add(pw.Text('Materials Consumption Details',
            style: pw.TextStyle(fontSize: 13, fontWeight: pw.FontWeight.bold)));
        rows.add(pw.Divider());

        final matTableData = <List<String>>[];
        for (final cat in mats) {
          final catMap = (cat as Map).cast<String, dynamic>();
          final catName = catMap['category']?.toString() ?? '-';
          final unit = catMap['unit']?.toString() ?? 'kg';
          final breakdowns = (catMap['breakdown'] as List?) ?? const [];
          double catTotal = 0;

          for (final typeEntry in breakdowns) {
            final te = (typeEntry as Map).cast<String, dynamic>();
            final typeName = te['type_name']?.toString() ?? '-';
            final batches = (te['batches'] as List?) ?? const [];
            double typeTotal = 0;

            for (final b in batches) {
              final bm = (b as Map).cast<String, dynamic>();
              final batch = bm['batch_number']?.toString() ?? 'No Batch';
              final used = _toDouble(bm['consumed'] ?? bm['total_used']);
              typeTotal += used;
              matTableData
                  .add([catName, typeName, batch, '${used.toStringAsFixed(1)} $unit']);
            }
            matTableData.add([
              '', 'Total $typeName', '', '${typeTotal.toStringAsFixed(1)} $unit'
            ]);
            catTotal += typeTotal;
          }
          matTableData
              .add(['Total $catName', '', '', '${catTotal.toStringAsFixed(1)} $unit']);
        }

        pw.Widget matCell(String text, {bool bold = false}) => pw.Padding(
              padding: const pw.EdgeInsets.symmetric(horizontal: 4, vertical: 3),
              child: pw.Text(text,
                  style: bold
                      ? pw.TextStyle(fontSize: 9, fontWeight: pw.FontWeight.bold)
                      : const pw.TextStyle(fontSize: 9)),
            );

        rows.add(pw.Table(
          columnWidths: {
            0: const pw.FlexColumnWidth(2.0),
            1: const pw.FlexColumnWidth(2.0),
            2: const pw.FlexColumnWidth(1.5),
            3: const pw.FlexColumnWidth(1.5),
          },
          border: pw.TableBorder.all(color: PdfColors.grey300, width: 0.5),
          children: [
            pw.TableRow(
                decoration: const pw.BoxDecoration(color: PdfColors.grey300),
                children: ['Category', 'Material Type', 'Batch', 'Used']
                    .map((h) => matCell(h, bold: true))
                    .toList()),
            for (final row in matTableData)
              pw.TableRow(
                decoration: pw.BoxDecoration(
                    color: (row[0].startsWith('Total ') && row[1].isEmpty)
                        ? PdfColors.deepPurple50
                        : (row[1].startsWith('Total '))
                            ? PdfColors.blueGrey50
                            : PdfColors.white),
                children: row
                    .asMap()
                    .entries
                    .map((e) => matCell(e.value,
                        bold: row[0].startsWith('Total ') ||
                            row[1].startsWith('Total ')))
                    .toList(),
              ),
          ],
        ));

        // ── Consolidated Quality ────────────────────────────────────────────
        if (cert.isNotEmpty) {
          rows.add(pw.SizedBox(height: 16));
          rows.add(pw.Text('Consolidated Quality',
              style: pw.TextStyle(fontSize: 13, fontWeight: pw.FontWeight.bold)));
          rows.add(pw.Divider());
          rows.add(_consolidatedQualityTable(cert));
        }
        return rows;
      },
    ));

    return pdf.save();
  }

  /// Renders the consolidated quality certificate as a bordered table.
  static pw.Widget _consolidatedQualityTable(List<dynamic> certificate) {
    final byParam = <String, Map<String, dynamic>>{};
    for (final r in certificate) {
      if (r is Map) byParam['${r['parameter']}'] = r.cast<String, dynamic>();
    }
    final ordered = <Map<String, dynamic>>[];
    for (final k in _paramOrder) {
      if (byParam.containsKey(k)) ordered.add(byParam[k]!);
    }
    for (final e in byParam.entries) {
      if (!_paramOrder.contains(e.key)) ordered.add(e.value);
    }

    final header = ['#', 'Parameter', 'Measure', 'Nominal', 'Lower SL', 'Upper SL', 'Mean', 'SD', 'Source'];
    final cells = <List<String>>[header];
    var i = 0;
    for (final row in ordered) {
      i++;
      final p = '${row['parameter']}';
      final flagged = row['flagged'] == true;
      final src = '${row['source'] ?? ''}'.toLowerCase();
      final sourceLabel = src == 'manual'
          ? 'Manual'
          : (src == 'auto' ? 'Auto' : '');
      cells.add([
        '$i',
        _paramLabels[p] ?? p,
        _f(row['unit']),
        _f(row['nominal']),
        _f(row['lower']),
        _f(row['upper']),
        '${_f(row['mean'])}${flagged ? ' ( ! )' : ''}',
        _f(row['sd']),
        sourceLabel,
      ]);
    }

    return pw.Table(
      border: pw.TableBorder.all(color: PdfColors.grey300, width: 0.5),
      columnWidths: {
        0: const pw.FlexColumnWidth(0.5),
        1: const pw.FlexColumnWidth(2.0),
        2: const pw.FlexColumnWidth(1.1),
        3: const pw.FlexColumnWidth(1.0),
        4: const pw.FlexColumnWidth(1.0),
        5: const pw.FlexColumnWidth(1.0),
        6: const pw.FlexColumnWidth(1.2),
        7: const pw.FlexColumnWidth(1.0),
        8: const pw.FlexColumnWidth(1.0),
      },
      children: [
        for (var ri = 0; ri < cells.length; ri++)
          pw.TableRow(
            decoration: ri == 0
                ? const pw.BoxDecoration(color: PdfColors.grey300)
                : null,
            children: [
              for (final cell in cells[ri])
                pw.Padding(
                  padding: const pw.EdgeInsets.all(4),
                  child: pw.Text(cell,
                      style: pw.TextStyle(
                          fontSize: 8,
                          fontWeight: ri == 0
                              ? pw.FontWeight.bold
                              : pw.FontWeight.normal)),
                ),
            ],
          ),
      ],
    );
  }

  static String _f(dynamic v, [String fb = '-']) {
    if (v == null || '$v'.isEmpty) return fb;
    if (v is num) {
      final d = v.toDouble();
      if (d == d.roundToDouble()) return d.round().toString();
      return d.toString();
    }
    return '$v';
  }

  static int _toInt(dynamic v) {
    if (v == null) return 0;
    if (v is int) return v;
    if (v is num) return v.toInt();
    return int.tryParse(v.toString()) ?? 0;
  }

  static double _toDouble(dynamic v) {
    if (v == null) return 0.0;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? 0.0;
  }
}
