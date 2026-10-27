// lib/dashboard/widgets/machine_widget.dart
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../dashboard_data.dart';
import 'manual_tests_dialog.dart';

class MachineWidget extends StatelessWidget {
  final Map<String, dynamic> config;
  final DashboardData data;
  const MachineWidget({super.key, required this.config, required this.data});

  @override
  Widget build(BuildContext context) {
    final alias = config['alias']?.toString();
    final machines = data.machines;
    Map<String, dynamic>? machine;
    for (final m in machines) {
      if (m['alias'] == alias) {
        machine = m;
        break;
      }
    }

    if (machine == null) {
      return Card(
        margin: EdgeInsets.zero,
        child: Center(
          child: Text(
            (alias == null || alias.isEmpty) ? 'No live data' : 'No live data for "$alias"',
            style: const TextStyle(color: Colors.grey, fontSize: 12),
          ),
        ),
      );
    }

    final state = (machine['state'] ?? 'offline').toString();
    final operator = machine['operator']?.toString();
    final activePo = machine['active_po']?.toString();
    final meanPd = _num(machine['mean_pd']);
    final meanDia = _num(machine['mean_dia']);
    final statusPd = machine['status_pd']?.toString();
    final statusDia = machine['status_dia']?.toString();
    final shiftStartedAt = machine['shift_started_at']?.toString();
    final lastMeasuredAt = machine['last_measured_at']?.toString();
    final lastManualTestAt = machine['last_manual_test_at']?.toString();

    final stateColor = switch (state) {
      'running' => Colors.green,
      'idle' => Colors.amber,
      _ => Colors.grey,
    };

    return Card(
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => _openKiosk(alias),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                const Icon(Icons.precision_manufacturing,
                    size: 18, color: Colors.deepPurple),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(alias ?? 'Machine',
                      style: const TextStyle(
                          fontSize: 14, fontWeight: FontWeight.w600),
                      overflow: TextOverflow.ellipsis),
                ),
                _StateBadge(label: state, color: stateColor),
              ]),
              const SizedBox(height: 10),
              _row('Operator', operator),
              _row('Active PO', activePo),
              _row('Active shift', _time(shiftStartedAt)),
              _row('Last sample', _relative(lastMeasuredAt)),
              _row('Last manual test',
                  (lastManualTestAt == null || lastManualTestAt.isEmpty)
                      ? 'No data'
                      : _relative(lastManualTestAt)),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(
                    child: _quality('Mean PD', meanPd, 'mm WG', statusPd, 1)),
                const SizedBox(width: 10),
                Expanded(
                    child: _quality('Mean Dia', meanDia, 'mm', statusDia, 3)),
              ]),
              const Spacer(),
              Row(children: [
                Icon(Icons.open_in_new, size: 12, color: Colors.grey[600]),
                const SizedBox(width: 4),
                Text('Open live quality',
                    style: TextStyle(fontSize: 10, color: Colors.grey[600])),
                const Spacer(),
                InkWell(
                  onTap: () => _openManualTests(context, machine!),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.fact_check_outlined,
                        size: 12, color: Colors.deepPurple),
                    const SizedBox(width: 4),
                    Text('Open manual tests',
                        style: TextStyle(
                            fontSize: 10, color: Colors.deepPurple)),
                  ]),
                ),
              ]),
            ],
          ),
        ),
      ),
    );
  }

  Widget _row(String label, String? value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 1),
        child: Row(children: [
          SizedBox(
              width: 80,
              child: Text(label,
                  style: TextStyle(fontSize: 11, color: Colors.grey[600]))),
          Expanded(
            child: Text(value ?? '—',
                style: const TextStyle(
                    fontSize: 12, fontWeight: FontWeight.w500),
                overflow: TextOverflow.ellipsis),
          ),
        ]),
      );

  Widget _quality(
      String label, double? value, String unit, String? status, int decimals) {
    final c = switch (status) {
      'GREEN' => Colors.green,
      'YELLOW' => Colors.amber,
      'RED' => Colors.red,
      _ => Colors.grey,
    };
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: c.withValues(alpha: 0.4)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: TextStyle(fontSize: 10, color: Colors.grey[600])),
        const SizedBox(height: 2),
        Text(value == null ? '—' : value.toStringAsFixed(decimals),
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        Text(unit, style: TextStyle(fontSize: 9, color: Colors.grey[600])),
      ]),
    );
  }

  Future<void> _openKiosk(String? alias) async {
    final a = (alias != null && alias.isNotEmpty) ? alias : 'M1';
    await launchUrl(
      Uri.base.resolve('/#/kiosk/quality?machine=${Uri.encodeComponent(a)}'),
      webOnlyWindowName: '_blank',
    );
  }

  void _openManualTests(BuildContext context, Map<String, dynamic> machine) {
    final id = (machine['machine_id'] as num?)?.toInt();
    if (id == null) return;
    showDialog(
      context: context,
      builder: (_) => ManualTestsDialog(
        machineId: id,
        machineName: machine['alias']?.toString(),
      ),
    );
  }

  double? _num(dynamic v) =>
      v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));

  String _time(String? iso) {
    if (iso == null || iso.isEmpty) return '—';
    final dt = DateTime.tryParse(iso)?.toLocal();
    if (dt == null) return '—';
    return DateFormat('HH:mm').format(dt);
  }

  String _relative(String? iso) {
    if (iso == null || iso.isEmpty) return '—';
    final dt = DateTime.tryParse(iso);
    if (dt == null) return '—';
    final diff = DateTime.now().difference(dt.toLocal());
    if (diff.inMinutes < 1) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    return '${diff.inDays}d ago';
  }
}

class _StateBadge extends StatelessWidget {
  final String label;
  final Color color;
  const _StateBadge({required this.label, required this.color});
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
            color: color.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(10)),
        child: Text(label,
            style: TextStyle(
                fontSize: 10, fontWeight: FontWeight.bold, color: color)),
      );
}
