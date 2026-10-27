// lib/screens/web/manual_tests_settings.dart
// Admin UI for per-machine manual QC test configuration: pick a machine and
// toggle the Visible / Required flags for every manual test parameter.
import 'package:flutter/material.dart';

import '../../api_service.dart';

class ManualTestsSettings extends StatefulWidget {
  const ManualTestsSettings({super.key});
  @override
  State<ManualTestsSettings> createState() => _ManualTestsSettingsState();
}

class _ManualTestsSettingsState extends State<ManualTestsSettings> {
  bool _loading = true;
  bool _saving = false;
  List<dynamic> _machines = [];
  int? _machineId;
  List<Map<String, dynamic>> _parameters = [];
  final _reminderCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadMachines();
  }

  @override
  void dispose() {
    _reminderCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadMachines() async {
    setState(() => _loading = true);
    final machines = await ApiService.fetchMachines();
    if (!mounted) return;
    int? selected = _machineId;
    if (selected == null && machines != null && machines.isNotEmpty) {
      selected = ((machines.first as Map)['id'] as num).toInt();
    }
    setState(() {
      _machines = (machines ?? [])
          .where((m) => (m as Map)['is_inactive'] != true)
          .toList();
      _machineId = selected;
      _loading = false;
    });
    await _loadConfig();
  }

  Future<void> _loadConfig() async {
    final id = _machineId;
    if (id == null) {
      if (mounted) setState(() => _parameters = []);
      return;
    }
    final cfg = await ApiService.fetchMachineManualTestConfig(id);
    if (!mounted || _machineId != id) return;
    final params = <Map<String, dynamic>>[];
    for (final raw in (cfg?['parameters'] as List? ?? [])) {
      final p = raw as Map;
      params.add({
        'key': p['key'],
        'label': p['label'],
        'kind': p['kind'],
        'is_visible': p['is_visible'] == true,
        'is_required': p['is_required'] == true,
      });
    }
    final reminder = cfg?['reminder_interval_minutes'];
    setState(() {
      _parameters = params;
      _reminderCtrl.text =
          (reminder is num && reminder > 0) ? reminder.toInt().toString() : '';
    });
  }

  Future<void> _save() async {
    final id = _machineId;
    if (id == null || _saving) return;
    setState(() => _saving = true);
    final config = <String, Map<String, bool>>{};
    for (final p in _parameters) {
      config[p['key'] as String] = {
        'is_visible': p['is_visible'] == true,
        'is_required': p['is_required'] == true,
      };
    }
    final reminder = int.tryParse(_reminderCtrl.text.trim()) ?? 0;
    final ok = await ApiService.updateMachineManualTestConfig(id, config,
        reminderIntervalMinutes: reminder);
    if (!mounted) return;
    setState(() => _saving = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(ok == null ? 'Failed to save manual tests' : 'Manual tests saved'),
    ));
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : Card(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Manual Quality Tests',
                            style: TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.bold,
                                color: Theme.of(context).colorScheme.primary)),
                        const SizedBox(height: 16),
                        DropdownButtonFormField<int>(
                          key: ValueKey(_machineId),
                          initialValue: _machineId,
                          decoration: const InputDecoration(
                              labelText: 'Machine', border: OutlineInputBorder()),
                          items: [
                            for (final m in _machines)
                              DropdownMenuItem<int>(
                                value: ((m as Map)['id'] as num).toInt(),
                                child: Text('${m['name']}'),
                              ),
                          ],
                          onChanged: (v) {
                            setState(() => _machineId = v);
                            _loadConfig();
                          },
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _reminderCtrl,
                          keyboardType: TextInputType.number,
                          decoration: const InputDecoration(
                              labelText: 'Reminder interval (minutes, 0 = off)',
                              border: OutlineInputBorder()),
                        ),
                        const SizedBox(height: 16),
                        if (_machineId != null) ..._parameterRows(),
                        const SizedBox(height: 16),
                        Align(
                          alignment: Alignment.centerRight,
                          child: ElevatedButton.icon(
                            onPressed: _machineId == null || _saving ? null : _save,
                            icon: const Icon(Icons.save, size: 18),
                            label: const Text('Save Manual Tests'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
        ),
      ),
    );
  }

  List<Widget> _parameterRows() {
    return [
      Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(children: const [
          Expanded(
              flex: 3,
              child: Text('Parameter',
                  style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(
              flex: 1,
              child: Text('Visible',
                  style: TextStyle(fontWeight: FontWeight.bold),
                  textAlign: TextAlign.center)),
          Expanded(
              flex: 1,
              child: Text('Required',
                  style: TextStyle(fontWeight: FontWeight.bold),
                  textAlign: TextAlign.center)),
        ]),
      ),
      for (var i = 0; i < _parameters.length; i++)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(children: [
            Expanded(flex: 3, child: Text('${_parameters[i]['label']}')),
            Expanded(
                flex: 1,
                child: Checkbox(
                  value: _parameters[i]['is_visible'] == true,
                  onChanged: (v) =>
                      setState(() => _parameters[i]['is_visible'] = v ?? false),
                )),
            Expanded(
                flex: 1,
                child: Checkbox(
                  value: _parameters[i]['is_required'] == true,
                  onChanged: (v) =>
                      setState(() => _parameters[i]['is_required'] = v ?? false),
                )),
          ]),
        ),
    ];
  }
}

