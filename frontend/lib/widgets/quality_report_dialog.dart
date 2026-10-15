// lib/widgets/quality_report_dialog.dart
// Printable A4 quality certificate report: header (PO + specification + machine /
// date / shift / operator), the Automatic Measurements table (station mean/SD),
// and the Manual Measurements table (each check + a computed Mean row).
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';

const _paramLabels = <String, String>{
  'length': 'Length',
  'diameter': 'Diameter',
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

  Map<String, dynamic>? get _report =>
      (widget.data['report'] as Map<String, dynamic>?);

  List<Map<String, dynamic>> _orderedRows(String key) {
    final byParam = <String, Map<String, dynamic>>{};
    for (final r in ((_report?[key] as List<dynamic>?) ?? const [])) {
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

  List<Map<String, dynamic>> get _autoRows => _orderedRows('automatic');

  List<Map<String, dynamic>> get _manualChecks {
    final out = <Map<String, dynamic>>[];
    for (final c in ((_report?['manual_checks'] as List<dynamic>?) ?? const [])) {
      if (c is Map) out.add(c.cast<String, dynamic>());
    }
    return out;
  }

  String _s(dynamic v, [String fb = '-']) => (v == null || '$v'.isEmpty) ? fb : '$v';
  String _f(dynamic v) {
    if (v == null) return '';
    if (v is num) {
      final d = v.toDouble();
      if (d == d.roundToDouble()) return d.round().toString();
      return d.toString();
    }
    return '$v';
  }
  String _flag(dynamic v) => v == null ? '-' : (v == true ? 'OK' : 'FAIL');

  String _fmtTime(dynamic v) {
    if (v == null || '$v'.isEmpty) return '-';
    try {
      return DateFormat('HH:mm').format(DateTime.parse('$v').toLocal());
    } catch (_) {
      return '$v';
    }
  }

  double? _meanOf(List<Map<String, dynamic>> rows, String key) {
    final vals = <double>[];
    for (final r in rows) {
      final v = r[key];
      if (v is num) {
        vals.add(v.toDouble());
      } else if (v != null) {
        final d = double.tryParse('$v');
        if (d != null) vals.add(d);
      }
    }
    if (vals.isEmpty) return null;
    return vals.reduce((a, b) => a + b) / vals.length;
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
    final autoRows = _autoRows;
    final manual = _manualChecks;

    pw.Widget kv(String l, String v) => pw.Row(
          crossAxisAlignment: pw.CrossAxisAlignment.start,
          children: [
            pw.SizedBox(
                width: 120,
                child: pw.Text(l,
                    style: pw.TextStyle(
                        fontWeight: pw.FontWeight.bold, fontSize: 9))),
            pw.Expanded(child: pw.Text(v, style: const pw.TextStyle(fontSize: 9))),
          ],
        );

    pw.Widget section(String t) => pw.Padding(
          padding: const pw.EdgeInsets.only(top: 8, bottom: 4),
          child: pw.Text(t,
              style: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 11)),
        );

    List<List<String>> autoCells() {
      final cells = <List<String>>[
        ['#', 'Parameter', 'Measure', 'Nominal', 'Lower SL', 'Upper SL', 'Mean', 'SD']
      ];
      var i = 0;
      for (final row in autoRows) {
        i++;
        final p = '${row['parameter']}';
        cells.add([
          '$i', _paramLabels[p] ?? p, _s(row['unit']), _f(row['nominal']),
          _f(row['lower']), _f(row['upper']), _f(row['mean']), _f(row['sd']),
        ]);
      }
      return cells;
    }

    List<List<String>> manualCells() {
      final cells = <List<String>>[
        ['#', 'Time', 'Weight (mg)', 'Length (mm)', 'Hardness (%)', 'Glue Seam', 'Cut Quality', 'Visual']
      ];
      var i = 0;
      for (final c in manual) {
        i++;
        cells.add([
          '$i', _fmtTime(c['measured_at']), _f(c['weight_mg']), _f(c['length_mm']),
          _f(c['hardness']), _flag(c['glue_seam_ok']), _flag(c['cut_quality_ok']),
          _flag(c['visual_appearance_ok']),
        ]);
      }
      if (manual.isNotEmpty) {
        cells.add([
          '', 'Mean', _f(_meanOf(manual, 'weight_mg')),
          _f(_meanOf(manual, 'length_mm')), _f(_meanOf(manual, 'hardness')),
          '', '', '',
        ]);
      }
      return cells;
    }

    doc.addPage(pw.MultiPage(
      pageFormat: PdfPageFormat.a4,
      margin: const pw.EdgeInsets.all(28),
      build: (ctx) => [
        pw.Text('QUALITY REPORT',
            textAlign: pw.TextAlign.center,
            style: pw.TextStyle(
                fontSize: 15,
                fontWeight: pw.FontWeight.bold)),
        pw.SizedBox(height: 10),
        section('Header'),
        kv('PO Number', _s(r['po_number'])),
        kv('Specification', _s(r['spec_string'])),
        kv('Machine', _s(r['machine'])),
        kv('Date', _s(r['date'])),
        kv('Shift Interval', _s(r['shift_label'])),
        kv('Operator', _s(r['operator'])),
        section('Automatic Measurements'),
        pw.Table.fromTextArray(
            headers: autoCells().first,
            data: autoCells().sublist(1),
            headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 8),
            cellStyle: const pw.TextStyle(fontSize: 8),
            headerDecoration: const pw.BoxDecoration(color: PdfColors.grey300)),
        section('Manual Measurements'),
        pw.Table.fromTextArray(
            headers: manualCells().first,
            data: manualCells().sublist(1),
            headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 8),
            cellStyle: const pw.TextStyle(fontSize: 8),
            headerDecoration: const pw.BoxDecoration(color: PdfColors.grey300)),
        if (_s(r['remarks'], '').trim().isNotEmpty)
          pw.Padding(
              padding: const pw.EdgeInsets.only(top: 8),
              child: pw.Text('Notes: ${r['remarks']}',
                  style: const pw.TextStyle(fontSize: 9))),
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
              ? const SizedBox(
                  width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
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
      actions: [
        TextButton(
            onPressed: () => Navigator.of(context).pop(), child: const Text('Close'))
      ],
    );
  }

  Widget _preview(Map<String, dynamic> r) {
    final autoRows = _autoRows;
    final manual = _manualChecks;
    Widget kv(String l, String v) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 1),
          child: Row(children: [
            SizedBox(
                width: 120,
                child: Text(l,
                    style: const TextStyle(
                        fontWeight: FontWeight.w600,
                        fontSize: 12,
                        color: Colors.black54))),
            Expanded(child: Text(v, style: const TextStyle(fontSize: 12))),
          ]),
        );
    final autoTableRows = <TableRow>[
      TableRow(children: [
        for (final c in ['#', 'Parameter', 'Measure', 'Nominal', 'Lower SL', 'Upper SL', 'Mean', 'SD'])
          _th(c)
      ]),
    ];
    var i = 0;
    for (final row in autoRows) {
      i++;
      final p = '${row['parameter']}';
      autoTableRows.add(TableRow(children: [
        _td('$i'), _td(_paramLabels[p] ?? p), _td(_s(row['unit'])),
        _td(_f(row['nominal'])), _td(_f(row['lower'])), _td(_f(row['upper'])),
        _td(_f(row['mean'])), _td(_f(row['sd'])),
      ]));
    }

    final manualTableRows = <TableRow>[
      TableRow(children: [
        for (final c in ['#', 'Time', 'Weight (mg)', 'Length (mm)', 'Hardness (%)', 'Glue Seam', 'Cut Quality', 'Visual'])
          _th(c)
      ]),
    ];
    var j = 0;
    for (final c in manual) {
      j++;
      manualTableRows.add(TableRow(children: [
        _td('$j'), _td(_fmtTime(c['measured_at'])), _td(_f(c['weight_mg'])),
        _td(_f(c['length_mm'])), _td(_f(c['hardness'])),
        _td(_flag(c['glue_seam_ok'])), _td(_flag(c['cut_quality_ok'])),
        _td(_flag(c['visual_appearance_ok'])),
      ]));
    }
    if (manual.isNotEmpty) {
      manualTableRows.add(TableRow(children: [
        _td(''), _th('Mean'), _td(_f(_meanOf(manual, 'weight_mg'))),
        _td(_f(_meanOf(manual, 'length_mm'))),
        _td(_f(_meanOf(manual, 'hardness'))), _td(''), _td(''), _td(''),
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
      const Text('Automatic Measurements',
          style: TextStyle(fontWeight: FontWeight.bold)),
      const SizedBox(height: 4),
      Table(border: TableBorder.all(color: Colors.grey.shade300), children: autoTableRows),
      const SizedBox(height: 12),
      const Text('Manual Measurements',
          style: TextStyle(fontWeight: FontWeight.bold)),
      const SizedBox(height: 4),
      Table(border: TableBorder.all(color: Colors.grey.shade300), children: manualTableRows),
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
