// lib/dashboard/quality/quality_config_dialogs.dart
// Configuration dialog for Quality Monitor widgets: parameter selector for
// both widget types, a metric selector (Mean / SD / Mean+SD) and a grams/mg
// toggle for weight, plus optional Y-axis bounds for charts.
import 'package:flutter/material.dart';

import 'quality_parameter.dart';

Future<Map<String, dynamic>?> promptQualityWidgetConfig(
  BuildContext context,
  String type,
  Map<String, dynamic> current,
) async {
  final isKpi = type == 'quality_kpi';
  var parameter = current['parameter']?.toString() ?? 'pd';
  var metric = current['metric']?.toString() ?? 'mean';
  var weightUnit = current['unit']?.toString() ?? 'g';
  final yMinCtrl = TextEditingController(text: current['yMin']?.toString() ?? '');
  final yMaxCtrl = TextEditingController(text: current['yMax']?.toString() ?? '');

  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: Text(isKpi ? 'Quality KPI Widget' : 'Control Chart Widget'),
        content: SizedBox(
          width: 340,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<String>(
                initialValue: parameter,
                decoration: const InputDecoration(labelText: 'Parameter'),
                items: [
                  for (final p in qualityParameters)
                    DropdownMenuItem(
                        value: p.key, child: Text('${p.label} (${p.unit})')),
                ],
                onChanged: (v) => setState(() => parameter = v ?? 'pd'),
              ),
              if (parameter == 'weight') ...[
                const SizedBox(height: 16),
                SegmentedButton<String>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(value: 'g', label: Text('Grams (g)')),
                    ButtonSegment(value: 'mg', label: Text('Milligrams (mg)')),
                  ],
                  selected: {weightUnit},
                  onSelectionChanged: (sel) =>
                      setState(() => weightUnit = sel.first),
                ),
              ],
              if (isKpi) ...[
                const SizedBox(height: 16),
                SegmentedButton<String>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(value: 'mean', label: Text('Mean')),
                    ButtonSegment(value: 'sd', label: Text('SD')),
                    ButtonSegment(value: 'mean_sd', label: Text('Mean + SD')),
                  ],
                  selected: {metric},
                  onSelectionChanged: (sel) =>
                      setState(() => metric = sel.first),
                ),
              ],
              if (!isKpi) ...[
                const SizedBox(height: 16),
                Row(children: [
                  Expanded(
                    child: TextField(
                      controller: yMinCtrl,
                      keyboardType:
                          const TextInputType.numberWithOptions(decimal: true),
                      decoration: const InputDecoration(
                          labelText: 'Y-Axis Min', hintText: 'auto'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextField(
                      controller: yMaxCtrl,
                      keyboardType:
                          const TextInputType.numberWithOptions(decimal: true),
                      decoration: const InputDecoration(
                          labelText: 'Y-Axis Max', hintText: 'auto'),
                    ),
                  ),
                ]),
              ],
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              final result = <String, dynamic>{
                'parameter': parameter,
                if (isKpi) 'metric': metric,
              };
              if (parameter == 'weight') result['unit'] = weightUnit;
              if (!isKpi) {
                final yMin = double.tryParse(yMinCtrl.text.trim());
                final yMax = double.tryParse(yMaxCtrl.text.trim());
                if (yMin != null) result['yMin'] = yMin;
                if (yMax != null) result['yMax'] = yMax;
              }
              Navigator.pop(context, result);
            },
            child: const Text('OK'),
          ),
        ],
      ),
    ),
  );
}