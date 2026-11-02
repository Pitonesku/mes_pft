// lib/dashboard/quality/triacetin_kpi_widget.dart
// Kiosk Quality-Monitor KPI tile for triacetin. Shows the current run's overall
// percentage plus the last single measurement (with its time) and the spec
// target, colour-coded by PASS/WARN/FAIL.
import 'package:flutter/material.dart';

import 'quality_data.dart';

class TriacetinKpiWidget extends StatelessWidget {
  final Map<String, dynamic> config;
  final QualityMonitorData data;

  const TriacetinKpiWidget({super.key, required this.config, required this.data});

  @override
  Widget build(BuildContext context) {
    final tri = data.triacetin;
    final overall = _num(tri?['overall']);
    final last = _num(tri?['last']);
    final lastAt = tri?['last_at']?.toString();
    final status = tri?['status']?.toString();
    final target = _num(tri?['target']);
    final tolerance = _num(tri?['tolerance']);
    final accent = _statusColor(status);
    final onFill = _onColor(accent);
    final subFill = _subOnColor(accent);
    final hasData = overall != null || last != null;

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
          Text('TRIACETIN',
              style: TextStyle(
                  color: subFill, fontSize: 12, letterSpacing: 0.5),
              maxLines: 1,
              overflow: TextOverflow.ellipsis),
          const SizedBox(height: 6),
          Expanded(
            child: hasData
                ? Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: Alignment.centerLeft,
                        child: Text(
                            overall == null ? '—' : '${overall.toStringAsFixed(2)} %',
                            style: TextStyle(
                                color: onFill,
                                fontSize: 30,
                                fontWeight: FontWeight.bold)),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        last == null
                            ? ''
                            : 'Last: ${last.toStringAsFixed(2)} % ${_fmtTime(lastAt)}',
                        style: TextStyle(color: subFill, fontSize: 11),
                      ),
                    ],
                  )
                : Center(
                    child: Text('No data',
                        style: TextStyle(
                            color: subFill,
                            fontSize: 14,
                            fontWeight: FontWeight.w500))),
          ),
          if (target != null)
            Text(
              'Target: ${target.toStringAsFixed(2)}'
              '${tolerance != null ? ' \u00b1 ${tolerance.toStringAsFixed(2)}' : ''} %',
              style: TextStyle(color: subFill, fontSize: 10),
            ),
        ],
      ),
    );
  }

  static const Color _neutral = Color(0xFF1A1E2B);

  double? _num(dynamic v) =>
      v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));

  Color _statusColor(String? s) => switch (s) {
        'PASS' => const Color(0xFF2E7D32),
        'WARN' => const Color(0xFFF9A825),
        'FAIL' => const Color(0xFFC62828),
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

  String _fmtTime(String? iso) {
    if (iso == null || iso.isEmpty) return '';
    final t = DateTime.tryParse(iso);
    if (t == null) return '';
    final l = t.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(l.hour)}:${two(l.minute)}';
  }
}
