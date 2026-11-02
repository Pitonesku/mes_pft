// lib/dashboard/widgets/triacetin_machines_widget.dart
// Web-console dashboard widget: a compact per-machine triacetin summary
// (overall % + last measurement + time), colour-coded by status.
import 'package:flutter/material.dart';

import '../dashboard_data.dart';

class TriacetinMachinesWidget extends StatelessWidget {
  final DashboardData data;
  const TriacetinMachinesWidget({super.key, required this.data});

  @override
  Widget build(BuildContext context) {
    final machines = data.machines;
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1A1E2B),
        borderRadius: BorderRadius.circular(10),
      ),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('TRIACETIN',
              style: TextStyle(
                  color: Colors.white70,
                  fontSize: 12,
                  letterSpacing: 0.5)),
          const SizedBox(height: 8),
          if (machines.isEmpty)
            const Expanded(
                child: Center(
                    child: Text('No machines',
                        style: TextStyle(color: Colors.white38))))
          else
            Expanded(
              child: ListView(
                children: machines.map((m) {
                  final overall = _num(m['triacetin_overall']);
                  final last = _num(m['triacetin_last']);
                  final at = m['triacetin_last_at']?.toString();
                  final status = m['triacetin_status']?.toString();
                  final target = _num(m['triacetin_target']);
                  final tol = _num(m['triacetin_tolerance']);
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Row(children: [
                      Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(
                              color: _statusColor(status),
                              shape: BoxShape.circle)),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(m['alias']?.toString() ?? '',
                            style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold)),
                      ),
                      Text(
                        overall == null ? '—' : '${overall.toStringAsFixed(2)} %',
                        style: const TextStyle(color: Colors.white),
                      ),
                      const SizedBox(width: 14),
                      SizedBox(
                        width: 130,
                        child: Text(
                          last == null
                              ? ''
                              : 'last ${last.toStringAsFixed(2)} % ${_fmtTime(at)}',
                          style: const TextStyle(
                              color: Colors.white54, fontSize: 11),
                          textAlign: TextAlign.right,
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 110,
                        child: Text(
                          target == null
                              ? ''
                              : 'tgt ${target.toStringAsFixed(2)}'
                                  '${tol != null ? '\u00b1${tol.toStringAsFixed(2)}' : ''}',
                          style: const TextStyle(
                              color: Colors.white38, fontSize: 10),
                          textAlign: TextAlign.right,
                        ),
                      ),
                    ]),
                  );
                }).toList(),
              ),
            ),
        ],
      ),
    );
  }

  double? _num(dynamic v) =>
      v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));

  Color _statusColor(String? s) => switch (s) {
        'PASS' => Colors.green,
        'WARN' => Colors.amber,
        'FAIL' => Colors.red,
        _ => Colors.grey,
      };

  String _fmtTime(String? iso) {
    if (iso == null || iso.isEmpty) return '';
    final t = DateTime.tryParse(iso);
    if (t == null) return '';
    final l = t.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(l.hour)}:${two(l.minute)}';
  }
}
