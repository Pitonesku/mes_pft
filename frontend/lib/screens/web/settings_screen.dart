// lib/screens/web/settings_screen.dart
// Settings page with a "Quality & Tolerances" tab configuring factory-wide
// quality defaults (tolerance bands and SD status thresholds).
import 'package:flutter/material.dart';

import '../../api_service.dart';
import '../../theme/theme_controller.dart';
import '../../theme/theme_presets.dart';
import 'manual_tests_settings.dart';
import 'odoo_sync_screen.dart';
import 'station_profiles_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _diaTol = TextEditingController();
  final _pdTol = TextEditingController();
  final _triTarget = TextEditingController();
  final _triTol = TextEditingController();
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
    for (final c in [_diaTol, _pdTol, _triTarget, _triTol, _pdWarn, _pdFail, _diaWarn, _diaFail]) {
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
      _triTarget.text = '${s?['triacetin_target'] ?? ''}';
      _triTol.text = '${s?['triacetin_tolerance'] ?? ''}';
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
      'triacetin_target': _p(_triTarget),
      'triacetin_tolerance': _p(_triTol),
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
            Text(title, style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: Theme.of(context).colorScheme.primary)),
            const SizedBox(height: 16),
            ...children,
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 5,
      child: Column(children: [
        const Material(
          color: Colors.white,
          child: TabBar(
            labelColor: Colors.deepPurple,
            unselectedLabelColor: Colors.black54,
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: [
              Tab(text: 'Quality & Tolerances'),
              Tab(text: 'Odoo Integration'),
              Tab(text: 'General'),
              Tab(text: 'Quality Stations'),
              Tab(text: 'Manual Tests'),
            ],
          ),
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : TabBarView(children: [
                  _qualityTab(),
                  const OdooSyncScreen(),
                  _generalTab(),
                  const StationProfilesScreen(),
                  const ManualTestsSettings(),
                ]),
        ),
      ]),
    );
  }

  Widget _generalTab() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: ListenableBuilder(
            listenable: ThemeController.instance,
            builder: (context, _) {
              final c = ThemeController.instance;
              return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                _card('Appearance & Theme', [
                  const Text('Theme Mode', style: TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  SegmentedButton<ThemeMode>(
                    segments: const [
                      ButtonSegment(value: ThemeMode.light, label: Text('Light')),
                      ButtonSegment(value: ThemeMode.dark, label: Text('Dark')),
                      ButtonSegment(value: ThemeMode.system, label: Text('System')),
                    ],
                    selected: {c.mode},
                    onSelectionChanged: (s) => ThemeController.instance.setMode(s.first),
                  ),
                  const SizedBox(height: 16),
                  const Text('UI Style Preset', style: TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  SegmentedButton<ThemePreset>(
                    segments: const [
                      ButtonSegment(value: ThemePreset.cupertino, label: Text('iOS / Clean')),
                      ButtonSegment(value: ThemePreset.material3, label: Text('Material 3')),
                      ButtonSegment(value: ThemePreset.industrial, label: Text('Industrial Dark')),
                    ],
                    selected: {c.preset},
                    onSelectionChanged: (s) => ThemeController.instance.setPreset(s.first),
                  ),
                ]),
              ]);
            },
          ),
        ),
      ),
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
              const SizedBox(height: 12),
              Row(children: [
                Expanded(child: _f(_triTarget, 'Triacetin Target (%)')),
                const SizedBox(width: 16),
                Expanded(child: _f(_triTol, 'Triacetin Tolerance ± (%)')),
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
