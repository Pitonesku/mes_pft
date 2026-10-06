// lib/dashboard/widgets/active_orders_widget.dart
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/app_navigation.dart';
import '../dashboard_data.dart';

class ActiveOrdersWidget extends StatelessWidget {
  final DashboardData data;
  const ActiveOrdersWidget({super.key, required this.data});

  @override
  Widget build(BuildContext context) {
    final orders = data.orders;
    return Card(
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        child: orders.isEmpty
            ? const Center(
                child: Text('No active orders',
                    style: TextStyle(color: Colors.grey)))
            : ListView.separated(
                itemCount: orders.length,
                separatorBuilder: (_, _) => const Divider(height: 12),
                itemBuilder: (ctx, i) => _orderRow(ctx, orders[i]),
              ),
      ),
    );
  }

  Widget _orderRow(BuildContext ctx, Map<String, dynamic> o) {
    final po = o['po_number']?.toString() ?? '—';
    final target = (o['target_qty'] as num?)?.toInt() ?? 0;
    final produced = (o['produced_qty'] as num?)?.toInt() ?? 0;
    final machine = o['machine']?.toString();
    final pct = target > 0 ? (produced / target).clamp(0.0, 1.0).toDouble() : 0.0;

    return InkWell(
      onTap: () => AppNavigation.openQualityControl(po: po),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Text(po,
                style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: Colors.deepPurple)),
          ),
          if (machine != null) ...[
            Icon(Icons.precision_manufacturing, size: 12, color: Colors.grey[600]),
            const SizedBox(width: 3),
            Text(machine,
                style: TextStyle(fontSize: 11, color: Colors.grey[600])),
          ],
        ]),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: pct,
            minHeight: 6,
            backgroundColor: Colors.grey.shade200,
            color: Colors.deepPurple,
          ),
        ),
        const SizedBox(height: 3),
        Text(
            '${NumberFormat.compact().format(produced)} / '
            '${NumberFormat.compact().format(target)} rods',
            style: TextStyle(fontSize: 10, color: Colors.grey[600])),
      ]),
    );
  }
}
