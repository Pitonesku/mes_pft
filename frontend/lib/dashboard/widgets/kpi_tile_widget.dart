// lib/dashboard/widgets/kpi_tile_widget.dart
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../dashboard_data.dart';

class KpiTileWidget extends StatelessWidget {
  final Map<String, dynamic> config;
  final DashboardData data;
  const KpiTileWidget({super.key, required this.config, required this.data});

  @override
  Widget build(BuildContext context) {
    final metric = config['metric']?.toString() ?? 'output_today';
    final kpis = data.kpis;

    late String label, value;
    late IconData icon;
    late Color color;

    switch (metric) {
      case 'scrap_rate':
        label = 'Scrap Rate Today';
        final v = _num(kpis['scrap_rate_pct']);
        value = v == null ? '—' : '${v.toStringAsFixed(2)} %';
        icon = Icons.delete_outline;
        color = Colors.orange;
        break;
      case 'compliance':
        label = 'Quality Compliance';
        final v = _num(kpis['compliance_pct']);
        value = v == null ? '—' : '${v.toStringAsFixed(1)} %';
        icon = Icons.verified_outlined;
        color = Colors.green;
        break;
      case 'active_operators':
        label = 'Active Operators';
        value = '${kpis['active_operators'] ?? 0}';
        icon = Icons.people_outline;
        color = Colors.blue;
        break;
      default: // output_today
        label = 'Output Today';
        final v = (kpis['output_today'] as num?)?.toInt() ?? 0;
        value = NumberFormat.compact().format(v);
        icon = Icons.precision_manufacturing;
        color = Colors.indigo;
        break;
    }

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(children: [
          CircleAvatar(
            radius: 18,
            backgroundColor: color.withValues(alpha: 0.12),
            child: Icon(icon, color: color, size: 20),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(label,
                    style: TextStyle(
                        fontSize: 10,
                        color: Colors.grey[600],
                        fontWeight: FontWeight.w500),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis),
                const SizedBox(height: 1),
                Text(value,
                    style: const TextStyle(
                        fontSize: 19, fontWeight: FontWeight.bold)),
              ],
            ),
          ),
        ]),
      ),
    );
  }

  double? _num(dynamic v) =>
      v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));
}
