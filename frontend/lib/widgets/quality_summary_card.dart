// lib/widgets/quality_summary_card.dart
// Collapsible "Quality Summary" card shown in the report detail panel.
// Uses pre-computed backend stats only (no local statistics).
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api_service.dart';
import '../core/app_navigation.dart';

class QualitySummaryCard extends StatefulWidget {
  final Map<String, dynamic> report;
  const QualitySummaryCard({super.key, required this.report});

  @override
  State<QualitySummaryCard> createState() => _QualitySummaryCardState();
}

class _QualitySummaryCardState extends State<QualitySummaryCard> {
  Map<String, dynamic>? _quality;
  bool _loading = false;
  bool _expanded = false;
  String? _error;
  Object? _loadedReportId;
  int _requestSeq = 0;

  @override
  void didUpdateWidget(covariant QualitySummaryCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.report['id'] != widget.report['id']) {
      _quality = null;
      _error = null;
      _loadedReportId = null;
      if (_expanded) _load();
    }
  }

  Future<void> _load() async {
    final id = widget.report['id'];
    if (id == null) {
      setState(() {
        _loading = false;
        _quality = null;
        _error = 'No report id';
      });
      return;
    }
    if (_quality != null && _loadedReportId == id) return;
    final seq = ++_requestSeq;
    setState(() {
      _loading = true;
      _error = null;
    });
    final q = await ApiService.fetchReportQuality(id is int ? id : int.tryParse('$id') ?? -1);
    if (!mounted || seq != _requestSeq) return;
    setState(() {
      _loading = false;
      _quality = q;
      _loadedReportId = id;
      if (q == null) _error = 'No quality data';
    });
  }

  void _toggle() {
    setState(() => _expanded = !_expanded);
    if (_expanded) _load();
  }

  Future<void> _open(String url) async {
    await launchUrl(Uri.base.resolve(url), webOnlyWindowName: '_blank');
  }

  @override
  Widget build(BuildContext context) {
    final shiftId = _quality?['shift_id'];
    return Container(
      margin: const EdgeInsets.only(top: 6),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.blueGrey.shade200),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(children: [
        InkWell(
          onTap: _toggle,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            child: Row(children: [
              Icon(_expanded ? Icons.expand_less : Icons.expand_more,
                  size: 18, color: Colors.blueGrey.shade700),
              const SizedBox(width: 6),
              const Icon(Icons.insights, size: 16, color: Colors.blueGrey),
              const SizedBox(width: 6),
              Text('Quality Summary',
                  style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      color: Colors.blueGrey.shade800)),
            ]),
          ),
        ),
        if (_expanded) ...[
          const Divider(height: 1),
          Padding(padding: const EdgeInsets.all(10), child: _body(shiftId)),
        ],
      ]),
    );
  }

  Widget _body(dynamic shiftId) {
    if (_loading) {
      return const Center(
          child: Padding(
              padding: EdgeInsets.all(6),
              child: SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2))));
    }
    if (_quality == null || shiftId == null) {
      return Text(_error ?? 'No quality data for this report.',
          style: const TextStyle(fontSize: 12, color: Colors.grey));
    }
    final params = (_quality?['parameters'] as Map<String, dynamic>?) ?? const {};
    final samples = _quality?['samples_count'] ?? 0;
    final status = (_quality?['status'] ?? '-').toString();

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Text('Tested samples: $samples',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
        const SizedBox(width: 10),
        _badge(status),
      ]),
      const SizedBox(height: 8),
      _table(params),
      const SizedBox(height: 10),
      Row(children: [
        Expanded(
            child: OutlinedButton.icon(
          icon: const Icon(Icons.picture_as_pdf, size: 15),
          label: const Text('Certificate', style: TextStyle(fontSize: 11)),
          onPressed: shiftId != null ? () => _open(ApiService.certificatePdfUrl(shiftId)) : null,
        )),
        const SizedBox(width: 6),
        Expanded(
            child: OutlinedButton.icon(
          icon: const Icon(Icons.open_in_new, size: 15),
          label: const Text('Open in Quality Control', style: TextStyle(fontSize: 11)),
          onPressed: () => AppNavigation.openQualityControl(
              machine: widget.report['machine_name']?.toString(),
              shiftId: shiftId is int ? shiftId : (shiftId != null ? int.tryParse('$shiftId') : null),
              po: widget.report['po_number']?.toString()),
        )),
      ]),
    ]);
  }

  Widget _badge(String s) {
    Color c = Colors.grey;
    if (s == 'PASS') c = Colors.green;
    if (s == 'WARN') c = Colors.orange;
    if (s == 'FAIL') c = Colors.red;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
          color: c.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(10)),
      child: Text(s,
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: c)),
    );
  }

  Widget _table(Map<String, dynamic> params) {
    const order = ['diameter', 'pd', 'weight'];
    const labels = {
      'diameter': 'Diameter',
      'pd': 'Pressure Drop (PD)',
      'weight': 'Weight',
    };
    String f(dynamic v, [int d = 3]) =>
        v == null ? '-' : (v is num ? v.toStringAsFixed(d) : '$v');

    return Table(
      border: TableBorder.all(color: Colors.grey.shade300, width: 0.5),
      columnWidths: const {
        0: FlexColumnWidth(1.8),
        1: FlexColumnWidth(1.2),
        2: FlexColumnWidth(1.2),
        3: FlexColumnWidth(1),
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
                  child: Text('Sample SD',
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
                  child: Text(f((params[k] as Map)['mean']),
                      style: const TextStyle(fontSize: 11))),
              Padding(
                  padding: const EdgeInsets.all(4),
                  child: Text(f((params[k] as Map)['sd_samp']),
                      style: const TextStyle(fontSize: 11))),
              Padding(
                  padding: const EdgeInsets.all(4),
                  child: _badge(
                      ((params[k] as Map)['status'] ?? 'NOT_MEASURED').toString())),
            ]),
      ],
    );
  }
}