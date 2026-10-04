// lib/features/pdf_export/pdf_layout_service.dart
//
// Platform-agnostic PDF layout service.
// This is the DRY core — written ONCE, runs identically on Web and Android.
// No Flutter widgets, no dart:html, no dart:io — pure Dart + pdf package only.

import 'dart:typed_data';

import 'package:intl/intl.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../../models.dart';

/// Builds PDF documents from application data models.
/// Returns raw [Uint8List] bytes that can be passed to any [PdfExporter].
class PdfLayoutService {
  // ─── Colour palette ────────────────────────────────────────────────────────
  static const _headerBg = PdfColor.fromInt(0xFF1565C0);   // deep blue
  static const _rowAlt   = PdfColor.fromInt(0xFFF5F5F5);   // light grey
  static const _accent   = PdfColor.fromInt(0xFF1976D2);   // medium blue
  static const _white    = PdfColors.white;
  static const _black    = PdfColors.black;
  static const _grey     = PdfColors.grey600;

  // ─── Public API ────────────────────────────────────────────────────────────

  /// Generates a daily Production Report PDF.
  ///
  /// [reportData] is the raw JSON map returned by the FastAPI `/reports` endpoint.
  /// [po] is the associated [PurchaseOrder] model.
  Future<Uint8List> buildProductionReport({
    required Map<String, dynamic> reportData,
    required PurchaseOrder po,
  }) async {
    final doc = pw.Document(
      title: 'Production Report',
      author: 'Production Log System',
    );

    doc.addPage(
      pw.MultiPage(
        pageFormat: PdfPageFormat.a4,
        margin: const pw.EdgeInsets.symmetric(horizontal: 28, vertical: 24),
        header: (ctx) => _buildPageHeader(reportData),
        footer: (ctx) => _buildPageFooter(ctx),
        build: (ctx) => [
          _buildSummarySection(reportData, po),
          pw.SizedBox(height: 14),
          _buildProductionMetricsSection(reportData),
          pw.SizedBox(height: 14),
          _buildMaterialsSection(reportData),
          pw.SizedBox(height: 20),
          _buildSignatureSection(),
        ],
      ),
    );

    return doc.save();
  }

  /// Generates a Purchase Order summary PDF.
  Future<Uint8List> buildPurchaseOrderSummary({
    required PurchaseOrder po,
  }) async {
    final doc = pw.Document(
      title: 'Purchase Order — ${po.poNumber}',
      author: 'Production Log System',
    );

    doc.addPage(
      pw.Page(
        pageFormat: PdfPageFormat.a4,
        margin: const pw.EdgeInsets.all(28),
        build: (ctx) => pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.start,
          children: [
            _buildPoHeader(po),
            pw.SizedBox(height: 16),
            _buildPoDetailsTable(po),
            pw.SizedBox(height: 16),
            _buildPoProgressBar(po),
          ],
        ),
      ),
    );

    return doc.save();
  }

  // ─── Page Header / Footer ──────────────────────────────────────────────────

  pw.Widget _buildPageHeader(Map<String, dynamic> data) {
    final date = data['report_date'] ?? DateFormat('yyyy-MM-dd').format(DateTime.now());
    final shift = data['shift_name'] ?? '';
    final machine = data['machine_name'] ?? '';

    return pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.stretch,
      children: [
        pw.Container(
          padding: const pw.EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: const pw.BoxDecoration(color: _headerBg),
          child: pw.Row(
            mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
            children: [
              pw.Text(
                'PRODUCTION REPORT',
                style: pw.TextStyle(
                  color: _white,
                  fontSize: 14,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
              pw.Column(
                crossAxisAlignment: pw.CrossAxisAlignment.end,
                children: [
                  pw.Text('Date: $date',
                      style: const pw.TextStyle(color: _white, fontSize: 9)),
                  pw.Text('Shift: $shift  |  Machine: $machine',
                      style: const pw.TextStyle(color: _white, fontSize: 9)),
                ],
              ),
            ],
          ),
        ),
        pw.SizedBox(height: 8),
      ],
    );
  }

  pw.Widget _buildPageFooter(pw.Context ctx) {
    return pw.Column(
      children: [
        pw.Divider(color: _grey, thickness: 0.5),
        pw.Row(
          mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
          children: [
            pw.Text(
              'Production Log System — Confidential',
              style: const pw.TextStyle(fontSize: 7, color: _grey),
            ),
            pw.Text(
              'Page ${ctx.pageNumber} of ${ctx.pagesCount}',
              style: const pw.TextStyle(fontSize: 7, color: _grey),
            ),
          ],
        ),
      ],
    );
  }

  // ─── Report Sections ───────────────────────────────────────────────────────

  pw.Widget _buildSummarySection(Map<String, dynamic> data, PurchaseOrder po) {
    return pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        _sectionTitle('Order & Operator Information'),
        pw.SizedBox(height: 6),
        pw.Table(
          border: pw.TableBorder.all(color: PdfColors.grey300, width: 0.5),
          columnWidths: {
            0: const pw.FlexColumnWidth(1),
            1: const pw.FlexColumnWidth(1),
            2: const pw.FlexColumnWidth(1),
            3: const pw.FlexColumnWidth(1),
          },
          children: [
            _tableHeaderRow(['PO Number', 'Operator', 'Machine', 'Shift']),
            _tableDataRow([
              data['po_number'] ?? '',
              data['operator_name'] ?? '',
              data['machine_name'] ?? '',
              data['shift_name'] ?? '',
            ], isAlt: false),
            _tableHeaderRow(['Diameter (mm)', 'Length (mm)', 'PD (mmWg)', 'Weight (mg)']),
            _tableDataRow([
              '${po.diameter}',
              '${po.length}',
              '${po.pd}',
              '${po.weight}',
            ], isAlt: true),
            _tableHeaderRow(['Box Type', 'CU', 'Acetate Type', 'Paper Type']),
            _tableDataRow([
              '${po.boxType}',
              '${po.cu}',
              po.acetateType,
              po.paperType,
            ], isAlt: false),
          ],
        ),
      ],
    );
  }

  pw.Widget _buildProductionMetricsSection(Map<String, dynamic> data) {
    return pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        _sectionTitle('Production Metrics'),
        pw.SizedBox(height: 6),
        pw.Table(
          border: pw.TableBorder.all(color: PdfColors.grey300, width: 0.5),
          columnWidths: {
            0: const pw.FlexColumnWidth(1.4),
            1: const pw.FlexColumnWidth(0.8),
            2: const pw.FlexColumnWidth(1.4),
            3: const pw.FlexColumnWidth(0.8),
          },
          children: [
            _tableHeaderRow(['Metric', 'Value', 'Metric', 'Value']),
            _tableDataRow([
              'Boxes Produced',
              '${data['boxes_produced'] ?? 0}',
              'Produced Rods',
              '${data['produced_rods'] ?? 0}',
            ], isAlt: false),
            _tableDataRow([
              'Machine Counter',
              '${data['machine_counter'] ?? 0}',
              'Difference',
              '${data['difference'] ?? 0}',
            ], isAlt: true),
            _tableDataRow([
              'Difference %',
              '${data['diff_percent'] ?? 0}%',
              'Waste (kg)',
              '${data['waste_kg'] ?? 0}',
            ], isAlt: false),
            _tableDataRow([
              'Machine Efficiency',
              '${data['machine_efficiency'] ?? 0}%',
              'Downtime (min)',
              '${data['downtime_minutes'] ?? 0}',
            ], isAlt: true),
          ],
        ),
      ],
    );
  }

  pw.Widget _buildMaterialsSection(Map<String, dynamic> data) {
    final rows = <List<String>>[];

    void addRows(String label, List<dynamic>? items) {
      if (items == null || items.isEmpty) return;
      for (final item in items) {
        if (item is Map) {
          rows.add([
            label,
            item['type']?.toString() ?? '',
            item['batch']?.toString() ?? '',
            item['start']?.toString() ?? '',
            item['stop']?.toString() ?? '',
            (item['used'] as num?)?.toStringAsFixed(2) ?? '0.00',
          ]);
        }
      }
    }

    addRows('Acetate',  data['acetate_list']  as List?);
    addRows('Paper',    data['paper_list']    as List?);
    addRows('PVA Glue', data['pva_list']      as List?);
    addRows('Hot Melt', data['hm_list']       as List?);
    addRows('Triacetin',data['tri_list']      as List?);

    if (rows.isEmpty) return pw.SizedBox();

    return pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        _sectionTitle('Materials Used'),
        pw.SizedBox(height: 6),
        pw.Table(
          border: pw.TableBorder.all(color: PdfColors.grey300, width: 0.5),
          columnWidths: {
            0: const pw.FlexColumnWidth(1.0),
            1: const pw.FlexColumnWidth(1.4),
            2: const pw.FlexColumnWidth(1.2),
            3: const pw.FlexColumnWidth(0.8),
            4: const pw.FlexColumnWidth(0.8),
            5: const pw.FlexColumnWidth(0.8),
          },
          children: [
            _tableHeaderRow(['Category', 'Type', 'Batch', 'Start', 'Stop', 'Used']),
            ...rows.asMap().entries.map(
              (e) => _tableDataRow(e.value, isAlt: e.key.isOdd),
            ),
          ],
        ),
      ],
    );
  }

  pw.Widget _buildSignatureSection() {
    return pw.Row(
      mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
      children: [
        _signatureBlock('Operator Signature'),
        _signatureBlock('Supervisor Signature'),
        _signatureBlock('QC Signature'),
      ],
    );
  }

  // ─── PO-specific sections ──────────────────────────────────────────────────

  pw.Widget _buildPoHeader(PurchaseOrder po) {
    return pw.Container(
      padding: const pw.EdgeInsets.all(12),
      decoration: const pw.BoxDecoration(color: _headerBg),
      child: pw.Row(
        mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
        children: [
          pw.Text(
            'PURCHASE ORDER — ${po.poNumber}',
            style: pw.TextStyle(
              color: _white,
              fontSize: 14,
              fontWeight: pw.FontWeight.bold,
            ),
          ),
          pw.Text(
            'Created: ${DateFormat('yyyy-MM-dd').format(po.createdAt)}',
            style: const pw.TextStyle(color: _white, fontSize: 9),
          ),
        ],
      ),
    );
  }

  pw.Widget _buildPoDetailsTable(PurchaseOrder po) {
    return pw.Table.fromTextArray(
      border: pw.TableBorder.all(color: PdfColors.grey300, width: 0.5),
      headerStyle: pw.TextStyle(
        fontWeight: pw.FontWeight.bold,
        fontSize: 9,
        color: _white,
      ),
      headerDecoration: const pw.BoxDecoration(color: _accent),
      cellStyle: const pw.TextStyle(fontSize: 9),
      headers: ['Parameter', 'Value', 'Parameter', 'Value'],
      data: [
        ['Diameter (mm)', '${po.diameter}', 'Length (mm)', '${po.length}'],
        ['PD (mmWg)', '${po.pd}', 'CU', '${po.cu}'],
        ['Weight (mg)', '${po.weight}', 'Box Type', '${po.boxType}'],
        ['Acetate Type', po.acetateType, 'Paper Type', po.paperType],
        ['HM Glue', po.hmGlueType, 'PVA Glue', po.pvaGlueType],
        ['Triacetin', po.triacetinType, '', ''],
        ['Target Qty', '${po.targetQty}', 'Produced Qty', '${po.producedQty}'],
        ['Remaining Qty', '${po.remainingQty}', 'Hidden', po.isHidden ? 'Yes' : 'No'],
      ],
    );
  }

  pw.Widget _buildPoProgressBar(PurchaseOrder po) {
    final progress = po.targetQty > 0
        ? (po.producedQty / po.targetQty).clamp(0.0, 1.0)
        : 0.0;
    final pct = (progress * 100).toStringAsFixed(1);

    return pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        _sectionTitle('Production Progress: $pct%'),
        pw.SizedBox(height: 6),
        _buildProgressBar(progress),
        pw.SizedBox(height: 4),
        pw.Text(
          '${po.producedQty} / ${po.targetQty} units',
          style: const pw.TextStyle(fontSize: 8, color: _grey),
        ),
      ],
    );
  }

  // ─── Reusable table helpers ────────────────────────────────────────────────

  pw.TableRow _tableHeaderRow(List<String> cells) {
    return pw.TableRow(
      decoration: const pw.BoxDecoration(color: _accent),
      children: cells
          .map(
            (c) => pw.Padding(
              padding: const pw.EdgeInsets.symmetric(horizontal: 6, vertical: 4),
              child: pw.Text(
                c,
                style: pw.TextStyle(
                  fontSize: 8,
                  fontWeight: pw.FontWeight.bold,
                  color: _white,
                ),
              ),
            ),
          )
          .toList(),
    );
  }

  pw.TableRow _tableDataRow(List<String> cells, {required bool isAlt}) {
    return pw.TableRow(
      decoration: pw.BoxDecoration(
        color: isAlt ? _rowAlt : _white,
      ),
      children: cells
          .map(
            (c) => pw.Padding(
              padding: const pw.EdgeInsets.symmetric(horizontal: 6, vertical: 4),
              child: pw.Text(c, style: const pw.TextStyle(fontSize: 8)),
            ),
          )
          .toList(),
    );
  }

  pw.Widget _sectionTitle(String title) {
    return pw.Container(
      padding: const pw.EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: const pw.BoxDecoration(
        border: pw.Border(
          left: pw.BorderSide(color: _accent, width: 3),
        ),
      ),
      child: pw.Text(
        title,
        style: pw.TextStyle(
          fontSize: 10,
          fontWeight: pw.FontWeight.bold,
          color: _accent,
        ),
      ),
    );
  }

  /// Renders a simple two-segment progress bar using fixed widths (A4 = ~539pt usable).
  pw.Widget _buildProgressBar(double progress) {
    const totalWidth = 539.0; // A4 usable width at 28pt margins
    final filledWidth = (totalWidth * progress).clamp(0.0, totalWidth);
    final emptyWidth = totalWidth - filledWidth;
    final barColor = progress >= 1.0 ? PdfColors.green : _accent;

    return pw.Row(
      children: [
        if (filledWidth > 0)
          pw.Container(
            width: filledWidth,
            height: 14,
            decoration: pw.BoxDecoration(
              color: barColor,
              borderRadius: pw.BorderRadius.circular(3),
            ),
          ),
        if (emptyWidth > 0)
          pw.Container(
            width: emptyWidth,
            height: 14,
            decoration: pw.BoxDecoration(
              color: PdfColors.grey200,
              borderRadius: pw.BorderRadius.circular(3),
            ),
          ),
      ],
    );
  }

  pw.Widget _signatureBlock(String label) {
    return pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        pw.SizedBox(height: 32),
        pw.Container(width: 140, height: 0.5, color: _black),
        pw.SizedBox(height: 4),
        pw.Text(label, style: const pw.TextStyle(fontSize: 8, color: _grey)),
      ],
    );
  }
}
