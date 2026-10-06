// lib/dashboard/widgets/recent_reports_widget.dart
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/app_navigation.dart';

class RecentReportsWidget extends StatelessWidget {
  final List<Map<String, dynamic>> reports;
  const RecentReportsWidget({super.key, required this.reports});

  @override
  Widget build(BuildContext context) {
    if (reports.isEmpty) {
      return const Card(
        margin: EdgeInsets.zero,
        child: Center(
            child:
                Text('No recent reports', style: TextStyle(color: Colors.grey))),
      );
    }
    return Card(
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: SingleChildScrollView(
          child: DataTable(
            showCheckboxColumn: false,
            headingRowColor: WidgetStateProperty.all(const Color(0xFFF5F5F5)),
            columnSpacing: 20,
            dataRowColor: WidgetStateProperty.resolveWith((states) {
              if (states.contains(WidgetState.hovered)) {
                return Colors.deepPurple.withValues(alpha: 0.04);
              }
              return null;
            }),
            columns: const [
              DataColumn(label: Text('Date')),
              DataColumn(label: Text('Shift')),
              DataColumn(label: Text('Machine')),
              DataColumn(label: Text('Operator')),
              DataColumn(label: Text('PO')),
              DataColumn(label: Text('Rods'), numeric: true),
              DataColumn(label: Text('Submitted')),
            ],
            rows: reports.map((r) {
              String submitted = '-';
              try {
                final raw = r['sync_at']?.toString();
                if (raw != null && raw.isNotEmpty) {
                  submitted = DateFormat('dd MMM HH:mm')
                      .format(DateTime.parse(raw).toLocal());
                }
              } catch (_) {}
              return DataRow(
                onSelectChanged: (_) {
                  final id = r['id'];
                  if (id != null) {
                    AppNavigation.openReport(
                        id is int ? id : int.tryParse('$id') ?? -1);
                  }
                },
                cells: [
                  DataCell(Text(r['report_date'] ?? '')),
                  DataCell(Text(r['shift_name'] ?? '')),
                  DataCell(Text(r['machine_name'] ?? '')),
                  DataCell(Text(r['operator_name'] ?? '')),
                  DataCell(Text(r['po_number'] ?? '',
                      style: const TextStyle(
                          fontWeight: FontWeight.w600,
                          color: Colors.deepPurple))),
                  DataCell(Text('${r['produced_rods'] ?? 0}')),
                  DataCell(Text(submitted,
                      style: const TextStyle(
                          fontSize: 12, color: Colors.grey))),
                ],
              );
            }).toList(),
          ),
        ),
      ),
    );
  }
}
