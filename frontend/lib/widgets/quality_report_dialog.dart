// lib/widgets/quality_report_dialog.dart
// Printable A4 quality inspection report: header, target specs, statistical
// summary + verdict, optional control-chart snapshots and full raw table.
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';

import 'quality_control_chart.dart';

class QualityReportDialog extends StatefulWidget {
  final Map<String, dynamic> data;
  final String machine;
  const QualityReportDialog({super.key, required this.data, required this.machine});
  @override
  State<QualityReportDialog> createState() => _QualityReportDialogState();
}

class _QualityReportDialogState extends State<QualityReportDialog> {
  bool _includeCharts = true;
  bool _includeRaw = false;
  bool _printing = false;
  final _pdKey = GlobalKey();
  final _diaKey = GlobalKey();

  Map<String, dynamic> get _header => (widget.data['header'] as Map<String, dynamic>?) ?? const {};
  Map<String, dynamic> get _kpis => (widget.data['kpis'] as Map<String, dynamic>?) ?? const {};
  Map<String, dynamic> get _specs => (widget.data['specs'] as Map<String, dynamic>?) ?? const {};
  Map<String, dynamic> get _thresholds => (widget.data['thresholds'] as Map<String, dynamic>?) ?? const {};
  List<dynamic> get _rawRows => (widget.data['raw_rows'] as List<dynamic>?) ?? const [];
  Map<String, dynamic> get _series =>
      ((widget.data['series'] as Map<String, dynamic>?) ?? const {})[widget.machine] as Map<String, dynamic>? ?? const {};

  double? _n(dynamic v) => v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));
  String _str(dynamic v, [String fb = '—']) => (v == null || '$v'.isEmpty) ? fb : '$v';
  String _f(double? v, int d) => v == null ? '—' : v.toStringAsFixed(d);

  String get _verdict {
    final pd = '${_kpis['status_pd'] ?? ''}';
    final dia = '${_kpis['status_dia'] ?? ''}';
    if (pd == 'RED' || dia == 'RED') return 'FAIL';
    if (pd == 'YELLOW' || dia == 'YELLOW') return 'WARN';
    if (pd == 'GREEN' || dia == 'GREEN') return 'PASS';
    return 'NO DATA';
  }

  Color get _verdictColor => switch (_verdict) {
        'PASS' => Colors.green,
        'WARN' => Colors.amber,
        'FAIL' => Colors.red,
        _ => Colors.grey,
      };

  Future<Uint8List?> _capture(GlobalKey key) async {
    try {
      final ctx = key.currentContext;
      if (ctx == null) return null;
      final obj = ctx.findRenderObject();
      if (obj is! RenderRepaintBoundary) return null;
      final image = await obj.toImage(pixelRatio: 2.0);
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      return data?.buffer.asUint8List();
    } catch (_) {
      return null;
    }
  }

  Future<void> _print() async {
    setState(() => _printing = true);
    try {
      Uint8List? pdPng;
      Uint8List? diaPng;
      if (_includeCharts) {
        pdPng = await _capture(_pdKey);
        diaPng = await _capture(_diaKey);
      }
      final doc = _buildPdf(pdPng, diaPng);
      await Printing.layoutPdf(onLayout: (_) => doc.save(), name: 'quality_report.pdf');
    } finally {
      if (mounted) setState(() => _printing = false);
    }
  }

  pw.Document _buildPdf(Uint8List? pdPng, Uint8List? diaPng) {
    final doc = pw.Document();
    final h = _header;
    final k = _kpis;
    final t = _thresholds;

    doc.addPage(pw.MultiPage(
      pageFormat: PdfPageFormat.a4,
      margin: const pw.EdgeInsets.all(28),
      build: (ctx) {
        final rows = <pw.Widget>[];

        void row(String label, String value) {
          rows.add(pw.Row(mainAxisAlignment: pw.MainAxisAlignment.spaceBetween, children: [
            pw.Expanded(child: pw.Text(label, style: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 10))),
            pw.Text(value, style: const pw.TextStyle(fontSize: 10)),
          ]));
          rows.add(pw.SizedBox(height: 4));
        }

        void section(String title) {
          rows.add(pw.SizedBox(height: 12));
          rows.add(pw.Text(title, style: pw.TextStyle(fontSize: 12, fontWeight: pw.FontWeight.bold)));
          rows.add(pw.Divider());
        }

        rows.add(pw.Center(child: pw.Text('PRODLOG — QUALITY INSPECTION REPORT',
            style: pw.TextStyle(fontSize: 14, fontWeight: pw.FontWeight.bold))));
        rows.add(pw.SizedBox(height: 4));
        rows.add(pw.Center(child: pw.Text(
            'Generated ${DateTime.now().toIso8601String().substring(0, 19).replaceFirst('T', ' ')}',
            style: const pw.TextStyle(fontSize: 9, color: PdfColors.grey700))));

        section('Header');
        row('PO Number', _str(h['po_number']));
        row('Machine', _str(h['machine']));
        row('Date', _str(h['date']));
        row('Shift Interval', _str(h['shift_label']));
        row('Operator', _str(h['operator']));

        section('Target Specifications');
        final specTable = [
          ['Parameter', 'Target', 'LSL', 'USL', 'SD Yellow', 'SD Red'],
        ];
        void addSpec(String key, String label, int dec) {
          final s = (_specs[key] as Map<String, dynamic>?) ?? const {};
          specTable.add([
            label,
            _f(_n(s['target']), dec),
            _f(_n(s['lsl']), dec),
            _f(_n(s['usl']), dec),
            _str(key == 'pd' ? t['pd_warn'] : t['dia_warn']),
            _str(key == 'pd' ? t['pd_fail'] : t['dia_fail']),
          ]);
        }

        addSpec('pd', 'Pressure Drop (mm WG)', 1);
        addSpec('diameter', 'Diameter (mm)', 3);
        rows.add(pw.Table.fromTextArray(
          headers: specTable.first,
          data: specTable.sublist(1),
          headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 9),
          cellStyle: const pw.TextStyle(fontSize: 9),
          headerDecoration: const pw.BoxDecoration(color: PdfColors.grey300),
        ));

        section('Statistical Summary');
        final sample = (k['sample_size'] ?? 0) as num;
        final rejected = (k['rods_rejected'] ?? 0) as num;
        final valid = sample - rejected;
        final statsTable = [
          ['Metric', 'Value'],
          ['Sample Size (tested rods)', '${sample.toInt()}'],
          ['Valid Rods', '${valid.toInt()}'],
          ['Rejected (3× Tol)', '${rejected.toInt()}'],
          ['Mean PD (mm WG)', _f(_n(k['mean_pd']), 1)],
          ['Sample SD PD (mm WG)', _f(_n(k['sd_pd']), 2)],
          ['Mean Diameter (mm)', _f(_n(k['mean_dia']), 3)],
          ['Sample SD Diameter (mm)', _f(_n(k['sd_dia']), 4)],
        ];
        rows.add(pw.Table.fromTextArray(
          headers: statsTable.first,
          data: statsTable.sublist(1),
          headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 9),
          cellStyle: const pw.TextStyle(fontSize: 9),
          headerDecoration: const pw.BoxDecoration(color: PdfColors.grey300),
        ));
        rows.add(pw.SizedBox(height: 8));
        final vColor = _verdict == 'PASS'
            ? PdfColors.green
            : _verdict == 'WARN'
                ? PdfColors.amber
                : _verdict == 'FAIL'
                    ? PdfColors.red
                    : PdfColors.grey;
        rows.add(pw.Row(children: [
          pw.Container(
            padding: const pw.EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            decoration: pw.BoxDecoration(color: vColor, borderRadius: pw.BorderRadius.circular(4)),
            child: pw.Text('FINAL VERDICT: $_verdict',
                style: pw.TextStyle(fontSize: 11, fontWeight: pw.FontWeight.bold, color: PdfColors.white)),
          ),
        ]));

        if (pdPng != null || diaPng != null) {
          section('Control Charts');
          if (pdPng != null) {
            rows.add(pw.Image(pw.MemoryImage(pdPng), width: 500, height: 160));
            rows.add(pw.SizedBox(height: 6));
          }
          if (diaPng != null) {
            rows.add(pw.Image(pw.MemoryImage(diaPng), width: 500, height: 160));
          }
        }

        if (_includeRaw && _rawRows.isNotEmpty) {
          section('Raw Measurements');
          final rawTable = [
            ['Timestamp', 'Rod #', 'Machine', 'PO', 'Diameter', 'PD', 'Weight', 'Status'],
          ];
          for (final r in _rawRows) {
            final m = r as Map<String, dynamic>;
            final ts = _str(m['measured_at']);
            rawTable.add([
              ts.length > 19 ? ts.substring(0, 19) : ts,
              _str(m['rod_no']),
              _str(m['machine_name']),
              _str(m['po_number']),
              _f(_n(m['diameter']), 3),
              _f(_n(m['pd']), 1),
              _f(_n(m['weight']), 3),
              m['rejected'] == true ? 'REJECTED' : 'OK',
            ]);
          }
          rows.add(pw.Table.fromTextArray(
            headers: rawTable.first,
            data: rawTable.sublist(1),
            headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 8),
            cellStyle: const pw.TextStyle(fontSize: 8),
            headerDecoration: const pw.BoxDecoration(color: PdfColors.grey300),
          ));
        }

        return rows;
      },
    ));
    return doc;
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: const EdgeInsets.all(16),
      child: SizedBox(
        width: 900,
        height: 720,
        child: Column(children: [
          Container(
            color: const Color(0xFFF5F5F5),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(children: [
              const Icon(Icons.picture_as_pdf, size: 18, color: Colors.deepPurple),
              const SizedBox(width: 8),
              const Expanded(child: Text('Quality Inspection Report',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14))),
              Checkbox(
                value: _includeCharts,
                onChanged: (v) => setState(() => _includeCharts = v ?? true),
                visualDensity: VisualDensity.compact,
              ),
              const Text('Include Control Charts', style: TextStyle(fontSize: 12)),
              const SizedBox(width: 12),
              Checkbox(
                value: _includeRaw,
                onChanged: (v) => setState(() => _includeRaw = v ?? false),
                visualDensity: VisualDensity.compact,
              ),
              const Text('Include Full Raw Table', style: TextStyle(fontSize: 12)),
              const SizedBox(width: 16),
              IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context), tooltip: 'Close'),
            ]),
          ),
          const Divider(height: 1),
          Expanded(
            child: Container(
              color: Colors.grey.shade300,
              padding: const EdgeInsets.all(24),
              child: Center(
                child: Container(
                  constraints: const BoxConstraints(maxWidth: 700),
                  decoration: BoxDecoration(color: Colors.white, boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.15), blurRadius: 10)]),
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(28),
                    child: _previewBody(),
                  ),
                ),
              ),
            ),
          ),
          Container(
            color: const Color(0xFFF5F5F5),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              OutlinedButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
              const SizedBox(width: 12),
              ElevatedButton.icon(
                onPressed: _printing ? null : _print,
                icon: _printing
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.print, size: 18),
                label: const Text('Print / Download PDF'),
              ),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _previewBody() {
    final h = _header;
    final k = _kpis;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Center(child: Text('PRODLOG — QUALITY INSPECTION REPORT',
          style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold))),
      const SizedBox(height: 12),
      _section('Header'),
      _row('PO Number', _str(h['po_number'])),
      _row('Machine', _str(h['machine'])),
      _row('Date', _str(h['date'])),
      _row('Shift Interval', _str(h['shift_label'])),
      _row('Operator', _str(h['operator'])),
      _section('Target Specifications'),
      _specTable(),
      _section('Statistical Summary'),
      _row('Sample Size (tested rods)', '${((k['sample_size'] ?? 0) as num).toInt()}'),
      _row('Valid Rods', '${(((k['sample_size'] ?? 0) as num) - ((k['rods_rejected'] ?? 0) as num)).toInt()}'),
      _row('Rejected (3× Tol)', '${((k['rods_rejected'] ?? 0) as num).toInt()}'),
      _row('Mean PD (mm WG)', _f(_n(k['mean_pd']), 1)),
      _row('Sample SD PD (mm WG)', _f(_n(k['sd_pd']), 2)),
      _row('Mean Diameter (mm)', _f(_n(k['mean_dia']), 3)),
      _row('Sample SD Diameter (mm)', _f(_n(k['sd_dia']), 4)),
      const SizedBox(height: 8),
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
        decoration: BoxDecoration(color: _verdictColor, borderRadius: BorderRadius.circular(4)),
        child: Text('FINAL VERDICT: $_verdict',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.white)),
      ),
      if (_includeCharts && _series.isNotEmpty) ...[
        _section('Control Charts'),
        RepaintBoundary(
          key: _pdKey,
          child: QualityControlChart(
              title: 'Pressure Drop (PD)', parameter: 'pd', lineColor: Colors.blue,
              series: _series, formatValue: (v) => v.toStringAsFixed(1), height: 160),
        ),
        const SizedBox(height: 8),
        RepaintBoundary(
          key: _diaKey,
          child: QualityControlChart(
              title: 'Diameter', parameter: 'diameter', lineColor: Colors.teal,
              series: _series, formatValue: (v) => v.toStringAsFixed(3), height: 160),
        ),
      ],
      if (_includeRaw && _rawRows.isNotEmpty) ...[
        _section('Raw Measurements'),
        _rawTable(),
      ],
    ]);
  }

  Widget _section(String title) => Padding(
        padding: const EdgeInsets.only(top: 14, bottom: 4),
        child: Text(title, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
      );

  Widget _row(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Expanded(child: Text(label, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w500, color: Colors.black54))),
          Text(value, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
        ]),
      );

  Widget _specTable() {
    final t = _thresholds;
    final rows = <TableRow>[
      TableRow(children: [
        _th('Parameter'), _th('Target'), _th('LSL'), _th('USL'), _th('SD Yellow'), _th('SD Red'),
      ]),
    ];
    void addSpec(String key, String label, int dec) {
      final s = (_specs[key] as Map<String, dynamic>?) ?? const {};
      rows.add(TableRow(children: [
        _td(label),
        _td(_f(_n(s['target']), dec)),
        _td(_f(_n(s['lsl']), dec)),
        _td(_f(_n(s['usl']), dec)),
        _td(_str(key == 'pd' ? t['pd_warn'] : t['dia_warn'])),
        _td(_str(key == 'pd' ? t['pd_fail'] : t['dia_fail'])),
      ]));
    }

    addSpec('pd', 'PD (mm WG)', 1);
    addSpec('diameter', 'Diameter (mm)', 3);
    return Table(border: TableBorder.all(color: Colors.grey.shade300), children: rows);
  }

  Widget _rawTable() {
    final header = ['Timestamp', 'Rod #', 'Diameter', 'PD', 'Weight', 'Status'];
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowColor: const WidgetStatePropertyAll(Color(0xFFEEEEEE)),
        columns: [for (final c in header) DataColumn(label: Text(c, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 11)))],
        rows: [
          for (final r in _rawRows)
            DataRow(cells: [
              for (final c in header) DataCell(Text(_cell(r, c), style: const TextStyle(fontSize: 11))),
            ]),
        ],
      ),
    );
  }

  String _cell(dynamic r, String c) {
    final m = r as Map<String, dynamic>;
    switch (c) {
      case 'Timestamp':
        final ts = _str(m['measured_at']);
        return ts.length > 19 ? ts.substring(0, 19) : ts;
      case 'Rod #':
        return _str(m['rod_no']);
      case 'Diameter':
        return _f(_n(m['diameter']), 3);
      case 'PD':
        return _f(_n(m['pd']), 1);
      case 'Weight':
        return _f(_n(m['weight']), 3);
      case 'Status':
        return m['rejected'] == true ? 'REJECTED' : 'OK';
      default:
        return '—';
    }
  }

  Widget _th(String t) => Padding(
        padding: const EdgeInsets.all(6),
        child: Text(t, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 11)),
      );

  Widget _td(String t) => Padding(
        padding: const EdgeInsets.all(6),
        child: Text(t, style: const TextStyle(fontSize: 11)),
      );
}



