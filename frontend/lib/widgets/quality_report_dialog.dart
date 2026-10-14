// lib/widgets/quality_report_dialog.dart
// Printable A4 quality certificate report: header (PO + specification + machine /
// date / shift / operator) and the measurement-results table (length, diameter,
// pressure drop, hardness, weight) with nominal / lower / upper / mean / SD.
// Values come from the server's merged run/order summary (station + manual).
// No verdict and no monitor-only SD color thresholds.
import 'package:flutter/material.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';

const _paramLabels = <String, String>{
  'length': 'Filter rods length',
  'diameter': 'Filter rods diameter',
  'pd': 'Pressure drop',
  'hardness': 'Hardness',
  'weight': 'Weight',
};
const _paramOrder = <String>['length', 'diameter', 'pd', 'hardness', 'weight'];

class QualityReportDialog extends StatefulWidget {
  final Map<String, dynamic> data;
  final String machine;
  const QualityReportDialog({super.key, required this.data, required this.machine});
  @override
  State<QualityReportDialog> createState() => _QualityReportDialogState();
}

class _QualityReportDialogState extends State<QualityReportDialog> {
  bool _printing = false;

  Map<String, dynamic>? get _report => (widget.data['report'] as Map<String, dynamic>?);
  List<Map<String, dynamic>> get _rows {
    final byParam = <String, Map<String, dynamic>>{};
    for (final r in ((_report?['certificate'] as List<dynamic>?) ?? const [])) {
      if (r is Map) byParam['${r['parameter']}'] = r.cast<String, dynamic>();
    }
    final ordered = <Map<String, dynamic>>[];
    for (final k in _paramOrder) {
      if (byParam.containsKey(k)) ordered.add(byParam[k]!);
    }
    for (final e in byParam.entries) {
      if (!_paramOrder.contains(e.key)) ordered.add(e.value);
    }
    return ordered;
  }

  String _s(dynamic v, [String fb = '—']) => (v == null || '$v'.isEmpty) ? fb : '$v';
  String _f(dynamic v) {
    if (v == null) return '';
    if (v is num) {
      final d = v.toDouble();
      if (d == d.roundToDouble()) return d.round().toString();
      return d.toString();
    }
    return '$v';
  }

  List<String> _manualLines() {
    final m = _report?['manual_measurements'];
    if (m is! Map || m.isEmpty) return const [];
    final lines = <String>[];
    final count = m['count'];
    if (count is num && count > 0) lines.add('Manual checks: $count');
    for (final k in _paramOrder) {
      final e = m[k];
      if (e is Map) {
        final mm = e.cast<String, dynamic>();
        final sd = mm['sd'] != null ? ', SD ${_f(mm['sd'])}' : '';
        lines.add('${_paramLabels[k]}: mean ${_f(mm['mean'])}$sd (n=${mm['n'] ?? '-'})');
      }
    }
    return lines;
  }

  Future<void> _print() async {
    setState(() => _printing = true);
    try {
      await Printing.layoutPdf(
        onLayout: (_) => _buildPdf().save(),
        name: 'quality_report.pdf',
      );
    } finally {
      if (mounted) setState(() => _printing = false);
    }
  }
  pw.Document _buildPdf() {
    final doc = pw.Document();
    final r = _report ?? const <String, dynamic>{};
    final rows = _rows;
    final manual = _manualLines();

    pw.Widget kv(String l, String v) => pw.Row(
          crossAxisAlignment: pw.CrossAxisAlignment.start,
          children: [
            pw.SizedBox(width: 120, child: pw.Text(l, style: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 10))),
            pw.Expanded(child: pw.Text(v, style: const pw.TextStyle(fontSize: 10))),
          ],
        );

    final header = ['#', 'Parameter', 'Measure', 'Nominal', 'Lower SL', 'Upper SL', 'Mean', 'SD'];
    final cells = <List<String>>[header];
    var i = 0;
    for (final row in rows) {
      i++;
      final p = '${row['parameter']}';
      cells.add([
        '$i', _paramLabels[p] ?? p, _s(row['unit']),
        _f(row['nominal']), _f(row['lower']), _f(row['upper']),
        _f(row['mean']), _f(row['sd']),
      ]);
    }

    doc.addPage(pw.MultiPage(
      pageFormat: PdfPageFormat.a4,
      margin: const pw.EdgeInsets.all(32),
      build: (ctx) => [
        pw.Center(child: pw.Text('QUALITY REPORT', style: pw.TextStyle(fontSize: 16, fontWeight: pw.FontWeight.bold))),
        pw.SizedBox(height: 12),
        pw.Text('Header', style: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 11)),
        pw.Divider(),
        kv('PO Number', _s(r['po_number'])),
        kv('Specification', _s(r['spec_string'])),
        kv('Machine', _s(r['machine'])),
        kv('Date', _s(r['date'])),
        kv('Shift Interval', _s(r['shift_label'])),
        kv('Operator', _s(r['operator'])),
        pw.SizedBox(height: 14),
        pw.Text('Measurement Results', style: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 11)),
        pw.Divider(),
        pw.Table(
          border: pw.TableBorder.all(color: PdfColors.grey),
          children: [
            for (var ri = 0; ri < cells.length; ri++)
              pw.TableRow(
                decoration: ri == 0 ? const pw.BoxDecoration(color: PdfColor.fromInt(0xFFEEEEEE)) : null,
                children: [
                  for (final cell in cells[ri])
                    pw.Padding(
                      padding: const pw.EdgeInsets.all(4),
                      child: pw.Text(cell, style: pw.TextStyle(fontSize: 9, fontWeight: ri == 0 ? pw.FontWeight.bold : pw.FontWeight.normal)),
                    ),
                ],
              ),
          ],
        ),
        if (manual.isNotEmpty) ...[
          pw.SizedBox(height: 8),
          ...manual.map((l) => pw.Text('• $l', style: const pw.TextStyle(fontSize: 9))),
        ],
        if (_s(r['remarks'], '').trim().isNotEmpty)
          pw.Padding(
            padding: const pw.EdgeInsets.only(top: 8),
            child: pw.Text('Notes: ${r['remarks']}', style: const pw.TextStyle(fontSize: 9)),
          ),
      ],
    ));
    return doc;
  }
  @override
  Widget build(BuildContext context) {
    final r = _report;
    return AlertDialog(
      title: Row(children: [
        const Expanded(child: Text('Quality Report')),
        IconButton(
          icon: _printing
              ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.print),
          tooltip: 'Print / Save PDF',
          onPressed: _printing || r == null ? null : _print,
        ),
      ]),
      content: SizedBox(
        width: 680,
        height: 560,
        child: r == null
            ? const Center(child: Text('No quality report data for this selection'))
            : SingleChildScrollView(child: _preview(r)),
      ),
      actions: [TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Close'))],
    );
  }

  Widget _preview(Map<String, dynamic> r) {
    final rows = _rows;
    final manual = _manualLines();
    Widget kv(String l, String v) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 1),
          child: Row(children: [
            SizedBox(width: 120, child: Text(l, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12, color: Colors.black54))),
            Expanded(child: Text(v, style: const TextStyle(fontSize: 12))),
          ]),
        );
    final tableRows = <TableRow>[
      TableRow(children: [for (final c in ['#', 'Parameter', 'Measure', 'Nominal', 'Lower SL', 'Upper SL', 'Mean', 'SD']) _th(c)]),
    ];
    var i = 0;
    for (final row in rows) {
      i++;
      final p = '${row['parameter']}';
      tableRows.add(TableRow(children: [
        _td('$i'), _td(_paramLabels[p] ?? p), _td(_s(row['unit'])),
        _td(_f(row['nominal'])), _td(_f(row['lower'])), _td(_f(row['upper'])),
        _td(_f(row['mean'])), _td(_f(row['sd'])),
      ]));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('Header', style: TextStyle(fontWeight: FontWeight.bold)),
      kv('PO Number', _s(r['po_number'])),
      kv('Specification', _s(r['spec_string'])),
      kv('Machine', _s(r['machine'])),
      kv('Date', _s(r['date'])),
      kv('Shift Interval', _s(r['shift_label'])),
      kv('Operator', _s(r['operator'])),
      const SizedBox(height: 12),
      const Text('Measurement Results', style: TextStyle(fontWeight: FontWeight.bold)),
      const SizedBox(height: 4),
      Table(border: TableBorder.all(color: Colors.grey.shade300), children: tableRows),
      if (manual.isNotEmpty) ...[
        const SizedBox(height: 8),
        ...manual.map((l) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 1),
            child: Text('• $l', style: const TextStyle(fontSize: 12)))),
      ],
      if (_s(r['remarks'], '').trim().isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text('Notes: ${r['remarks']}', style: const TextStyle(fontSize: 12)),
        ),
    ]);
  }

  Widget _th(String t) => Padding(
      padding: const EdgeInsets.all(5),
      child: Text(t, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 11)));
  Widget _td(String t) => Padding(
      padding: const EdgeInsets.all(5),
      child: Text(t, style: const TextStyle(fontSize: 11)));
}
