// lib/screens/web/settings_screen.dart
// Settings page with a "Quality & Tolerances" tab configuring factory-wide
// quality defaults (tolerance bands and SD status thresholds).
import 'package:flutter/material.dart';

import '../../api_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _diaTol = TextEditingController();
  final _pdTol = TextEditingController();
  final _pdWarn = TextEditingController();
  final _pdFail = TextEditingController();
  final _diaWarn = TextEditingController();
  final _diaFail = TextEditingController();

  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in [_diaTol, _pdTol, _pdWarn, _pdFail, _diaWarn, _diaFail]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final s = await ApiService.fetchQualitySettings();
    if (!mounted) return;
    setState(() {
      _diaTol.text = '${s?['diameter_tolerance'] ?? ''}';
      _pdTol.text = '${s?['pd_tolerance'] ?? ''}';
      _pdWarn.text = '${s?['pd_sd_warn'] ?? ''}';
      _pdFail.text = '${s?['pd_sd_fail'] ?? ''}';
      _diaWarn.text = '${s?['dia_sd_warn'] ?? ''}';
      _diaFail.text = '${s?['dia_sd_fail'] ?? ''}';
      _loading = false;
    });
  }

  double? _p(TextEditingController c) =>
      double.tryParse(c.text.trim().replaceAll(',', '.'));

  Future<void> _save() async {
    final r = await ApiService.updateQualitySettings({
      'diameter_tolerance': _p(_diaTol),
      'pd_tolerance': _p(_pdTol),
      'pd_sd_warn': _p(_pdWarn),
      'pd_sd_fail': _p(_pdFail),
      'dia_sd_warn': _p(_diaWarn),
      'dia_sd_fail': _p(_diaFail),
    });
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(r == null ? 'Failed to save settings' : 'Settings saved'),
    ));
  }

  Widget _f(TextEditingController c, String label) => TextField(
        controller: c,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
      );

  Widget _card(String title, List<Widget> children) => Card(
        margin: const EdgeInsets.only(bottom: 16),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Colors.deepPurple)),
            const SizedBox(height: 16),
            ...children,
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Column(children: [
        const Material(
          color: Colors.white,
          child: TabBar(
            labelColor: Colors.deepPurple,
            unselectedLabelColor: Colors.black54,
            tabs: [
              Tab(text: 'Quality & Tolerances'),
              Tab(text: 'General'),
            ],
          ),
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : TabBarView(children: [
                  _qualityTab(),
                  const Center(child: Text('General settings coming soon.')),
                ]),
        ),
      ]),
    );
  }

  Widget _qualityTab() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            _card('Default Tolerances', [
              Row(children: [
                Expanded(child: _f(_diaTol, 'Diameter Tolerance ± (mm)')),
                const SizedBox(width: 16),
                Expanded(child: _f(_pdTol, 'PD Tolerance ± (mm WG)')),
              ]),
            ]),
            _card('Standard Deviation Thresholds (Yellow / Red)', [
              Row(children: [
                Expanded(child: _f(_pdWarn, 'PD SD Yellow (mm WG)')),
                const SizedBox(width: 16),
                Expanded(child: _f(_pdFail, 'PD SD Red (mm WG)')),
              ]),
              const SizedBox(height: 12),
              Row(children: [
                Expanded(child: _f(_diaWarn, 'Diameter SD Yellow (mm)')),
                const SizedBox(width: 16),
                Expanded(child: _f(_diaFail, 'Diameter SD Red (mm)')),
              ]),
            ]),
            Align(
              alignment: Alignment.centerRight,
              child: ElevatedButton.icon(
                onPressed: _save,
                icon: const Icon(Icons.save, size: 18),
                label: const Text('Save Settings'),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
