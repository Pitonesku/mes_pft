// lib/screens/web/report_full_screen.dart
// Full-page report view reached via /#/reports/{id}. Responsive two-column layout:
// left = specs / output / materials, right = quality summary / outliers / actions.
import 'package:flutter/material.dart';

import '../../api_service.dart';
import '../../core/app_navigation.dart';
import '../../core/open_new_tab.dart';
import '../../widgets/quality_control_chart.dart';
import '../../widgets/quality_report_dialog.dart';
import '../../widgets/report_verification_card.dart';
import '../../widgets/report_edit_form.dart';
import '../../widgets/report_history_dialog.dart';

class ReportFullScreen extends StatefulWidget {
  final int reportId;
  final VoidCallback onBack;
  final bool canModify;
  const ReportFullScreen({super.key, required this.reportId, required this.onBack, required this.canModify});
  @override
  State<ReportFullScreen> createState() => _ReportFullScreenState();
}

class _ReportFullScreenState extends State<ReportFullScreen> {
  int _currentId = 0;
  Map<String, dynamic>? _report;
  Map<String, dynamic>? _quality;
  int? _prevId;
  int? _nextId;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _currentId = widget.reportId;
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final r = await ApiService.fetchReport(_currentId);
    final q = await ApiService.fetchReportQuality(_currentId);
    final now = DateTime.now();
    final start = now.subtract(const Duration(days: 90));
    final reports = (await ApiService.fetchReports(
            startDate: start, endDate: now) ??
        [])
        .cast<Map<String, dynamic>>();
    final ids = <int>[];
    for (final rep in reports) {
      final id = rep['id'];
      if (id != null) ids.add(id is int ? id : int.tryParse('$id') ?? -1);
    }
    final index = ids.indexOf(_currentId);
    if (!mounted) return;
    setState(() {
      _report = r;
      _quality = q;
      _prevId = (index >= 0 && index < ids.length - 1) ? ids[index + 1] : null;
      _nextId = (index > 0) ? ids[index - 1] : null;
      _loading = false;
      _error = r == null ? 'Report not found' : null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(),
        const SizedBox(height: 16),
        Expanded(child: _body()),
      ]),
    );
  }

  Widget _header() => Row(children: [
        IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: widget.onBack,
            tooltip: 'Back'),
        const SizedBox(width: 4),
        TextButton.icon(
          icon: const Icon(Icons.chevron_left, size: 18),
          label: const Text('Previous Report'),
          onPressed: _prevId == null ? null : () => _goTo(_prevId!),
        ),
        Expanded(
          child: Text('Report #$_currentId',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
        ),
        TextButton.icon(
          icon: const Icon(Icons.chevron_right, size: 18),
          label: const Text('Next Report'),
          onPressed: _nextId == null ? null : () => _goTo(_nextId!),
        ),
        const SizedBox(width: 8),
        OutlinedButton.icon(
          icon: const Icon(Icons.print, size: 18),
          label: const Text('Print Quality Report'),
          onPressed: _printQualityReport,
        ),
        IconButton(
          icon: const Icon(Icons.open_in_new),
          tooltip: 'Open in new tab',
          onPressed: _openInNewTab,
        ),
      ]);

  Future<void> _printQualityReport() async {
    final d = await ApiService.fetchQualityData(
      reportId: _currentId,
      window: 'shift',
      includeRaw: true,
    );
    if (!mounted) return;
    if (d == null) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No quality data to print')));
      return;
    }
    final machines = (d['active_machines'] as List<dynamic>?) ?? const [];
    final reportMachine = _report?['machine_name']?.toString() ?? '';
    final selected = machines.contains(reportMachine)
        ? reportMachine
        : (machines.isNotEmpty ? machines.first.toString() : '');
    showDialog(
      context: context,
      builder: (_) => QualityReportDialog(data: d, machine: selected),
    );
  }

  void _goTo(int id) {
    setState(() => _currentId = id);
    _load();
  }

  void _openInNewTab() {
    openInNewTab(absoluteAppUrl('/reports/$_currentId'));
  }

  void _openQualityControl() {
    final shiftIdRaw = _quality?['shift_id'];
    AppNavigation.openQualityControl(
      machine: _report?['machine_name']?.toString(),
      shiftId: shiftIdRaw is int
          ? shiftIdRaw
          : (shiftIdRaw != null ? int.tryParse('$shiftIdRaw') : null),
      po: _report?['po_number']?.toString(),
    );
  }

  Future<void> _editReport() async {
    final report = _report;
    if (report == null) return;
    final payload = await showReportEditOverlay(context, report);
    if (payload == null || payload.isEmpty) return;
    final ok = await ApiService.updateReport(_currentId, payload);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(ok ? 'Report updated — re-verification required.' : 'Failed to update report.'),
      backgroundColor: ok ? Colors.green : Colors.red,
    ));
    if (ok) _load();
  }

  void _openHistory() {
    final report = _report;
    if (report == null) return;
    showReportHistoryDialog(context, report, onReverted: _load);
  }

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null || _report == null) {
      return Center(
          child: Text(_error ?? 'Report not found',
              style: const TextStyle(color: Colors.red)));
    }
    return SingleChildScrollView(
      child: LayoutBuilder(builder: (ctx, c) {
        final left = _leftColumn();
        final right = _rightColumn();
        if (c.maxWidth >= 900) {
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
                flex: 3,
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: left)),
            const SizedBox(width: 20),
            Expanded(
                flex: 2,
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: right)),
          ]);
        }
        return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [...left, const SizedBox(height: 20), ...right]);
      }),
    );
  }

  List<Widget> _leftColumn() => [
        _card('REPORT', [
          _row('Date', _report!['report_date']),
          _row('Shift',
              '${_report!['shift_name'] ?? '-'} (${_report!['shift_time_range'] ?? ''})'),
          _row('Machine', _report!['machine_name']),
          _row('PO Number', _report!['po_number'], vc: Colors.deepPurple),
        ]),
        _card('TECHNICAL SPECIFICATION', [
          _row('Lot Number', _report!['lot_number']),
          _row('Box Type', _fmt(_report!['box_type'], dec: 0)),
          _row('Diameter / Length',
              '${_fmt(_report!['diameter'])} / ${_fmt(_report!['length'])}'),
          _row('PD / Weight',
              '${_fmt(_report!['pd'], dec: 0)} / ${_fmt(_report!['weight'])}'),
        ]),
        _card('PRODUCTION OUTPUT', [
          _row('Boxes Produced', _fmt(_report!['boxes_produced'], dec: 0)),
          _row('Produced Rods', _fmt(_report!['produced_rods'], dec: 0)),
          _row('Machine Counter', _fmt(_report!['machine_counter'], dec: 0)),
          _row('Difference',
              '${_fmt(_report!['difference'])} (${_report!['diff_percent'] ?? '-'})'),
          _row('Waste (kg)', _fmt(_report!['waste_kg'])),
          _row('Efficiency (%)', _fmt(_report!['machine_efficiency'])),
        ]),
        _card('MATERIAL BREAKDOWN', [
          _materialBreakdown('Acetate', _report!['acetate_list']),
          _materialBreakdown('Paper', _report!['paper_list']),
          _materialBreakdown('PVA Glue', _report!['pva_list']),
          _materialBreakdown('Hot Melt Glue', _report!['hm_list']),
          _materialBreakdown('Triacetin', _report!['tri_list']),
        ]),
        if (_report!['remarks']?.toString().isNotEmpty == true)
          _card('REMARKS', [
            Text(_report!['remarks'].toString(),
                style: const TextStyle(fontSize: 13)),
          ]),
      ];

  List<Widget> _rightColumn() => [
        if (_quality?['series'] != null) ...[
          QualityControlChart(
            title: 'Pressure Drop (PD)',
            parameter: 'pd',
            lineColor: Colors.blue,
            series: _quality!['series'] as Map<String, dynamic>?,
            formatValue: (v) => v.toStringAsFixed(1),
          ),
          const SizedBox(height: 12),
          QualityControlChart(
            title: 'Diameter',
            parameter: 'diameter',
            lineColor: Colors.teal,
            series: _quality!['series'] as Map<String, dynamic>?,
            formatValue: (v) => v.toStringAsFixed(3),
          ),
          const SizedBox(height: 16),
        ],
        _card('VERIFICATION', [
          ReportVerificationCard(report: _report!, canVerify: widget.canModify, onVerified: _load),
        ]),
        _card('QUALITY SUMMARY', [_qualitySummary()]),
        _card('OUTLIERS', [_outliers()]),
        _card('ACTIONS', [
          OutlinedButton.icon(
            icon: const Icon(Icons.open_in_new, size: 16),
            label: const Text('Open in Quality Control'),
            onPressed: _openQualityControl,
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            icon: const Icon(Icons.history, size: 16),
            label: const Text('History'),
            onPressed: _openHistory,
          ),
          if (widget.canModify) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              icon: const Icon(Icons.edit, size: 16),
              label: const Text('Edit Report'),
              onPressed: _editReport,
            ),
          ],
        ]),
      ];

  Widget _card(String title, List<Widget> children) => Card(
        margin: const EdgeInsets.only(bottom: 16),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title,
                style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: Colors.deepPurple)),
            const Divider(height: 12),
            ...children,
          ]),
        ),
      );

  Widget _row(String label, dynamic value, {Color? vc}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
              width: 150,
              child: Text(label,
                  style: TextStyle(
                      fontSize: 12,
                      color: Colors.grey[600],
                      fontWeight: FontWeight.w500))),
          Expanded(
              child: Text(value?.toString() ?? '-',
                  style: TextStyle(
                      fontSize: 13, fontWeight: FontWeight.w600, color: vc))),
        ]),
      );

  String _fmt(dynamic v, {int dec = 2}) {
    if (v == null) return '-';
    if (v is num) return v.toStringAsFixed(dec);
    return v.toString();
  }

  Widget _materialBreakdown(String title, List<dynamic>? items) {
    if (items == null || items.isEmpty) return const SizedBox();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SizedBox(height: 6),
      Text(title,
          style: const TextStyle(fontSize: 11, fontWeight: FontWeight.bold)),
      const SizedBox(height: 2),
      for (final it in items)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 1),
          child: Row(children: [
            Expanded(
                child: Text(it['type']?.toString() ?? '-',
                    style: const TextStyle(fontSize: 11))),
            Text(
                it['batch']?.toString().isNotEmpty == true
                    ? it['batch'].toString()
                    : 'No Batch',
                style: TextStyle(fontSize: 11, color: Colors.grey[600])),
            const SizedBox(width: 8),
            Text('${_used(it)} kg',
                style: const TextStyle(
                    fontSize: 11, fontWeight: FontWeight.w600)),
          ]),
        ),
    ]);
  }

  double _used(Map<String, dynamic> it) {
    if (it['used'] != null) return double.tryParse(it['used'].toString()) ?? 0;
    final s = double.tryParse(it['start']?.toString() ?? '') ?? 0;
    final e = double.tryParse(it['stop']?.toString() ?? '') ?? 0;
    return s - e;
  }

  Widget _qualitySummary() {
    final params = (_quality?['parameters'] as Map<String, dynamic>?) ?? const {};
    final samples = _quality?['samples_count'] ?? 0;
    final status = (_quality?['status'] ?? '-').toString();
    if (params.isEmpty) {
      return const Text('No station measurements linked to this report.',
          style: TextStyle(fontSize: 12, color: Colors.grey));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Text('Tested samples: $samples',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
        const SizedBox(width: 10),
        _badge(status),
      ]),
      const SizedBox(height: 8),
      _paramsTable(params),
    ]);
  }

  Widget _paramsTable(Map<String, dynamic> params) {
    const order = ['diameter', 'pd', 'weight'];
    const labels = {
      'diameter': 'Diameter',
      'pd': 'Pressure Drop (PD)',
      'weight': 'Weight',
    };
    return Table(
      border: TableBorder.all(color: Colors.grey.shade300, width: 0.5),
      columnWidths: const {
        0: FlexColumnWidth(1.6),
        1: FlexColumnWidth(1),
        2: FlexColumnWidth(1),
        3: FlexColumnWidth(0.8),
      },
      children: [
        TableRow(
            decoration: const BoxDecoration(color: Color(0xFFF0F0F0)),
            children: const [
              Padding(
                  padding: EdgeInsets.all(4),
                  child: Text('Parameter',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold))),
              Padding(
                  padding: EdgeInsets.all(4),
                  child: Text('Mean',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold))),
              Padding(
                  padding: EdgeInsets.all(4),
                  child: Text('SD (n-1)',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold))),
              Padding(
                  padding: EdgeInsets.all(4),
                  child: Text('Status',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold))),
            ]),
        for (final k in order)
          if (params[k] is Map)
            TableRow(children: [
              Padding(
                  padding: const EdgeInsets.all(4),
                  child: Text(labels[k]!, style: const TextStyle(fontSize: 11))),
              Padding(
                  padding: const EdgeInsets.all(4),
                  child: Text(_fmt((params[k] as Map)['mean']),
                      style: const TextStyle(fontSize: 11))),
              Padding(
                  padding: const EdgeInsets.all(4),
                  child: Text(_fmt((params[k] as Map)['sd_samp']),
                      style: const TextStyle(fontSize: 11))),
              Padding(
                  padding: const EdgeInsets.all(4),
                  child: _badge(
                      ((params[k] as Map)['status'] ?? 'NOT_MEASURED').toString())),
            ]),
      ],
    );
  }

  Widget _outliers() {
    final total = _quality?['rods_total'] ?? 0;
    final rejected = _quality?['rods_rejected'] ?? 0;
    final used = _quality?['rods_used'] ?? 0;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _row('Rods tested', total),
      _row('Rejected (3× outlier)', rejected,
          vc: (rejected is num && rejected > 0) ? Colors.red : null),
      _row('Rods used', used),
      _row('Out-of-spec (kept)', _outOfSpecText()),
    ]);
  }

  String _outOfSpecText() {
    final params = (_quality?['parameters'] as Map<String, dynamic>?) ?? const {};
    final parts = <String>[];
    const labels = {'diameter': 'Dia', 'pd': 'PD', 'weight': 'Wt'};
    for (final k in ['diameter', 'pd', 'weight']) {
      final p = params[k];
      if (p is Map && p['out_of_spec'] != null) {
        parts.add('${labels[k]}: ${p['out_of_spec']}');
      }
    }
    return parts.isEmpty ? '-' : parts.join(' · ');
  }

  Widget _badge(String s) {
    Color c = Colors.grey;
    if (s == 'PASS' || s == 'GREEN') c = Colors.green;
    if (s == 'WARN' || s == 'YELLOW') c = Colors.orange;
    if (s == 'FAIL' || s == 'RED') c = Colors.red;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
          color: c.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(10)),
      child: Text(s,
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: c)),
    );
  }
}
