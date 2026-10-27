// lib/screens/mobile/manual_quality_checks_screen.dart
// Operator "Quality Checks" tab. The machine and MO shown here (and stamped on every
// check) come from the SERVER's open run of the shift, so they follow an MO / machine
// change; the cached ShiftContext is only used to find the shift id.
import 'package:flutter/material.dart';
import '../../api_service.dart';
import '../../shift_context.dart';
import '../../dead_man_switch.dart';

class ManualQualityChecksScreen extends StatefulWidget {
  final ShiftContext? shiftContext;
  const ManualQualityChecksScreen({super.key, this.shiftContext});
  @override
  State<ManualQualityChecksScreen> createState() => _ManualQualityChecksScreenState();
}

class _ManualQualityChecksScreenState extends State<ManualQualityChecksScreen> {
  ShiftContext? _ctx;
  Map<String, dynamic>? _run; // the shift's currently open run (server truth)
  bool _loading = true;
  bool _submitting = false;
  int _queued = 0;

  final _weightCtrl = TextEditingController();
  final _rodsCtrl = TextEditingController(text: '10');
  final _lengthCtrl = TextEditingController();
  final _hardnessCtrl = TextEditingController();
  final _notesCtrl = TextEditingController();
  final _triWetCtrl = TextEditingController();
  final _triDryCtrl = TextEditingController();
  final _triRodsCtrl = TextEditingController();
  // Tri-state: null = not checked, true = OK, false = FAIL.
  bool? _glue;
  bool? _cut;
  bool? _visual;

  // Per-machine manual-test config: key -> {is_visible, is_required}.
  // Defaults to "all visible, none required" when the config is unavailable.
  Map<String, Map<String, bool>> _cfg = {};

  List<dynamic> _checks = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _weightCtrl.dispose();
    _rodsCtrl.dispose();
    _lengthCtrl.dispose();
    _hardnessCtrl.dispose();
    _notesCtrl.dispose();
    _triWetCtrl.dispose();
    _triDryCtrl.dispose();
    _triRodsCtrl.dispose();
    super.dispose();
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _load() async {
    final ctx = widget.shiftContext ?? await ApiService.loadShiftContext();
    if (ctx == null) {
      if (mounted) setState(() => _loading = false);
      return;
    }
    await ApiService.flushManualCheckQueue();
    final detail = await ApiService.fetchShiftDetail(ctx.shiftId);
    Map<String, dynamic>? open;
    for (final r in (detail?['runs'] as List? ?? [])) {
      if (r['ended_at'] == null) open = Map<String, dynamic>.from(r as Map);
    }
    final checks = await ApiService.fetchManualChecks(shiftId: ctx.shiftId);
    final queued = (await ApiService.pendingManualChecks()).length;
    final machineId = open?['machine_id'];
    Map<String, Map<String, bool>> cfg = {};
    if (machineId != null) {
      final c = await ApiService.fetchMachineManualTestConfig((machineId as num).toInt());
      for (final raw in (c?['parameters'] as List? ?? [])) {
        final p = raw as Map;
        cfg[p['key'] as String] = {
          'is_visible': p['is_visible'] == true,
          'is_required': p['is_required'] == true,
        };
      }
    }
    if (!mounted) return;
    setState(() {
      _ctx = ctx;
      _run = open;
      _checks = checks ?? [];
      _queued = queued;
      _cfg = cfg;
      _loading = false;
    });
  }

  String _machineName(dynamic id) {
    if (id == null) return '';
    if (id == _ctx?.machineId) return _ctx?.machineName ?? 'Machine #$id';
    return 'Machine #$id';
  }

  /// Live hint mirroring the server's weight auto-detection: shows the per-rod
  /// interpretation (and the unit) so an operator can catch a mis-typed rod
  /// count. The server remains the authoritative normaliser.
  String? _weightHint() {
    final raw = _weightCtrl.text.trim();
    if (raw.isEmpty) return null;
    final v = double.tryParse(raw.replaceAll(',', '.'));
    if (v == null) return 'Not a number';
    final rods = int.tryParse(_rodsCtrl.text.trim());
    if (rods == null || rods <= 0) return null;
    const lo = 0.2, hi = 1.0; // g/rod detection band (200-1000 mg)
    final options = <String, double>{
      'total g': v / rods,
      'mg/rod': v / 1000,
      'g/rod': v,
      'total mg': v / (1000 * rods),
    };
    final plausible =
        options.entries.where((e) => e.value >= lo && e.value <= hi).toList();
    if (plausible.isEmpty) {
      final loG = (lo * rods).toStringAsFixed(1);
      final hiG = (hi * rods).toStringAsFixed(1);
      return 'Doesn\'t fit $rods rods (expect ~$loG-$hiG g total, or 300-700 mg/rod)';
    }
    final pick = plausible.first;
    return '→ ${(pick.value * 1000).round()} mg/rod (${pick.key})';
  }

  bool _visible(String key) => _cfg[key]?['is_visible'] ?? true;

  bool _required(String key) => _cfg[key]?['is_required'] ?? false;

  /// Live manual triacetin result: (wet - dry) / dry * 100 (mg in, % out).
  double? _triacetinPct() {
    final wet = double.tryParse(_triWetCtrl.text.trim().replaceAll(',', '.'));
    final dry = double.tryParse(_triDryCtrl.text.trim().replaceAll(',', '.'));
    if (wet == null || dry == null || dry <= 0) return null;
    return (wet - dry) / dry * 100.0;
  }

  String? _firstMissingRequired(double? weight, double? length, double? hardness,
      double? triWet, double? triDry, int? triRods) {
    String? miss(bool visible, bool required, bool filled, String label) =>
        (visible && required && !filled) ? label : null;
    return miss(_visible('weight'), _required('weight'), weight != null, 'Weight') ??
        miss(_visible('length'), _required('length'), length != null, 'Length') ??
        miss(_visible('hardness'), _required('hardness'), hardness != null, 'Hardness') ??
        miss(_visible('glue_seam'), _required('glue_seam'), _glue != null, 'Glue Seam') ??
        miss(_visible('cut_quality'), _required('cut_quality'), _cut != null, 'Cut Quality') ??
        miss(_visible('visual_cleanness'), _required('visual_cleanness'), _visual != null, 'Visual Cleanness') ??
        miss(_visible('triacetin'), _required('triacetin'),
            triWet != null && triDry != null && triRods != null, 'Triacetin');
  }

  Future<void> _submit() async {
    final c = _ctx;
    if (c == null || _submitting) return;
    final weight = double.tryParse(_weightCtrl.text.trim().replaceAll(',', '.'));
    final length = double.tryParse(_lengthCtrl.text.trim().replaceAll(',', '.'));
    final hardness = double.tryParse(_hardnessCtrl.text.trim().replaceAll(',', '.'));
    final triWet = double.tryParse(_triWetCtrl.text.trim().replaceAll(',', '.'));
    final triDry = double.tryParse(_triDryCtrl.text.trim().replaceAll(',', '.'));
    final triRods = int.tryParse(_triRodsCtrl.text.trim());
    final notes = _notesCtrl.text.trim();

    final missing = _firstMissingRequired(weight, length, hardness, triWet, triDry, triRods);
    if (missing != null) {
      _toast('$missing is required for this machine');
      return;
    }

    final hasTri = triWet != null || triDry != null || triRods != null;
    if (weight == null && length == null && hardness == null && _glue == null &&
        _cut == null && _visual == null && !hasTri && notes.isEmpty) {
      _toast('Enter a value, tick a check or add a note');
      return;
    }
    if (hasTri && (triWet == null || triDry == null || triDry <= 0 || triRods == null)) {
      _toast('Triacetin needs wet weight, dry weight and rod count');
      return;
    }

    setState(() => _submitting = true);
    // shift_id only; the server binds the open run (machine + MO) itself.
    final saved = await ApiService.submitManualCheckQueued({
      'shift_id': c.shiftId,
      'sample_weight': weight,
      'sample_rods': int.tryParse(_rodsCtrl.text.trim()) ?? 10,
      'length_mm': length,
      'hardness': hardness,
      'glue_seam_ok': _glue,
      'cut_quality_ok': _cut,
      'visual_appearance_ok': _visual,
      'triacetin_wet_mg': triWet,
      'triacetin_dry_mg': triDry,
      'triacetin_rods': triRods,
      'notes': notes.isEmpty ? null : notes,
    });
    if (!mounted) return;
    setState(() => _submitting = false);
    final status = ApiService.lastApiStatus ?? 0;
    if (saved == null && status >= 400 && status < 500) {
      _toast('Not saved: ${ApiService.lastApiDetail ?? 'rejected'}');
      return;
    }
    DeadManSwitch.instance.reset();
    _toast(saved == null
        ? 'Offline - saved on this tablet, will be sent later'
        : 'QC check saved (${saved['overall_status'] ?? 'no limits'})');
    _weightCtrl.clear();
    _lengthCtrl.clear();
    _hardnessCtrl.clear();
    _triWetCtrl.clear();
    _triDryCtrl.clear();
    _triRodsCtrl.clear();
    _notesCtrl.clear();
    setState(() {
      _glue = null;
      _cut = null;
      _visual = null;
    });
    _load();
  }

  Future<void> _void(Map c) async {
    final reasonCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Void this check?'),
        content: TextField(
            controller: reasonCtrl,
            decoration: const InputDecoration(labelText: 'Reason (required)')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(d, true), child: const Text('Void')),
        ],
      ),
    );
    final reason = reasonCtrl.text.trim();
    reasonCtrl.dispose();
    if (ok != true || reason.isEmpty) return;
    final done = await ApiService.voidManualCheck(c['id'] as int, reason);
    _toast(done ? 'Check voided' : 'Failed: ${ApiService.lastApiDetail ?? ''}');
    if (done) _load();
  }


  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Quality Checks'),
        backgroundColor: Colors.deepPurple,
        foregroundColor: Colors.white,
        actions: [IconButton(icon: const Icon(Icons.refresh), onPressed: _load)],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _ctx == null
              ? _buildNoShift()
              : _buildChecks(),
    );
  }

  Widget _buildNoShift() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.schedule, size: 64, color: Colors.grey),
          const SizedBox(height: 16),
          const Text('No active shift',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          const Text(
            'Start your shift from the main report screen first.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey),
          ),
          const SizedBox(height: 16),
          FilledButton(
              onPressed: () => Navigator.pop(context), child: const Text('Back')),
        ]),
      ),
    );
  }

  Widget _buildHeader() {
    final run = _run;
    final machine = _machineName(run?['machine_id'] ?? _ctx?.machineId);
    final mo = run?['mo_ref'] ?? _ctx?.moRef ?? 'no MO';
    return Card(
      color: Colors.deepPurple.shade50,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(children: [
          const Icon(Icons.precision_manufacturing, color: Colors.deepPurple),
          const SizedBox(width: 10),
          Expanded(
            child: Text('$machine  •  MO $mo  •  ${_ctx?.shiftName ?? ''}',
                style: const TextStyle(fontWeight: FontWeight.bold)),
          ),
        ]),
      ),
    );
  }

  Widget _buildChecks() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _buildHeader(),
        if (_queued > 0)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('$_queued check(s) waiting to be sent (offline)',
                style: const TextStyle(color: Colors.orange)),
          ),
        const SizedBox(height: 16),
        if (_visible('weight'))
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
                flex: 3,
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      TextField(
                          controller: _weightCtrl,
                          keyboardType:
                              const TextInputType.numberWithOptions(decimal: true),
                          onChanged: (_) => setState(() {}),
                          decoration: const InputDecoration(
                              labelText: 'Weight (g total / mg per rod)',
                              border: OutlineInputBorder())),
                      if (_weightHint() != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 2, left: 2),
                          child: Text(_weightHint()!,
                              style: const TextStyle(
                                  fontSize: 12, color: Colors.blueGrey)),
                        ),
                    ])),
            const SizedBox(width: 12),
            Expanded(
                flex: 2,
                child: TextField(
                    controller: _rodsCtrl,
                    keyboardType: TextInputType.number,
                    onChanged: (_) => setState(() {}),
                    decoration: const InputDecoration(
                        labelText: 'per N rods', border: OutlineInputBorder()))),
          ]),
        if (_visible('length')) ...[
          const SizedBox(height: 12),
          TextField(
              controller: _lengthCtrl,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: 'Length (mm)', border: OutlineInputBorder())),
        ],
        if (_visible('hardness')) ...[
          const SizedBox(height: 12),
          TextField(
              controller: _hardnessCtrl,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: 'Hardness (%)', border: OutlineInputBorder())),
        ],
        if (_visible('glue_seam') ||
            _visible('cut_quality') ||
            _visible('visual_cleanness'))
          const SizedBox(height: 16),
        if (_visible('glue_seam'))
          _triState('Glue Seam', _glue, (v) => setState(() => _glue = v)),
        if (_visible('cut_quality'))
          _triState('Cut Quality', _cut, (v) => setState(() => _cut = v)),
        if (_visible('visual_cleanness'))
          _triState('Visual Cleanness', _visual, (v) => setState(() => _visual = v)),
        if (_visible('triacetin')) ...[
          const SizedBox(height: 16),
          const Text('Triacetin (manual fallback)',
              style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
                child: TextField(
                    controller: _triWetCtrl,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    onChanged: (_) => setState(() {}),
                    decoration: const InputDecoration(
                        labelText: 'Wet Weight (mg)',
                        border: OutlineInputBorder()))),
            const SizedBox(width: 12),
            Expanded(
                child: TextField(
                    controller: _triDryCtrl,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    onChanged: (_) => setState(() {}),
                    decoration: const InputDecoration(
                        labelText: 'Dry Weight (mg)',
                        border: OutlineInputBorder()))),
            const SizedBox(width: 12),
            Expanded(
                child: TextField(
                    controller: _triRodsCtrl,
                    keyboardType: TextInputType.number,
                    onChanged: (_) => setState(() {}),
                    decoration: const InputDecoration(
                        labelText: 'Rods Count', border: OutlineInputBorder()))),
          ]),
          if (_triacetinPct() != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('Triacetin: ${_triacetinPct()!.toStringAsFixed(2)} %',
                  style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                      color: Colors.deepPurple)),
            ),
        ],
        const SizedBox(height: 12),
        TextField(
            controller: _notesCtrl,
            decoration: const InputDecoration(
                labelText: 'Notes (optional)', border: OutlineInputBorder())),
        const SizedBox(height: 20),
        FilledButton.icon(
          onPressed: (_submitting || _run == null) ? null : _submit,
          icon: const Icon(Icons.check),
          label: Text(_submitting ? 'Submitting…' : 'Submit QC Check'),
        ),
        if (_run == null)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('No open MO run on this shift - pick an MO first.',
                style: TextStyle(color: Colors.red)),
          ),
        const SizedBox(height: 24),
        const Text('Shift Timeline', style: TextStyle(fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        if (_checks.isEmpty) const Text('No checks recorded yet.') else ..._timeline(),
      ]),
    );
  }


  /// All checks of the shift, grouped by MO / machine; the current run is
  /// highlighted instead of hiding the earlier MOs.
  List<Widget> _timeline() {
    final widgets = <Widget>[];
    String? lastKey;
    for (final raw in _checks) {
      final c = raw as Map;
      final key = '${c['mo_ref'] ?? '-'}|${c['machine_id']}';
      if (key != lastKey) {
        final current = c['run_id'] != null && c['run_id'] == _run?['id'];
        widgets.add(Container(
          margin: const EdgeInsets.only(top: 12, bottom: 4),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          color: current ? Colors.deepPurple.shade100 : Colors.grey.shade200,
          child: Text(
              'MO ${c['mo_ref'] ?? '-'}  •  ${_machineName(c['machine_id'])}'
              '${current ? '  (current)' : ''}',
              style: const TextStyle(fontWeight: FontWeight.bold)),
        ));
        lastKey = key;
      }
      widgets.add(_checkTile(c));
    }
    return widgets;
  }

  Widget _checkTile(Map c) {
    String flag(dynamic v) => v == null ? '-' : (v == true ? 'OK' : 'FAIL');
    final status = c['overall_status'] as String?;
    final w = c['sample_weight'];
    final verdicts = c['verdicts'] as Map?;
    final weightRejected = (verdicts?['weight'] as Map?)?['rejected'] == true;
    final when = (c['measured_at'] ?? c['created_at'] ?? '')
        .toString()
        .replaceFirst('T', ' ')
        .split('.')
        .first;
    final notes = (c['notes'] ?? '').toString();
    return ListTile(
      dense: true,
      leading: Icon(
          status == 'FAIL'
              ? Icons.cancel
              : (status == 'PASS' ? Icons.check_circle : Icons.help_outline),
          color: status == 'FAIL'
              ? Colors.red
              : (status == 'PASS' ? Colors.green : Colors.grey)),
      title: Text('$when'
          '${w != null ? ' — ${w}g/${c['sample_rods'] ?? 10}' : ''}'
          '${weightRejected ? '  ⚠ dropped (3×tol)' : ''}'
          '${c['length_mm'] != null ? '  L:${c['length_mm']}' : ''}'
          '${c['hardness'] != null ? '  H:${c['hardness']}%' : ''}'),
      subtitle: Text('glue:${flag(c['glue_seam_ok'])} cut:${flag(c['cut_quality_ok'])} '
          'visual:${flag(c['visual_appearance_ok'])}${notes.isEmpty ? '' : '\n$notes'}'),
      trailing: IconButton(
          icon: const Icon(Icons.delete_outline),
          tooltip: 'Void',
          onPressed: () => _void(c)),
    );
  }

  Widget _triState(String label, bool? value, ValueChanged<bool?> onChanged) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Expanded(child: Text(label, style: const TextStyle(fontSize: 16))),
        SegmentedButton<int>(
          showSelectedIcon: false,
          emptySelectionAllowed: true,
          segments: const [
            ButtonSegment(value: 1, label: Text('OK')),
            ButtonSegment(value: 0, label: Text('FAIL')),
          ],
          selected: value == null ? <int>{} : {value ? 1 : 0},
          onSelectionChanged: (s) => onChanged(s.isEmpty ? null : s.first == 1),
        ),
      ]),
    );
  }
}
