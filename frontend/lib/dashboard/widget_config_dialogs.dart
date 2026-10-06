// lib/dashboard/widget_config_dialogs.dart
import 'package:flutter/material.dart';

/// Prompts for a widget's configuration and returns it, or null on cancel.
Future<Map<String, dynamic>?> promptWidgetConfig(
  BuildContext context,
  String type,
  Map<String, dynamic> current,
  List<String> machineAliases,
) async {
  if (type == 'machine') {
    final currentAlias = current['alias']?.toString();
    var selected = machineAliases.contains(currentAlias)
        ? currentAlias
        : (machineAliases.isNotEmpty ? machineAliases.first : null);
    return showDialog<Map<String, dynamic>>(
      context: context,
      builder: (ctx) => _ConfigDialog(
        title: 'Machine Widget',
        child: DropdownButtonFormField<String>(
          initialValue: selected,
          decoration: const InputDecoration(labelText: 'Machine'),
          items: [
            for (final a in machineAliases)
              DropdownMenuItem(value: a, child: Text(a)),
          ],
          onChanged: (v) => selected = v,
        ),
        onOk: () => selected == null ? null : {'alias': selected},
      ),
    );
  }
  if (type == 'kpi') {
    const metrics = [
      ('output_today', 'Output Today'),
      ('scrap_rate', 'Scrap Rate Today'),
      ('compliance', 'Quality Compliance'),
      ('active_operators', 'Active Operators'),
    ];
    var selected = current['metric']?.toString() ?? 'output_today';
    return showDialog<Map<String, dynamic>>(
      context: context,
      builder: (ctx) => _ConfigDialog(
        title: 'KPI Widget',
        child: DropdownButtonFormField<String>(
          initialValue: selected,
          decoration: const InputDecoration(labelText: 'Metric'),
          items: [
            for (final m in metrics)
              DropdownMenuItem(value: m.$1, child: Text(m.$2)),
          ],
          onChanged: (v) => selected = v ?? 'output_today',
        ),
        onOk: () => {'metric': selected},
      ),
    );
  }
  return const {};
}

class _ConfigDialog extends StatelessWidget {
  final String title;
  final Widget child;
  final Map<String, dynamic>? Function() onOk;
  const _ConfigDialog({
    required this.title,
    required this.child,
    required this.onOk,
  });

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(title),
        content: SizedBox(width: 320, child: child),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, onOk()),
            child: const Text('OK'),
          ),
        ],
      );
}
