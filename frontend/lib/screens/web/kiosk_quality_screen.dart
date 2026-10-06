// lib/screens/web/kiosk_quality_screen.dart
// Full-screen, read-only shop-floor TV display. No login required.
import 'dart:async';
import 'package:flutter/material.dart';
import '../../api_service.dart';
import '../../widgets/quality_control_chart.dart';

class KioskQualityScreen extends StatefulWidget {
  final String initialMachine;
  const KioskQualityScreen({super.key, this.initialMachine = 'M1'});
  @override
  State<KioskQualityScreen> createState() => _KioskQualityScreenState();
}

class _KioskQualityScreenState extends State<KioskQualityScreen> {
  static const List<String> _machines = ['M1', 'M2'];
  late String _machine;
  String _windowType = 'rods';
  int _windowValue = 50;
  String _anchorMode = 'none';
  TimeOfDay? _anchorTime;
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _machine = _machines.contains(widget.initialMachine) ? widget.initialMachine : 'M1';
    _load();
    _timer = Timer.periodic(const Duration(seconds: 20), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final data = await ApiService.fetchLiveQuality(_machine, windowType: _windowType, windowValue: _windowValue, anchor: _anchorValue);
    if (!mounted) return;
    setState(() {
      _data = data;
      _loading = false;
      _error = data == null ? 'No data from server' : null;
    });
  }

  void _applyWindow(String type, int value) {
    setState(() { _windowType = type; _windowValue = value; _loading = true; });
    _load();
  }

  void _applyMachine(String m) {
    setState(() { _machine = m; _loading = true; });
    _load();
  }

  String? get _anchorValue {
    if (_anchorMode == 'shift_start') return 'shift_start';
    if (_anchorMode == 'custom' && _anchorTime != null) {
      final now = DateTime.now();
      final dt = DateTime(now.year, now.month, now.day, _anchorTime!.hour, _anchorTime!.minute);
      return dt.toIso8601String();
    }
    return null;
  }

  Future<void> _pickAnchorTime() async {
    final t = await showTimePicker(
      context: context,
      initialTime: _anchorTime ?? const TimeOfDay(hour: 6, minute: 0),
    );
    if (t != null) {
      setState(() { _anchorMode = 'custom'; _anchorTime = t; _loading = true; });
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0E1017),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(children: [
            _header(),
            const SizedBox(height: 16),
            _kpis(),
            const SizedBox(height: 16),
            Expanded(child: _charts()),
          ]),
        ),
      ),
    );
  }

  Widget _header() {
    final activePo = _data?['active_po'];
    return Row(children: [
      const Icon(Icons.factory, color: Colors.deepPurpleAccent, size: 30),
      const SizedBox(width: 12),
      const Text('QUALITY MONITOR', style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold, letterSpacing: 2)),
      const SizedBox(width: 24),
      _machineDropdown(),
      const SizedBox(width: 16),
      if (activePo != null) _badge('PO: $activePo', Colors.orange),
      const Spacer(),
      _anchorDropdown(),
      const SizedBox(width: 12),
      _windowButtons(),
    ]);
  }

  Widget _machineDropdown() => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12),
    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8)),
    child: DropdownButton<String>(
      value: _machine,
      items: _machines.map((m) => DropdownMenuItem(value: m, child: Text(m, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)))).toList(),
      onChanged: (v) { if (v != null) _applyMachine(v); },
      underline: const SizedBox.shrink(),
    ),
  );

  Widget _badge(String text, Color color) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
    decoration: BoxDecoration(color: color.withValues(alpha: 0.2), borderRadius: BorderRadius.circular(8), border: Border.all(color: color)),
    child: Text(text, style: TextStyle(color: color, fontSize: 15, fontWeight: FontWeight.bold)),
  );

  Widget _windowButtons() => Wrap(spacing: 8, children: [
    _windowChip('50 rods', 'rods', 50),
    _windowChip('100 rods', 'rods', 100),
  ]);

  Widget _anchorDropdown() => Row(children: [
    Container(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8)),
      child: DropdownButton<String>(
        value: _anchorMode,
        items: const [
          DropdownMenuItem(value: 'none', child: Text('Live (last N)')),
          DropdownMenuItem(value: 'shift_start', child: Text('Since shift start')),
          DropdownMenuItem(value: 'custom', child: Text('Since adjustment…')),
        ],
        onChanged: (v) {
          if (v == null) return;
          if (v == 'custom') { _pickAnchorTime(); return; }
          setState(() { _anchorMode = v; _loading = true; });
          _load();
        },
        underline: const SizedBox.shrink(),
      ),
    ),
    if (_anchorMode == 'custom' && _anchorTime != null) ...[
      const SizedBox(width: 8),
      Text(_anchorTime!.format(context), style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold)),
    ],
  ]);

  Widget _windowChip(String label, String type, int value) {
    final selected = _windowType == type && _windowValue == value;
    return ChoiceChip(
      label: Text(label, style: TextStyle(color: selected ? Colors.black : Colors.white, fontWeight: FontWeight.bold)),
      selected: selected,
      onSelected: (_) => _applyWindow(type, value),
      backgroundColor: const Color(0xFF1E2230),
      selectedColor: Colors.white,
      side: const BorderSide(color: Colors.white24),
      showCheckmark: false,
    );
  }

  Widget _kpis() {
    final meanPd = _num(_data?['mean_pd']);
    final sdPd = _num(_data?['sd_pd_unit']);
    final sdPdPct = _num(_data?['sd_pd_percent']);
    final meanDia = _num(_data?['mean_dia']);
    final sdDia = _num(_data?['sd_dia_mm']);
    final sdDiaPct = _num(_data?['sd_dia_percent']);
    return Row(children: [
      _kpiCard('MEAN PD', _fmt(meanPd, 1), 'mm WG', _statusColor(_data?['status_pd'])),
      _kpiCard('SD PD', _fmt(sdPd, 2), 'mm WG · ${_pct(sdPdPct)}', _statusColor(_data?['status_pd'])),
      _kpiCard('MEAN DIA', _fmt(meanDia, 3), 'mm', _statusColor(_data?['status_dia'])),
      _kpiCard('SD DIA', _fmt(sdDia, 4), 'mm · ${_pct(sdDiaPct)}', _statusColor(_data?['status_dia'])),
    ]);
  }

  Widget _kpiCard(String label, String value, String sub, Color status) {
    return Expanded(child: Container(
      margin: const EdgeInsets.symmetric(horizontal: 6),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: const Color(0xFF1A1E2B), borderRadius: BorderRadius.circular(12), border: Border.all(color: status, width: 2)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Container(width: 10, height: 10, decoration: BoxDecoration(color: status, shape: BoxShape.circle)), const SizedBox(width: 8), Text(label, style: const TextStyle(color: Colors.white70, fontSize: 13, letterSpacing: 1))]),
        const SizedBox(height: 8),
        Text(value, style: const TextStyle(color: Colors.white, fontSize: 34, fontWeight: FontWeight.bold)),
        Text(sub, style: const TextStyle(color: Colors.white54, fontSize: 13)),
      ]),
    ));
  }

  Widget _charts() {
    if (_loading) return const Center(child: CircularProgressIndicator(color: Colors.white));
    if (_error != null) return Center(child: Text(_error!, style: const TextStyle(color: Colors.white70, fontSize: 16)));
    final series = (_data?['series'] as Map<String, dynamic>?) ?? const {};
    return Column(children: [
      Expanded(child: QualityControlChart(title: 'Pressure Drop (PD)', parameter: 'pd', lineColor: Colors.blueAccent, series: series, formatValue: (v) => v.toStringAsFixed(1))),
      const SizedBox(height: 12),
      Expanded(child: QualityControlChart(title: 'Diameter', parameter: 'diameter', lineColor: Colors.tealAccent, series: series, formatValue: (v) => v.toStringAsFixed(3))),
    ]);
  }

  double? _num(dynamic v) => v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));
  String _pct(double? v) => v == null ? '—' : '${v.toStringAsFixed(1)}%';
  String _fmt(double? v, int d) => v == null ? '—' : v.toStringAsFixed(d);
  Color _statusColor(dynamic s) => switch (s) {
    'GREEN' => Colors.green,
    'YELLOW' => Colors.amber,
    'RED' => Colors.red,
    _ => Colors.grey,
  };
}