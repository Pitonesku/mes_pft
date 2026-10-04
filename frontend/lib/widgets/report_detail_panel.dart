// lib/widgets/report_detail_panel.dart
// Shared report detail side-panel used by ReportsScreen and DashboardScreen.
import 'package:flutter/material.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';

class ReportDetailPanel extends StatelessWidget {
  final Map<String, dynamic> report;
  final VoidCallback onClose;
  final VoidCallback? onArchiveToggle;
  const ReportDetailPanel({super.key, required this.report, required this.onClose, this.onArchiveToggle});

  String _fmt(dynamic v, {int dec = 2}) {
    if (v == null) return '-';
    if (v is num) return v.toStringAsFixed(dec);
    return v.toString();
  }

  Widget _row(String label, String value, {Color? vc}) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SizedBox(width: 150, child: Text(label, style: TextStyle(
        fontSize: 12, color: Colors.grey[600], fontWeight: FontWeight.w500))),
      Expanded(child: Text(value, style: TextStyle(
        fontSize: 13, fontWeight: FontWeight.w600, color: vc))),
    ]),
  );

  Widget _sec(String title, List<Widget> ch) => Column(
    crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SizedBox(height: 14),
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: const BoxDecoration(
          border: Border(left: BorderSide(color: Colors.deepPurple, width: 3))),
        child: Text(title, style: const TextStyle(fontSize: 12,
          fontWeight: FontWeight.bold, color: Colors.deepPurple))),
      const Divider(height: 8),
      ...ch,
    ]);

  Widget _materialBreakdown(String title, List<dynamic>? items) {
    if (items == null || items.isEmpty) return const SizedBox();
    double total = 0;
    final rows = <Widget>[];
    rows.add(Row(children: const [
      Expanded(flex: 4, child: Text('Type', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11, color: Colors.grey))),
      Expanded(flex: 3, child: Text('Batch', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11, color: Colors.grey))),
      Expanded(flex: 2, child: Text('Start', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11, color: Colors.grey))),
      Expanded(flex: 2, child: Text('Stop', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11, color: Colors.grey))),
      Expanded(flex: 2, child: Text('Used', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11, color: Colors.grey), textAlign: TextAlign.right)),
    ]));
    for (final it in items) {
      final type  = it['type']?.toString() ?? '-';
      final batch = it['batch']?.toString().isNotEmpty == true ? it['batch'].toString() : 'No Batch';
      final start = it['start']?.toString() ?? '-';
      final stop  = it['stop']?.toString() ?? '-';
      double used = 0;
      if (it['used'] != null) {
        used = double.tryParse(it['used'].toString()) ?? 0;
      } else {
        final s = double.tryParse(it['start']?.toString() ?? '') ?? 0;
        final e = double.tryParse(it['stop']?.toString() ?? '') ?? 0;
        used = s - e;
      }
      total += used;
      rows.add(Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Expanded(flex: 4, child: Text(type, style: const TextStyle(fontSize: 11))),
          Expanded(flex: 3, child: Text(batch, style: const TextStyle(fontSize: 11))),
          Expanded(flex: 2, child: Text(start, style: const TextStyle(fontSize: 11))),
          Expanded(flex: 2, child: Text(stop, style: const TextStyle(fontSize: 11))),
          Expanded(flex: 2, child: Text(used.toStringAsFixed(2), style: const TextStyle(fontSize: 11), textAlign: TextAlign.right)),
        ]),
      ));
    }
    rows.add(const Divider(height: 6));
    rows.add(Row(children: [
      const Expanded(flex: 4, child: Text('Total', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11))),
      const Expanded(flex: 3, child: SizedBox()),
      const Expanded(flex: 2, child: SizedBox()),
      const Expanded(flex: 2, child: SizedBox()),
      Expanded(flex: 2, child: Text(total.toStringAsFixed(2), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 11), textAlign: TextAlign.right)),
    ]));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.only(top: 8, bottom: 4),
        child: Text(title, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12, color: Colors.blueGrey))),
      ...rows,
      const SizedBox(height: 6),
    ]);
  }

  Future<void> _printPdf(BuildContext context) async {
    final pdf = pw.Document();
    pdf.addPage(pw.MultiPage(
      pageFormat: PdfPageFormat.a4,
      build: (ctx) {
        final rows = <pw.Widget>[];
        void addRow(String label, String value) {
          rows.add(pw.Row(mainAxisAlignment: pw.MainAxisAlignment.spaceBetween, children: [
            pw.Expanded(child: pw.Text(label, style: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 10))),
            pw.Text(value, style: const pw.TextStyle(fontSize: 10)),
          ]));
          rows.add(pw.SizedBox(height: 4));
        }
        void addSection(String title) {
          rows.add(pw.SizedBox(height: 12));
          rows.add(pw.Text(title, style: pw.TextStyle(fontSize: 12, fontWeight: pw.FontWeight.bold)));
          rows.add(pw.Divider());
        }
        void addMaterials(String title, List<dynamic>? items) {
          if (items == null || items.isEmpty) return;
          addSection(title);
          double total = 0;
          final table = [['Material Type', 'Batch', 'Start', 'Stop', 'Used']];
          for (final it in items) {
            final type = it['type']?.toString() ?? '-';
            final batch = it['batch']?.toString().isNotEmpty == true ? it['batch'].toString() : 'No Batch';
            final start = it['start']?.toString() ?? '-';
            final stop = it['stop']?.toString() ?? '-';
            double used = 0;
            if (it['used'] != null) {
              used = double.tryParse(it['used'].toString()) ?? 0;
            } else {
              final s = double.tryParse(it['start']?.toString() ?? '') ?? 0;
              final e = double.tryParse(it['stop']?.toString() ?? '') ?? 0;
              used = s - e;
            }
            total += used;
            table.add([type, batch, start, stop, used.toStringAsFixed(2)]);
          }
          table.add(['', 'Overall Total', '', '', total.toStringAsFixed(2)]);
          rows.add(pw.Table.fromTextArray(
            headers: table.first, data: table.sublist(1),
            headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 9),
            cellStyle: const pw.TextStyle(fontSize: 9),
            headerDecoration: const pw.BoxDecoration(color: PdfColors.grey300),
          ));
          rows.add(pw.SizedBox(height: 6));
        }

        addSection('General Info');
        addRow('Operator', report['operator_name'] ?? '-');
        addRow('Date', report['report_date'] ?? '-');
        addRow('Shift', '${report['shift_name'] ?? '-'} (${report['shift_time_range'] ?? ''})');
        addRow('Machine', report['machine_name'] ?? '-');
        addRow('PO Number', report['po_number'] ?? '-');
        addSection('Technical Specification');
        addRow('Lot Number', report['lot_number'] ?? '-');
        addRow('Box Type', _fmt(report['box_type'], dec: 0));
        addRow('Diameter / Length', '${_fmt(report["diameter"])} / ${_fmt(report["length"])}');
        addRow('PD / Weight', '${_fmt(report["pd"], dec: 0)} / ${_fmt(report["weight"])}');
        addSection('Production Output');
        addRow('Boxes Produced', _fmt(report['boxes_produced'], dec: 0));
        addRow('Produced Rods', _fmt(report['produced_rods'], dec: 0));
        addRow('Machine Counter', _fmt(report['machine_counter'], dec: 0));
        addRow('Difference', '${_fmt(report["difference"])} (${report["diff_percent"] ?? "-"})');
        addRow('Waste (kg)', _fmt(report['waste_kg']));
        addRow('Efficiency (%)', _fmt(report['machine_efficiency']));
        addSection('Materials Used (Total)');
        addRow('Acetate', _fmt(report['total_acetate']));
        addRow('Paper', _fmt(report['total_paper']));
        addRow('PVA Glue', _fmt(report['total_pva']));
        addRow('Hot Melt Glue', _fmt(report['total_hm']));
        addRow('Triacetin', _fmt(report['total_triacetin']));
        addMaterials('Acetate', report['acetate_list'] as List?);
        addMaterials('Paper', report['paper_list'] as List?);
        addMaterials('PVA Glue', report['pva_list'] as List?);
        addMaterials('Hot Melt Glue', report['hm_list'] as List?);
        addMaterials('Triacetin', report['tri_list'] as List?);
        addSection('Remarks');
        rows.add(pw.Text(
          (report['remarks']?.toString().isNotEmpty == true) ? report['remarks'] : 'No comments.',
          style: const pw.TextStyle(fontSize: 10)));
        return [pw.Header(level: 0, text: 'Production Report'), ...rows];
      },
    ));
    await Printing.layoutPdf(onLayout: (_) => pdf.save(), name: 'report_${report["id"]}.pdf');
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border(left: BorderSide(color: Colors.grey.shade200)),
        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.06),
          blurRadius: 8, offset: const Offset(-2, 0))]),
      child: Column(children: [
        Container(
          color: const Color(0xFFF5F5F5),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(children: [
            const Icon(Icons.description, size: 18, color: Colors.deepPurple),
            const SizedBox(width: 8),
            Expanded(child: Text('Report #${report["id"] ?? ""}',
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14))),
            if (onArchiveToggle != null)
              IconButton(
                icon: Icon(report['is_archived'] == true ? Icons.unarchive : Icons.archive,
                  size: 18, color: Colors.brown),
                tooltip: report['is_archived'] == true ? 'Unarchive' : 'Archive',
                onPressed: onArchiveToggle,
                padding: EdgeInsets.zero, constraints: const BoxConstraints()),
            IconButton(
              icon: const Icon(Icons.print, size: 18, color: Colors.deepPurple),
              tooltip: 'Print / Save PDF',
              onPressed: () => _printPdf(context),
              padding: EdgeInsets.zero, constraints: const BoxConstraints()),
            const SizedBox(width: 4),
            IconButton(icon: const Icon(Icons.close, size: 18),
              onPressed: onClose, tooltip: 'Close',
              padding: EdgeInsets.zero, constraints: const BoxConstraints()),
          ]),
        ),
        const Divider(height: 1),
        Expanded(child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _row('Operator',   report['operator_name']   ?? '-'),
            _row('Date',       report['report_date']     ?? '-'),
            _row('Shift',      '${report['shift_name'] ?? '-'} (${report['shift_time_range'] ?? ''})'),
            _row('Machine',    report['machine_name']    ?? '-'),
            _row('PO Number',  report['po_number']       ?? '-', vc: Colors.deepPurple),

            _sec('TECHNICAL SPECIFICATION', [
              _row('Lot Number',       report['lot_number']  ?? '-'),
              _row('Box Type',         _fmt(report['box_type'], dec: 0)),
              _row('Diameter / Length','${_fmt(report["diameter"])} / ${_fmt(report["length"])}'),
              _row('PD / Weight',      '${_fmt(report["pd"], dec: 0)} / ${_fmt(report["weight"])}'),
            ]),

            _sec('PRODUCTION OUTPUT', [
              _row('Boxes Produced',  _fmt(report['boxes_produced'],  dec: 0)),
              _row('Produced Rods',   _fmt(report['produced_rods'],   dec: 0)),
              _row('Machine Counter', _fmt(report['machine_counter'], dec: 0)),
              _row('Difference',      '${_fmt(report["difference"])} (${report["diff_percent"] ?? "-"})'),
              _row('Waste (kg)',       _fmt(report['waste_kg'])),
              _row('Efficiency (%)',   _fmt(report['machine_efficiency'])),
            ]),

            _sec('MATERIALS USED (TOTAL)', [
              _row('Acetate',      _fmt(report['total_acetate'])),
              _row('Paper',        _fmt(report['total_paper'])),
              _row('PVA Glue',     _fmt(report['total_pva'])),
              _row('Hot Melt Glue',_fmt(report['total_hm'])),
              _row('Triacetin',    _fmt(report['total_triacetin'])),
            ]),

            _sec('MATERIAL BREAKDOWN', [
              _materialBreakdown('Acetate',      report['acetate_list'] as List?),
              _materialBreakdown('Paper',        report['paper_list']   as List?),
              _materialBreakdown('PVA Glue',     report['pva_list']     as List?),
              _materialBreakdown('Hot Melt Glue',report['hm_list']      as List?),
              _materialBreakdown('Triacetin',    report['tri_list']     as List?),
            ]),

            _sec('REMARKS', [
              Text(
                (report['remarks']?.toString().isNotEmpty == true)
                    ? report['remarks'].toString()
                    : 'No comments.',
                style: const TextStyle(fontSize: 13, fontStyle: FontStyle.italic)),
            ]),

            if (report['is_archived'] == true)
              Padding(padding: const EdgeInsets.only(top: 14),
                child: Chip(
                  avatar: const Icon(Icons.archive, size: 14, color: Colors.white),
                  label: const Text('Archived',
                    style: TextStyle(fontSize: 11, color: Colors.white)),
                  backgroundColor: Colors.brown, padding: EdgeInsets.zero,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap)),
            if (report['is_modified_manually'] == true)
              Padding(padding: const EdgeInsets.only(top: 14),
                child: Chip(
                  avatar: const Icon(Icons.edit, size: 14, color: Colors.white),
                  label: const Text('Manually edited',
                    style: TextStyle(fontSize: 11, color: Colors.white)),
                  backgroundColor: Colors.orange, padding: EdgeInsets.zero,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap)),
          ]),
        )),
      ]),
    );
  }
}
