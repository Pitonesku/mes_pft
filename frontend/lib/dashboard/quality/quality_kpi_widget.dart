// lib/dashboard/quality/quality_kpi_widget.dart
// Compact, container-filling KPI card for one quality parameter. Renders a
// clean "No data" state when the selected parameter has no stats on this
// machine. Value typography scales down to fit via FittedBox.
import 'package:flutter/material.dart';

import 'quality_data.dart';
import 'quality_parameter.dart';

class QualityKpiWidget extends StatelessWidget {
  final Map<String, dynamic> config;
  final QualityMonitorData data;

  const QualityKpiWidget({super.key, required this.config, required this.data});

  @override
  Widget build(BuildContext context) {
    final param = qualityParameterByKey(config['parameter']?.toString() ?? 'pd');
    final metric = config['metric']?.toString() ?? 'mean';
    final entry = data.parameterEntry(param.key);
    final display =
        qualityDisplayFor(param.key, weightUnit: config['unit']?.toString());

    final mean = _scaled(_num(entry?['mean']), display.scale);
    final sd = _scaled(_num(entry?['sd_samp']), display.scale);
    final status = entry?['status']?.toString();
    final hasData = mean != null || sd != null;
    final accent = _statusColor(status);

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1A1E2B),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: accent, width: 2),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Row(children: [
            Container(
                width: 8,
                height: 8,
                decoration:
                    BoxDecoration(color: accent, shape: BoxShape.circle)),
            const SizedBox(width: 6),
            Expanded(
              child: Text(_label(param, metric),
                  style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 12,
                      letterSpacing: 0.5),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis),
            ),
          ]),
          const SizedBox(height: 6),
          Expanded(
            child: hasData
                ? _value(metric, mean, sd, display)
                : const Center(
                    child: Text('No data',
                        style: TextStyle(
                            color: Colors.white38,
                            fontSize: 14,
                            fontWeight: FontWeight.w500))),
          ),
          const SizedBox(height: 2),
          Text(display.unit,
              style: const TextStyle(color: Colors.white54, fontSize: 11)),
        ],
      ),
    );
  }

  Widget _value(String metric, double? mean, double? sd, QualityDisplay display) {
    final Widget primary;
    if (metric == 'sd') {
      primary = Text(sd == null ? '—' : _fmt(sd, display.decimals),
          style: const TextStyle(
              color: Colors.white, fontSize: 32, fontWeight: FontWeight.bold));
    } else if (metric == 'mean') {
      primary = Text(_fmt(mean, display.decimals),
          style: const TextStyle(
              color: Colors.white, fontSize: 32, fontWeight: FontWeight.bold));
    } else {
      primary = Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Mean ${_fmt(mean, display.decimals)}',
              style: const TextStyle(
                  color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
          Text('SD   ${sd == null ? '—' : _fmt(sd, display.decimals)}',
              style: const TextStyle(color: Colors.white70, fontSize: 14)),
        ],
      );
    }
    return FittedBox(
      fit: BoxFit.scaleDown,
      alignment: Alignment.centerLeft,
      child: primary,
    );
  }

  String _label(QualityParameter param, String metric) => switch (metric) {
        'sd' => 'SD ${param.short}',
        'mean_sd' => param.label,
        _ => 'MEAN ${param.short}',
      };

  double? _num(dynamic v) =>
      v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));

  double? _scaled(double? v, double scale) => v == null ? null : v * scale;

  String _fmt(double? v, int d) => v == null ? '—' : v.toStringAsFixed(d);

  Color _statusColor(String? s) => switch (s) {
        'PASS' => Colors.green,
        'WARN' => Colors.amber,
        'FAIL' => Colors.red,
        _ => Colors.grey,
      };
}