// lib/dashboard/quality/quality_kpi_widget.dart
// Compact, container-filling KPI card for one quality parameter. Renders a
// clean "No data" state when the selected parameter has no stats on this
// machine. Value typography scales down to fit via FittedBox.
//
// Colour rules (kiosk):
// * the tile is filled with the status colour (not just a border);
// * colour is driven ONLY by the standard deviation - PD and Diameter use the
//   server-side SD status, other parameters stay neutral regardless of mean;
// * SD decimals match the Quality Control page (PD 2, Diameter 3, ...).
import 'package:flutter/material.dart';

import 'quality_data.dart';
import 'quality_parameter.dart';

class QualityKpiWidget extends StatelessWidget {
  final Map<String, dynamic> config;
  final QualityMonitorData data;

  const QualityKpiWidget({super.key, required this.config, required this.data});

  static const Color _neutral = Color(0xFF1A1E2B);

  @override
  Widget build(BuildContext context) {
    final param = qualityParameterByKey(config['parameter']?.toString() ?? 'pd');
    final metric = config['metric']?.toString() ?? 'mean';
    final entry = data.parameterEntry(param.key);
    final display =
        qualityDisplayFor(param.key, weightUnit: config['unit']?.toString());

    final mean = _scaled(_num(entry?['mean']), display.scale);
    final sd = _scaled(_num(entry?['sd_samp']), display.scale);
    final hasData = mean != null || sd != null;

    // Colour comes from the SD status ONLY on SD tiles: mean tiles (and the
    // combined Mean+SD tile) are always neutral, never coloured by the
    // standard deviation.
    final status = metric == 'sd' ? _sdStatusFor(param.key) : null;
    final accent = _statusColor(status);
    final onFill = _onColor(accent);
    final subFill = _subOnColor(accent);
    final sdDecimals = _sdDecimals(param.key);

    return Container(
      decoration: BoxDecoration(
        color: accent,
        borderRadius: BorderRadius.circular(10),
        border: accent == _neutral
            ? Border.all(color: Colors.white24, width: 1)
            : null,
      ),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(_label(param, metric),
              style: TextStyle(
                  color: subFill, fontSize: 12, letterSpacing: 0.5),
              maxLines: 1,
              overflow: TextOverflow.ellipsis),
          const SizedBox(height: 6),
          Expanded(
            child: hasData
                ? _value(metric, mean, sd, display, sdDecimals, onFill, subFill)
                : Center(
                    child: Text('No data',
                        style: TextStyle(
                            color: subFill,
                            fontSize: 14,
                            fontWeight: FontWeight.w500))),
          ),
          const SizedBox(height: 2),
          Text(display.unit, style: TextStyle(color: subFill, fontSize: 11)),
        ],
      ),
    );
  }

  Widget _value(String metric, double? mean, double? sd, QualityDisplay display,
      int sdDecimals, Color onFill, Color subFill) {
    final Widget primary;
    if (metric == 'sd') {
      primary = Text(sd == null ? '—' : _fmt(sd, sdDecimals),
          style: TextStyle(
              color: onFill, fontSize: 32, fontWeight: FontWeight.bold));
    } else if (metric == 'mean') {
      primary = Text(_fmt(mean, display.decimals),
          style: TextStyle(
              color: onFill, fontSize: 32, fontWeight: FontWeight.bold));
    } else {
      primary = Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Mean ${_fmt(mean, display.decimals)}',
              style: TextStyle(
                  color: onFill, fontSize: 18, fontWeight: FontWeight.bold)),
          Text('SD   ${sd == null ? '—' : _fmt(sd, sdDecimals)}',
              style: TextStyle(color: subFill, fontSize: 14)),
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

  /// SD-only status per parameter: PD and Diameter have SD thresholds; all
  /// other parameters stay neutral (colour never follows mean/spec results).
  String? _sdStatusFor(String key) => switch (key) {
        'pd' => data.statusPd,
        'diameter' => data.statusDia,
        _ => null,
      };

  /// SD decimals matching the Quality Control page.
  int _sdDecimals(String key) => switch (key) {
        'pd' => 2,
        'diameter' => 3,
        'weight' => 3,
        'hardness' => 1,
        'length' => 0,
        _ => 2,
      };

  double? _num(dynamic v) =>
      v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));

  double? _scaled(double? v, double scale) => v == null ? null : v * scale;

  String _fmt(double? v, int d) => v == null ? '—' : v.toStringAsFixed(d);

  Color _statusColor(String? s) => switch (s) {
        'GREEN' || 'PASS' => const Color(0xFF2E7D32),
        'YELLOW' || 'WARN' => const Color(0xFFF9A825),
        'RED' || 'FAIL' => const Color(0xFFC62828),
        _ => _neutral,
      };

  Color _onColor(Color c) {
    if (c == const Color(0xFFF9A825)) return Colors.black87;
    return Colors.white;
  }

  Color _subOnColor(Color c) {
    if (c == const Color(0xFFF9A825)) return Colors.black54;
    return Colors.white70;
  }
}