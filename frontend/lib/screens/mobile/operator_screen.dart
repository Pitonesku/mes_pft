import 'package:flutter/material.dart';
import 'dart:convert';
import 'package:printing/printing.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:pdf/pdf.dart';
import '../../models.dart';
import '../../app_state.dart';
import '../auth_screen.dart';
import '../../api_service.dart';
import '../../local_db.dart';
import '../../widgets/dev_banner.dart';
import 'history_screen.dart';
import 'manual_quality_checks_screen.dart';
import 'pending_shifts_screen.dart';
import '../../shift_context.dart';
import 'package:intl/intl.dart';
import 'dart:async';
import 'dart:math';

/// Result of the "Change MO" dialog.
class _SwitchInput {
  final double? endCounter;
  final PurchaseOrder? po;
  _SwitchInput({this.endCounter, this.po});
}

class ReportPage extends StatefulWidget {
  final User operator;
  final Map<String, dynamic>? initialData;
  final int? localId;
  final String? initialStatus;

  const ReportPage({
    super.key,
    required this.operator,
    this.initialData,
    this.localId,
    this.initialStatus,
  });

  @override
  State<ReportPage> createState() => _ReportPageState();
}

class _ReportPageState extends State<ReportPage> {
  final _formKey = GlobalKey<FormState>();
  int? _currentDraftId;
  int? _editingSourceId;
  int? _originalServerReportId;
  String? _originalReportDate;
  String? _loadedReportStatus;

  bool _isModifyEnabled = false;
  bool _isSubmitting = false;
  bool _isSaving = false;
  String? _clientReportId;
  // Shift / run the report being edited belongs to. Null = "use the active shift's
  // current run" (a fresh report); a restored draft keeps the ids it was started with.
  int? _reportShiftId;
  int? _reportRunId;
  bool _adjustTime = false;
  DateTime? _manualShiftDate;

  Shift? _selectedShift;
  Machine? _selectedMachine;
  PurchaseOrder? _selectedPO;
  ShiftContext? _activeShift;

  // Field controllers
  final _startTimeCtrl = TextEditingController();
  final _endTimeCtrl = TextEditingController();
  final _lotController = TextEditingController();
  final _boxTypeController = TextEditingController();
  final _diameterController = TextEditingController();
  final _lengthController = TextEditingController();
  final _pdController = TextEditingController();
  final _weightController = TextEditingController();

  final _boxProducedController = TextEditingController();
  final _machineCounterController = TextEditingController();
  final _rodsProducedController = TextEditingController();
  final _differenceController = TextEditingController();
  final _diffPercentController = TextEditingController();
  final _wasteController = TextEditingController();
  final _efficiencyController = TextEditingController();
  final _remarksController = TextEditingController();

  // Списки материалов
  final List<MaterialItem> _acetate = [];
  final List<MaterialItem> _paper = [];
  final List<MaterialItem> _hmGlue = [];
  final List<MaterialItem> _pvaGlue = [];
  final List<MaterialItem> _triacetin = [];

  @override
  void dispose() {
    _startTimeCtrl.dispose();
    _endTimeCtrl.dispose();
    _lotController.dispose();
    _boxTypeController.dispose();
    _diameterController.dispose();
    _lengthController.dispose();
    _pdController.dispose();
    _weightController.dispose();
    _boxProducedController.dispose();
    _machineCounterController.dispose();
    _rodsProducedController.dispose();
    _differenceController.dispose();
    _diffPercentController.dispose();
    _wasteController.dispose();
    _efficiencyController.dispose();
    _remarksController.dispose();
    super.dispose();
  }

  bool get _isDataModified {
    if (_selectedPO == null) return false;
    return _diameterController.text != _selectedPO!.diameter.toString() ||
        _lengthController.text != _selectedPO!.length.toString() ||
        _pdController.text != _selectedPO!.pd.toString() ||
        _weightController.text != _selectedPO!.weight.toString() ||
        _boxTypeController.text != _selectedPO!.boxType.toString();
  }

  // --- ВАЛИДАТОРЫ ---
  String? _reqValidator(String? value) {
    if (value == null || value.trim().isEmpty) return 'Req';
    return null;
  }

  String? _validatePositiveInt(String? value) {
    if (value == null || value.trim().isEmpty) return 'Req';
    final intVal = int.tryParse(value);
    if (intVal == null || intVal <= 0) return 'Must be > 0';
    return null;
  }

  String? _validateDiameter(String? value) {
    if (value == null || value.trim().isEmpty) return 'Req';
    final normalized = value.replaceAll(',', '.');
    if (!RegExp(r'^\d{1}\.\d{2}$').hasMatch(normalized)) return 'Format: X.XX';
    return null;
  }

  String? _validateLengthWeight(String? value) {
    if (value == null || value.trim().isEmpty) return 'Req';
    final normalized = value.replaceAll(',', '.');
    if (!RegExp(r'^\d{2,3}\.\d{2}$').hasMatch(normalized)) {
      return 'Format: XX.XX';
    }
    return null;
  }

  @override
  void initState() {
    super.initState();
    _startTimeCtrl.text = "08:00";
    _endTimeCtrl.text = "20:00";
    _loadedReportStatus = widget.initialStatus;

    if (widget.initialData != null) {
      _loadDraftData(widget.initialData!, widget.localId);
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _ensureActiveShift();
      });
    }
  }

  Future<void> _ensureActiveShift() async {
    final ctx = await ApiService.loadShiftContext();
    if (!mounted) return;
    if (ctx == null) {
      setState(() => _activeShift = null);
      return;
    }

    // The saved context may point at a shift that was stopped/closed on another
    // device, or at a previous session. Re-validate it against the server so the
    // screen either shows the real active shift (with machine/shift/MO) or the
    // "Start Shift" view - never a blank form with no way to open a shift.
    final detail = await ApiService.fetchShiftDetail(ctx.shiftId);
    if (!mounted) return;

    if (detail == null) {
      if (ApiService.lastApiStatus == 404) {
        await ApiService.clearShiftContext();
        setState(() => _activeShift = null);
      } else {
        // Network/auth problem: keep the context, repopulate from the cache only.
        _applyShiftContext(ctx, null);
      }
      return;
    }

    if (detail['ended_at'] != null) {
      // Already closed / auto-closed elsewhere -> drop the stale context.
      await ApiService.clearShiftContext();
      setState(() => _activeShift = null);
      return;
    }

    _applyShiftContext(ctx, detail);
  }

  void _applyShiftContext(ShiftContext ctx, Map<String, dynamic>? detail) {
    final machineId = detail?['machine_id'] as int? ?? ctx.machineId;
    final shiftName = (detail?['shift_name'] as String?) ?? ctx.shiftName;
    final machine = _machineById(machineId) ?? _machineByName(ctx.machineName);
    final shift = _shiftByName(shiftName);
    final po = (detail != null ? _poByRun(detail['runs'] as List<dynamic>?) : null)
        ?? _poByNumber(ctx.moRef);

    setState(() {
      _activeShift = ctx;
      if (machine != null) _selectedMachine = machine;
      if (shift != null) {
        _selectedShift = shift;
        _startTimeCtrl.text = shift.start;
        _endTimeCtrl.text = shift.end;
      }
    });
    if (po != null) _onPOSelected(po);
  }

  Machine? _machineById(int? id) {
    if (id == null) return null;
    for (final m in AppData.machines) {
      if (m.id == id) return m;
    }
    return null;
  }

  Machine? _machineByName(String? name) {
    if (name == null) return null;
    for (final m in AppData.machines) {
      if (m.name == name) return m;
    }
    return null;
  }

  Shift? _shiftByName(String? name) {
    if (name == null) return null;
    for (final s in AppData.shifts) {
      if (s.name == name) return s;
    }
    return null;
  }

  PurchaseOrder? _poByNumber(String? poNumber) {
    if (poNumber == null) return null;
    for (final p in AppData.activePOs) {
      if (p.poNumber == poNumber) return p;
    }
    return null;
  }

  PurchaseOrder? _poById(int? id) {
    if (id == null) return null;
    for (final p in AppData.activePOs) {
      if (p.id == id) return p;
    }
    return null;
  }

  PurchaseOrder? _poByRun(List<dynamic>? runs) {
    if (runs == null) return null;
    Map<String, dynamic>? open;
    for (final r in runs) {
      final m = Map<String, dynamic>.from(r as Map);
      if (m['ended_at'] == null) open = m;
    }
    if (open == null) return null;
    return _poById(open['po_id'] as int?) ?? _poByNumber(open['mo_ref'] as String?);
  }

  Widget _buildInactiveShiftView() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.timer_off_outlined, size: 72, color: Colors.grey),
          const SizedBox(height: 16),
          const Text(
            'No Active Shift',
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          const Text(
            'Please start a shift to log production.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey, fontSize: 15),
          ),
          const SizedBox(height: 28),
          FilledButton.icon(
            onPressed: _promptStartShift,
            icon: const Icon(Icons.play_circle, size: 24),
            label: const Text('Start Shift', style: TextStyle(fontSize: 16)),
          ),
        ]),
      ),
    );
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _promptStartShift() async {
    final now = DateTime.now();
    final availableShifts = availableShiftsForTime(now, AppData.shifts);
    Shift? autoShift = resolveShiftForTime(now, AppData.shifts) ??
        (availableShifts.isNotEmpty ? availableShifts.first : null);

    Machine? selMachine;
    for (final m in AppData.machines) {
      if (!m.isInactive && m.id != null) {
        selMachine = m;
        break;
      }
    }
    PurchaseOrder? selPO;
    for (final p in AppData.activePOs) {
      if (!p.isHidden) {
        selPO = p;
        break;
      }
    }
    if (selMachine == null) {
      _toast('No machines available — check connection and sync data.');
      return;
    }

    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: const Text('Start Shift'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              DropdownButtonFormField<Machine>(
                initialValue: selMachine,
                decoration: const InputDecoration(labelText: 'Machine'),
                items: AppData.machines
                    .where((m) => !m.isInactive && m.id != null)
                    .map((m) => DropdownMenuItem(value: m, child: Text(m.name)))
                    .toList(),
                onChanged: (v) => setDlg(() => selMachine = v),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<Shift>(
                initialValue: autoShift,
                decoration: const InputDecoration(labelText: 'Shift'),
                items: availableShifts
                    .map((s) => DropdownMenuItem(
                        value: s, child: Text('${s.name} (${s.start}-${s.end})')))
                    .toList(),
                onChanged: (v) => setDlg(() => autoShift = v),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<PurchaseOrder>(
                initialValue: selPO,
                decoration: const InputDecoration(labelText: 'Manufacturing Order'),
                items: AppData.activePOs
                    .where((p) => !p.isHidden)
                    .map((p) => DropdownMenuItem(value: p, child: Text(p.poNumber)))
                    .toList(),
                onChanged: (v) => setDlg(() => selPO = v),
              ),
            ]),
          ),
          actions: [
            FilledButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Start Shift')),
          ],
        ),
      ),
    );

    if (confirmed != true || selMachine == null) return;
    await _doStartShift(selMachine!, autoShift, selPO);
  }

  Future<void> _doStartShift(
      Machine machine, Shift? shift, PurchaseOrder? po) async {
    if (machine.id == null) {
      _toast('Machine not synced — please reconnect and retry.');
      return;
    }
    bool takeover = false;
    if (machine.id != null) {
      final active = await ApiService.fetchShiftSessions(
          machineId: machine.id, status: 'active');
      if (!mounted) return;
      if (active != null && active.isNotEmpty) {
        final take = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Text('Machine already has an open shift'),
            content: const Text(
                'Another operator has an active shift on this machine. Take over? Their shift will be auto-closed (data kept) so you can start fresh.'),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text('Cancel')),
              FilledButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  child: const Text('Take Over')),
            ],
          ),
        );
        if (take != true) return;
        takeover = true;
      }
    }

    final scheduledEnd =
        shift != null ? scheduledEndForShift(DateTime.now(), shift) : null;
    final r = await ApiService.startShift(
      machineId: machine.id!,
      poId: po?.id,
      shiftName: shift?.name,
      scheduledEndAt: scheduledEnd,
      takeover: takeover,
    );
    if (r == null) {
      _toast('Failed to start shift: ${ApiService.lastApiDetail}');
      return;
    }
    final shiftId = r['id'] as int? ?? 0;
    final run = r['run'] as Map?;
    final runId = run?['id'] as int?;
    final ctx = ShiftContext(
      shiftId: shiftId,
      machineId: machine.id,
      machineName: machine.name,
      runId: runId,
      moRef: po?.poNumber ?? (run?['mo_ref'] as String?),
      shiftName: shift?.name ?? (r['shift_name'] as String?),
      startedAt: DateTime.tryParse(r['started_at']?.toString() ?? ''),
      scheduledEndAt: scheduledEnd,
    );
    await ApiService.saveShiftContext(ctx);
    if (!mounted) return;
    setState(() {
      _activeShift = ctx;
      _selectedMachine = machine;
      if (shift != null) {
        _selectedShift = shift;
        _startTimeCtrl.text = shift.start;
        _endTimeCtrl.text = shift.end;
      }
    });
    if (po != null) _onPOSelected(po);
    // A new shift is a brand-new report: reset the idempotency key and clear the
    // production-log fields so the previous report's values (boxes, counter, ...)
    // never leak into this one. Without this, resubmitting after a shift close
    // reuses the old client_report_id and the server silently rejects it as a
    // duplicate while the UI still shows "Sent to server!".
    _startNewReportIdentity();
    _resetProductionLog();
    _toast('Shift started');
    await _checkForMatchingDraft(ctx);
  }

  Future<void> _changeMo() async {
    final ctx = _activeShift;
    if (ctx == null) {
      _toast('No active shift');
      return;
    }

    PurchaseOrder? selPO;
    for (final p in AppData.activePOs) {
      if (!p.isHidden && p.poNumber != ctx.moRef) {
        selPO = p;
        break;
      }
    }
    final counterCtrl = TextEditingController(text: _machineCounterController.text.trim());
    final input = await showDialog<_SwitchInput>(
      context: context,
      builder: (dctx) => StatefulBuilder(
        builder: (dctx, setDlg) => AlertDialog(
          title: const Text('Change MO / Order'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text('Now: ${ctx.moRef ?? '-'} on ${ctx.machineName ?? '-'}',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              const Text(
                  'What you entered for the current MO is saved as a draft report first '
                  '(one report per MO). The new MO starts with an empty report.',
                  style: TextStyle(fontSize: 12, color: Colors.grey)),
              const SizedBox(height: 12),
              DropdownButtonFormField<PurchaseOrder>(
                initialValue: selPO,
                decoration: const InputDecoration(labelText: 'New Manufacturing Order'),
                items: AppData.activePOs
                    .where((p) => !p.isHidden && p.poNumber != ctx.moRef)
                    .map((p) => DropdownMenuItem(value: p, child: Text(p.poNumber)))
                    .toList(),
                onChanged: (v) => setDlg(() => selPO = v),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: counterCtrl,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: InputDecoration(
                    labelText: 'Final machine counter of ${ctx.moRef ?? 'current MO'}'),
              ),
            ]),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dctx), child: const Text('Cancel')),
            FilledButton(
                onPressed: selPO == null
                    ? null
                    : () => Navigator.pop(
                        dctx,
                        _SwitchInput(
                          po: selPO,
                          endCounter: double.tryParse(
                              counterCtrl.text.trim().replaceAll(',', '.')),
                        )),
                child: const Text('Switch')),
          ],
        ),
      ),
    );
    counterCtrl.dispose();
    final chosen = input?.po;
    if (input == null || chosen == null) return;

    await _saveDraftIfHasData();
    final r = await ApiService.switchMo(ctx.shiftId,
        poId: chosen.id, endCounter: input.endCounter);
    if (r == null) {
      if (ApiService.lastApiStatus == 409) {
        await ApiService.clearShiftContext();
        if (!mounted) return;
        setState(() => _activeShift = null);
        _toast('This shift is no longer active — start a new shift.');
      } else {
        _toast('Failed to switch MO: ${ApiService.lastApiDetail ?? ''}');
      }
      return;
    }
    final newRunId = r['id'] as int?;
    final newMoRef = r['mo_ref'] as String? ?? chosen.poNumber;
    final newCtx = ctx.copyWith(runId: newRunId, moRef: newMoRef);
    await ApiService.saveShiftContext(newCtx);
    if (!mounted) return;
    setState(() => _activeShift = newCtx);
    _startNewReportIdentity();
    _onPOSelected(chosen);
    _resetProductionLog();
    _toast('Switched to ${chosen.poNumber}');
  }

  /// A report belongs to exactly one MO run: after an MO / machine change the next
  /// report is a brand-new one (new idempotency key, new draft, new run link).
  void _startNewReportIdentity() {
    _currentDraftId = null;
    _clientReportId = null;
    _editingSourceId = null;
    _originalServerReportId = null;
    _originalReportDate = null;
    _reportShiftId = null;
    _reportRunId = null;
  }

  bool _hasProductionData() =>
      _boxProducedController.text.trim().isNotEmpty ||
      _machineCounterController.text.trim().isNotEmpty ||
      _rodsProducedController.text.trim().isNotEmpty ||
      _wasteController.text.trim().isNotEmpty;

  Future<void> _saveDraftIfHasData() async {
    if (_hasProductionData()) await _saveAsDraft();
  }

  void _resetProductionLog() {
    _boxProducedController.clear();
    _machineCounterController.clear();
    _rodsProducedController.clear();
    _differenceController.clear();
    _diffPercentController.clear();
    _wasteController.clear();
    _efficiencyController.clear();
    _calculateProductionLog();
  }

  Future<bool> _promptSmartShiftClose() async {
    final ctx = _activeShift;
    if (ctx == null) return false;
    final scheduledEnd = ctx.scheduledEndAt;
    final nearEnd = scheduledEnd != null &&
        scheduledEnd.difference(DateTime.now()).inMinutes < 20;

    if (nearEnd) {
      final close = await showDialog<bool>(
        context: context,
        builder: (dctx) => AlertDialog(
          title: const Text('End of Shift'),
          content: const Text(
              'Your shift is ending. Close the shift and log out after submitting?'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dctx, false),
                child: const Text('Keep Shift Open')),
            FilledButton(
                onPressed: () => Navigator.pop(dctx, true),
                child: const Text('Close Shift & Log Out')),
          ],
        ),
      );
      return close ?? true; // default to close
    }

    final close = await showDialog<bool>(
      context: context,
      builder: (dctx) => AlertDialog(
        title: const Text('Submit Report'),
        content: const Text(
            'Submit the report and close the shift, or keep the shift open for more production?'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dctx, false),
              child: const Text('Submit Report Only')),
          FilledButton(
              onPressed: () => Navigator.pop(dctx, true),
              child: const Text('Submit & Close Shift')),
        ],
      ),
    );
    return close ?? false;
  }

  Future<void> _closeActiveShift() async {
    final ctx = _activeShift;
    if (ctx == null) return;
    final logs = _buildShiftCloseLogs();
    await ApiService.completeShift(
      ctx.shiftId,
      materialLogs: logs['material_logs']!,
      scrapLogs: logs['scrap_logs']!,
    );
    await ApiService.clearShiftContext();
    if (!mounted) return;
    setState(() => _activeShift = null); // return to the "No Active Shift" state
  }

  Future<void> _endShift() async {
    final ctx = _activeShift;
    if (ctx == null) {
      _toast('No active shift');
      return;
    }
    final choice = await showDialog<String>(
      context: context,
      builder: (dctx) => AlertDialog(
        title: const Text('Stop Shift'),
        content: const Text(
            'Choose how to finish this shift. Unsaved production data can be kept '
            'as a draft, submitted, or discarded.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dctx, 'cancel'),
              child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(dctx, 'discard'),
              child: const Text('Stop Without Saving')),
          TextButton(
              onPressed: () => Navigator.pop(dctx, 'draft'),
              child: const Text('Save Draft & Stop Shift')),
          FilledButton(
              onPressed: () => Navigator.pop(dctx, 'submit'),
              child: const Text('Submit Report & Finish')),
        ],
      ),
    );
    if (choice == null || choice == 'cancel') return;
    if (choice == 'submit') {
      await _submitReport(closeShiftOverride: true);
      return;
    }
    if (choice == 'discard') {
      await _stopShift(saveDraft: false);
      return;
    }
    await _stopShift();
  }

  Future<void> _stopShift({bool saveDraft = true}) async {
    final ctx = _activeShift;
    if (ctx == null) return;
    if (saveDraft) {
      await _saveAsDraft();
    }
    final ok = await ApiService.stopShift(ctx.shiftId);
    if (!ok) {
      if (ApiService.lastApiStatus == 409) {
        // Stale context: the shift is already ended on the server.
        await ApiService.clearShiftContext();
        if (!mounted) return;
        setState(() => _activeShift = null);
        _toast('This shift is no longer active — start a new shift.');
      } else {
        _toast('Failed to stop shift');
      }
      return;
    }
    await ApiService.clearShiftContext();
    if (!mounted) return;
    setState(() => _activeShift = null);
  }

  Future<void> _checkForMatchingDraft(ShiftContext ctx) async {
    final matching = await _findMatchingDrafts(
        ctx.machineName, ctx.shiftName, _getShiftDateString(), ctx.moRef);
    if (matching.isEmpty || !mounted) return;
    final draftMo = (matching.first['data'] as Map<String, dynamic>)['po_number'];
    final restore = await showDialog<bool>(
      context: context,
      builder: (dctx) => AlertDialog(
        title: const Text('Unsaved Draft Found'),
        content: Text(
            'Found unsaved draft for MO ${draftMo ?? '-'} (this shift). Restore previous data?'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dctx, false),
              child: const Text('Start Fresh')),
          FilledButton(
              onPressed: () => Navigator.pop(dctx, true),
              child: const Text('Restore')),
        ],
      ),
    );
    if (restore == true && mounted) {
      _loadDraftData(matching.first['data'] as Map<String, dynamic>,
          matching.first['id'] as int?);
    }
  }

  Future<List<Map<String, dynamic>>> _findMatchingDrafts(
      String? machineName, String? shiftName, String shiftDate, String? mo) async {
    final drafts = await LocalDB.instance.getReportsByStatus('draft');
    final matching = <Map<String, dynamic>>[];
    for (final d in drafts) {
      final data = jsonDecode(d['report_data']) as Map<String, dynamic>;
      final date = (data['shift_date'] ?? data['report_date']) as String?;
      if (data['machine_name'] == machineName &&
          data['shift_name'] == shiftName &&
          date == shiftDate &&
          data['po_number'] == mo) {
        matching.add({'id': d['id'], 'data': data});
      }
    }
    return matching;
  }

  Map<String, List<Map<String, dynamic>>> _buildShiftCloseLogs() {
    final materialLogs = <Map<String, dynamic>>[];
    void add(List<MaterialItem> items, String category) {
      for (final it in items) {
        final batch = it.batch.text.trim();
        final used = it.used;
        if (used > 0 || batch.isNotEmpty) {
          materialLogs.add({
            'category': category,
            'batch_no': batch.isEmpty ? null : batch,
            'qty_kg': used,
            'source': 'manual',
          });
        }
      }
    }

    add(_acetate, 'acetate');
    add(_paper, 'paper');
    add(_pvaGlue, 'glue');
    add(_hmGlue, 'glue');
    add(_triacetin, 'triacetin');

    final scrapLogs = <Map<String, dynamic>>[];
    final waste =
        double.tryParse(_wasteController.text.trim().replaceAll(',', '.')) ?? 0.0;
    if (waste > 0) {
      scrapLogs.add({'reason_code': 'UNSPECIFIED', 'qty_kg': waste});
    }
    return {'material_logs': materialLogs, 'scrap_logs': scrapLogs};
  }

  void _loadDraftData(Map<String, dynamic> d, int? id) {
    setState(() {
      if (_loadedReportStatus == 'draft' || _loadedReportStatus == null) {
        _currentDraftId = id;
      } else {
        _editingSourceId = id;
      }
      _originalServerReportId =
          (d['server_report_id'] as int?) ?? d['report_id'] as int?;
      _reportShiftId = d['shift_id'] as int?;
      _reportRunId = d['run_id'] as int?;
      _originalReportDate = d['report_date'] as String?;
      _startTimeCtrl.text = d['start_time'] ?? "08:00";
      _endTimeCtrl.text = d['end_time'] ?? "20:00";
      _lotController.text = d['lot_number'] ?? "";
      _boxTypeController.text = d['box_type'] ?? "";
      _diameterController.text = d['diameter'] ?? "";
      _lengthController.text = d['length'] ?? "";
      _pdController.text = d['pd'] ?? "";
      _weightController.text = d['weight'] ?? "";
      _boxProducedController.text = d['boxes_produced'] ?? "";
      _machineCounterController.text = d['machine_counter'] ?? "";
      _rodsProducedController.text = d['produced_rods']?.toString() ?? "";
      _differenceController.text = d['difference']?.toString() ?? "";
      _diffPercentController.text = d['diff_percent']?.toString().replaceAll('%', '') ?? "";
      _wasteController.text = d['waste_kg'] ?? "";
      _efficiencyController.text = d['efficiency'] ?? "";
      _remarksController.text = d['remarks'] ?? "";
      _isModifyEnabled = d['is_modified'] ?? false;
      // Reuse the idempotency key for unfinished drafts, but generate a new one
      // when editing an already-submitted report (a new record is being created).
      _clientReportId = (_loadedReportStatus == 'draft' || _loadedReportStatus == null)
          ? d['client_report_id'] as String?
          : null;

      try {
        if (d['shift_name'] != null) {
          _selectedShift = AppData.shifts.firstWhere(
            (s) => s.name == d['shift_name'],
          );
        }
        if (d['machine_name'] != null) {
          _selectedMachine = AppData.machines.firstWhere(
            (m) => m.name == d['machine_name'],
          );
        }
        if (d['po_number'] != null) {
          _selectedPO = AppData.activePOs.firstWhere(
            (p) => p.poNumber == d['po_number'],
          );
        }
      } catch (e) {
        debugPrint("Error: $e");
      }

      if (d['acetate_list'] != null) {
        _acetate.clear();
        _acetate.addAll(
          (d['acetate_list'] as List)
              .map((i) => MaterialItem.fromJson(i as Map<String, dynamic>))
              .toList(),
        );
      }
      if (d['paper_list'] != null) {
        _paper.clear();
        _paper.addAll(
          (d['paper_list'] as List)
              .map((i) => MaterialItem.fromJson(i as Map<String, dynamic>))
              .toList(),
        );
      }
      if (d['pva_list'] != null) {
        _pvaGlue.clear();
        _pvaGlue.addAll(
          (d['pva_list'] as List)
              .map((i) => MaterialItem.fromJson(i as Map<String, dynamic>))
              .toList(),
        );
      }
      if (d['hm_list'] != null) {
        _hmGlue.clear();
        _hmGlue.addAll(
          (d['hm_list'] as List)
              .map((i) => MaterialItem.fromJson(i as Map<String, dynamic>))
              .toList(),
        );
      }
      if (d['tri_list'] != null) {
        _triacetin.clear();
        _triacetin.addAll(
          (d['tri_list'] as List)
              .map((i) => MaterialItem.fromJson(i as Map<String, dynamic>))
              .toList(),
        );
      }

      _calculateProductionLog();
    });
  }

  void _onPOSelected(PurchaseOrder? po) {
    if (po == null) return;
    setState(() {
      _selectedPO = po;
      _isModifyEnabled = false;
      _boxTypeController.text = po.boxType.toString();
      _diameterController.text = po.diameter.toString();
      _lengthController.text = po.length.toString();
      _pdController.text = po.pd.toString();
      _weightController.text = po.weight.toString();

      _acetate.clear();
      _acetate.add(MaterialItem(defaultType: po.acetateType));
      _paper.clear();
      _paper.add(MaterialItem(defaultType: po.paperType));
      _hmGlue.clear();
      _hmGlue.add(MaterialItem(defaultType: po.hmGlueType));
      _pvaGlue.clear();
      _pvaGlue.add(MaterialItem(defaultType: po.pvaGlueType));
      _triacetin.clear();
      _triacetin.add(MaterialItem(defaultType: po.triacetinType));

      _calculateProductionLog();
    });
  }

  void _confirmModify(bool? newValue) async {
    if (newValue == true) {
      bool confirm =
          await showDialog(
            context: context,
            builder: (ctx) => AlertDialog(
              title: const Text("Attention"),
              content: const Text(
                "Are you sure you want to modify the PO data manually?",
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text("NO"),
                ),
                TextButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  child: const Text("YES"),
                ),
              ],
            ),
          ) ??
          false;
      if (confirm) setState(() => _isModifyEnabled = true);
    } else {
      setState(() => _isModifyEnabled = false);
    }
  }

  void _calculateProductionLog() {
    int boxType = int.tryParse(_boxTypeController.text) ?? 0;
    int boxes = int.tryParse(_boxProducedController.text) ?? 0;
    int counter = int.tryParse(_machineCounterController.text) ?? 0;
    int rods = boxes * boxType;
    int diff = counter - rods;
    double diffPct = counter > 0 ? (diff / counter) * 100 : 0.0;

    setState(() {
      _rodsProducedController.text = rods.toString();
      _differenceController.text = diff.toString();
      _diffPercentController.text = diffPct.toStringAsFixed(2);
    });
  }

  DateTime? _parseTimeToDate(String value) {
    final normalized = value.trim();
    if (normalized.isEmpty) return null;
    final parts = normalized.split(':');
    if (parts.length != 2) return null;
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    if (hour == null || minute == null) return null;
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
    final now = DateTime.now();
    return DateTime(now.year, now.month, now.day, hour, minute);
  }

  bool _crossesMidnight(DateTime start, DateTime end) {
    return end.isBefore(start);
  }

  String _getShiftDateString() {
    if (_originalReportDate != null && _originalReportDate!.isNotEmpty) {
      return _originalReportDate!;
    }

    if (_manualShiftDate != null) {
      return DateFormat('yyyy-MM-dd').format(_manualShiftDate!);
    }

    final startValue = _startTimeCtrl.text.isNotEmpty
        ? _startTimeCtrl.text
        : _selectedShift?.start ?? '';
    final endValue = _endTimeCtrl.text.isNotEmpty
        ? _endTimeCtrl.text
        : _selectedShift?.end ?? '';

    final startDate = _parseTimeToDate(startValue) ??
        _parseTimeToDate(_selectedShift?.start ?? '') ??
        DateTime.now();
    final endDate = _parseTimeToDate(endValue) ??
        _parseTimeToDate(_selectedShift?.end ?? '') ??
        DateTime.now();

    DateTime shiftDate = DateTime.now();
    if (_crossesMidnight(startDate, endDate)) {
      final now = DateTime.now();
      final todayEnd = DateTime(now.year, now.month, now.day, endDate.hour,
          endDate.minute);
      if (now.isBefore(todayEnd)) {
        shiftDate = now.subtract(const Duration(days: 1));
      }
    }

    return DateFormat('yyyy-MM-dd').format(shiftDate);
  }

  String _getShiftDateDisplay() {
    try {
      final parsed = DateTime.parse(_getShiftDateString());
      return DateFormat('dd.MM.yyyy').format(parsed);
    } catch (_) {
      return _getShiftDateString();
    }
  }

  double _calculateTotal(List<MaterialItem> items) {
    return items.fold(0.0, (sum, item) => sum + item.used);
  }

  // --- МЕТОД СОХРАНЕНИЯ ЧЕРНОВИКА ---
  Future<void> _saveAsDraft() async {
    if (_isSaving) return;
    setState(() => _isSaving = true);
    final reportData = {
      'client_report_id': _clientReportId ??= _generateClientReportId(),
      'shift_id': _reportShiftId ?? _activeShift?.shiftId,
      'run_id': _reportRunId ?? _activeShift?.runId,
      'operator_name': widget.operator.name,
      'report_date': _getShiftDateString(),
      'shift_date': _getShiftDateString(),
      'shift_name': _selectedShift?.name,
      'start_time': _startTimeCtrl.text,
      'end_time': _endTimeCtrl.text,
      'machine_name': _selectedMachine?.name,
      'po_number': _selectedPO?.poNumber,
      'lot_number': _lotController.text,
      'box_type': _boxTypeController.text,
      'diameter': _diameterController.text,
      'length': _lengthController.text,
      'pd': _pdController.text,
      'weight': _weightController.text,
      'boxes_produced': _boxProducedController.text,
      'machine_counter': _machineCounterController.text,
      'produced_rods': _rodsProducedController.text,
      'difference': _differenceController.text,
      'diff_percent': '${_diffPercentController.text}%',
      'waste_kg': _wasteController.text,
      'efficiency': _efficiencyController.text,
      'remarks': _remarksController.text,
      'acetate_list': _acetate.map((m) => m.toJson()).toList(),
      'paper_list': _paper.map((m) => m.toJson()).toList(),
      'pva_list': _pvaGlue.map((m) => m.toJson()).toList(),
      'hm_list': _hmGlue.map((m) => m.toJson()).toList(),
      'tri_list': _triacetin.map((m) => m.toJson()).toList(),
      'total_acetate': _calculateTotal(_acetate),
      'total_paper': _calculateTotal(_paper),
      'total_pva': _calculateTotal(_pvaGlue),
      'total_hm': _calculateTotal(_hmGlue),
      'total_triacetin': _calculateTotal(_triacetin),
      'parent_local_report_id': _editingSourceId,
      'edited_by': _editingSourceId != null ? widget.operator.name : null,
      'edited_at': _editingSourceId != null
          ? DateTime.now().toIso8601String()
          : null,
      'server_report_id': _originalServerReportId,
      'status': _editingSourceId != null ? 'edited' : null,
      'is_modified': _isModifyEnabled,
    };

    try {
      _currentDraftId = await LocalDB.instance.saveReport(
        'draft',
        reportData,
        existingId: _currentDraftId,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("✅ Draft saved successfully!"),
            backgroundColor: Colors.blue,
          ),
        );
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text("❌ Error saving draft: $e"),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) setState(() => _isSaving = false);
    }
  }

  String _generateClientReportId() {
    final rand = Random();
    final now = DateTime.now().microsecondsSinceEpoch;
    final suffix = List.generate(8, (_) => rand.nextInt(36).toRadixString(36)).join();
    return '$now-$suffix';
  }

  Map<String, dynamic> _buildReportPayload() {
    String date = _getShiftDateString();
    String timeRange = _adjustTime
        ? "${_startTimeCtrl.text} - ${_endTimeCtrl.text}"
        : "${_selectedShift?.start ?? '00:00'} - ${_selectedShift?.end ?? '00:00'}";

    return {
      "client_report_id": _clientReportId ??= _generateClientReportId(),
      // One report per MO run: link it to the shift / run it was produced on. The
      // server re-validates these against the report's MO number.
      "shift_id": _reportShiftId ?? _activeShift?.shiftId,
      "run_id": _reportRunId ?? _activeShift?.runId,
      "report_date": date,
      "shift_date": date,
      "shift_name": _selectedShift?.name ?? "Unknown",
      "start_time": _startTimeCtrl.text,
      "end_time": _endTimeCtrl.text,
      "shift_time_range": timeRange,
      "machine_name": _selectedMachine?.name ?? "Unknown",
      "operator_name": widget.operator.name,
      "po_number": _selectedPO?.poNumber ?? "Unknown",
      "lot_number": _lotController.text,
      "box_type": int.tryParse(_boxTypeController.text) ?? 0,
      "diameter": double.tryParse(_diameterController.text) ?? 0.0,
      "length": double.tryParse(_lengthController.text) ?? 0.0,
      "pd": double.tryParse(_pdController.text)?.toInt() ?? 0,
      "weight": double.tryParse(_weightController.text) ?? 0.0,
      "boxes_produced": int.tryParse(_boxProducedController.text) ?? 0,
      "machine_counter": int.tryParse(_machineCounterController.text) ?? 0,
      "produced_rods": int.tryParse(_rodsProducedController.text) ?? 0,
      "waste_kg": double.tryParse(_wasteController.text) ?? 0.0,
      "machine_efficiency": double.tryParse(_efficiencyController.text) ?? 0.0,
      "difference": double.tryParse(_differenceController.text) ?? 0.0,
      "diff_percent": "${_diffPercentController.text}%",
      "efficiency_box_min": 0.0,
      "total_acetate": _calculateTotal(_acetate),
      "total_paper": _calculateTotal(_paper),
      "total_pva": _calculateTotal(_pvaGlue),
      "total_hm": _calculateTotal(_hmGlue),
      "total_triacetin": _calculateTotal(_triacetin),
      "remarks": _remarksController.text,
      "is_modified_manually": _isDataModified,
      "parent_report_id": _originalServerReportId,
      "parent_local_report_id": _editingSourceId,
      "edited_by": _editingSourceId != null ? widget.operator.name : null,
      "edited_at": _editingSourceId != null
          ? DateTime.now().toIso8601String()
          : null,
      "server_report_id": _originalServerReportId,
      "status": _editingSourceId != null ? 'edited' : null,
      "acetate_list": _acetate.map((m) => m.toJson()).toList(),
      "paper_list": _paper.map((m) => m.toJson()).toList(),
      "pva_list": _pvaGlue.map((m) => m.toJson()).toList(),
      "hm_list": _hmGlue.map((m) => m.toJson()).toList(),
      "tri_list": _triacetin.map((m) => m.toJson()).toList(),
    };
  }

  Future<void> _printReportPdf(Map<String, dynamic> data) async {
    final pdf = pw.Document();

    pdf.addPage(
      pw.MultiPage(
        pageFormat: PdfPageFormat.a4,
        build: (context) {
          List<pw.Widget> rows = [];
          void addRow(String label, String value) {
            rows.add(
              pw.Row(
                mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
                children: [
                  pw.Expanded(
                    child: pw.Text(
                      label,
                      style: pw.TextStyle(
                        fontWeight: pw.FontWeight.bold,
                        fontSize: 10,
                      ),
                    ),
                  ),
                  pw.Text(value, style: pw.TextStyle(fontSize: 10)),
                ],
              ),
            );
            rows.add(pw.SizedBox(height: 4));
          }

          void addSection(String title) {
            rows.add(pw.SizedBox(height: 12));
            rows.add(
              pw.Text(
                title,
                style: pw.TextStyle(
                  fontSize: 12,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
            );
            rows.add(pw.Divider());
          }

          addSection('General Info');
          addRow('Operator', data['operator_name'] ?? 'Unknown');
          addRow(
            'Shift Date',
            data['shift_date'] ?? data['report_date'] ?? '',
          );
          addRow(
            'Shift',
            '${data['shift_name']} (${data['shift_time_range'] ?? ''})',
          );
          addRow('Machine', data['machine_name'] ?? 'Unknown');
          addRow('MO Number', data['po_number'] ?? 'Unknown');
          addRow('Lot Number', data['lot_number'] ?? '');

          addSection('PO Specifications');
          addRow('Box Type', data['box_type'].toString());
          addRow(
            'Diameter / Length',
            '${data['diameter']} / ${data['length']}',
          );
          addRow('PD / Weight', '${data['pd']} / ${data['weight']}');

          addSection('Production Log');
          addRow('Boxes Produced', data['boxes_produced'].toString());
          addRow('Produced Rods', data['produced_rods'].toString());
          addRow('Machine Counter', data['machine_counter'].toString());
          addRow(
            'Difference',
            '${data['difference']} (${data['diff_percent']})',
          );
          addRow('Waste (kg)', data['waste_kg'].toString());
          addRow('Efficiency (%)', data['machine_efficiency'].toString());

          addSection('Total Materials');
          addRow('Acetate', data['total_acetate']?.toString() ?? '0.0');
          addRow('Paper', data['total_paper']?.toString() ?? '0.0');
          addRow('PVA (Cold Glue)', data['total_pva']?.toString() ?? '0.0');
          addRow('Hot Melt Glue', data['total_hm']?.toString() ?? '0.0');
          addRow('Triacetin', data['total_triacetin']?.toString() ?? '0.0');

          void addMaterials(String title, List<dynamic>? items) {
            if (items == null || items.isEmpty) return;
            addSection(title);

            double toDouble(dynamic v) {
              if (v == null) return 0.0;
              if (v is num) return v.toDouble();
              return double.tryParse(v.toString()) ?? 0.0;
            }

            double categoryTotal = 0.0;

            final List<List<String>> table = [];
            table.add([
              'Material Type',
              'Batch',
              'Start',
              'Stop',
              'Used',
            ]);

            for (final it in items) {
              final type = (it['type']?.toString() ?? 'Unknown').trim();
              final batch = (it['batch']?.toString().isNotEmpty == true)
                  ? it['batch'].toString()
                  : 'No Batch';
              final String start = it['start']?.toString().trim().isNotEmpty == true
                  ? it['start'].toString()
                  : '-';
              final String stop = it['stop']?.toString().trim().isNotEmpty == true
                  ? it['stop'].toString()
                  : '-';
              final used = it.containsKey('used') && it['used'] != null
                  ? toDouble(it['used'])
                  : (toDouble(it['start']) - toDouble(it['stop']));

              categoryTotal += used;

              table.add([
                type,
                batch,
                start,
                stop,
                used.toStringAsFixed(2),
              ]);
            }

            table.add([
              'Total',
              '',
              '',
              '',
              categoryTotal.toStringAsFixed(2),
            ]);

            rows.add(
              pw.Table.fromTextArray(
                headers: table.first,
                data: table.sublist(1),
                headerStyle: pw.TextStyle(
                  fontWeight: pw.FontWeight.bold,
                  fontSize: 9,
                ),
                cellStyle: pw.TextStyle(fontSize: 9),
                cellAlignment: pw.Alignment.centerLeft,
                headerDecoration: const pw.BoxDecoration(
                  color: PdfColors.grey300,
                ),
              ),
            );
            rows.add(pw.SizedBox(height: 6));
          }

          addMaterials('Acetate (Tow)', data['acetate_list'] as List<dynamic>?);
          addMaterials('Paper', data['paper_list'] as List<dynamic>?);
          addMaterials('PVA (Cold Glue)', data['pva_list'] as List<dynamic>?);
          addMaterials('Hot Melt Glue', data['hm_list'] as List<dynamic>?);
          addMaterials('Triacetin', data['tri_list'] as List<dynamic>?);

          addSection('Remarks');
          rows.add(
            pw.Text(
              data['remarks']?.toString().isNotEmpty == true
                  ? data['remarks']
                  : 'No remarks.',
              style: pw.TextStyle(fontSize: 10),
            ),
          );

          if (data['edited_by'] != null) {
            addSection('Edit Metadata');
            addRow('Edited By', data['edited_by'] ?? '');
            addRow('Edited At', data['edited_at'] ?? '');
          }

          return [pw.Header(level: 0, text: 'Production Report'), ...rows];
        },
      ),
    );

    await Printing.layoutPdf(onLayout: (format) => pdf.save());
  }

  // --- МЕТОД ПРЕДВАРИТЕЛЬНОГО ПРОСМОТРА И ОТПРАВКИ ---
  Future<void> _showPreviewAndSubmit() async {
    if (_isSubmitting || _isSaving) return;
    if (!_formKey.currentState!.validate()) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Please fill all required fields correctly!"),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    bool confirm =
        await showDialog(
          context: context,
          builder: (ctx) => Dialog(
            insetPadding: const EdgeInsets.all(16),
            child: Container(
              padding: const EdgeInsets.all(16),
              width: double.infinity,
              child: Column(
                children: [
                  const Text(
                    "REPORT PREVIEW",
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: Colors.deepPurple,
                    ),
                  ),
                  const Text(
                    "Review before printing/submission",
                    style: TextStyle(fontSize: 12, color: Colors.grey),
                  ),
                  const Divider(),
                  Expanded(
                    child: SingleChildScrollView(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          _previewSectionTitle("1. General Info"),
                          _previewRow("Operator", widget.operator.name),
                          _previewRow("Shift Date", _getShiftDateDisplay()),
                          _previewRow(
                            "Shift",
                            "${_selectedShift?.name ?? ''} (${_startTimeCtrl.text} - ${_endTimeCtrl.text})",
                          ),
                          _previewRow("Machine", _selectedMachine?.name ?? ''),
                          _previewRow("MO Number", _selectedPO?.poNumber ?? ''),
                          _previewRow("Lot Number", _lotController.text),

                          _previewSectionTitle("2. PO Specifications"),
                          _previewRow("Box Type", _boxTypeController.text),
                          _previewRow(
                            "Diameter / Length",
                            "${_diameterController.text} / ${_lengthController.text}",
                          ),
                          _previewRow(
                            "PD / Weight",
                            "${_pdController.text} / ${_weightController.text}",
                          ),

                          _previewSectionTitle("3. Production Log"),
                          _previewRow(
                            "Boxes Produced",
                            _boxProducedController.text,
                          ),
                          _previewRow(
                            "Produced Rods",
                            _rodsProducedController.text,
                          ),
                          _previewRow(
                            "Machine Counter",
                            _machineCounterController.text,
                          ),
                          _previewRow(
                            "Difference",
                            "${_differenceController.text} (${_diffPercentController.text}%)",
                          ),
                          _previewRow("Waste (kg)", _wasteController.text),
                          _previewRow(
                            "Efficiency (%)",
                            _efficiencyController.text,
                          ),

                          _previewSectionTitle("4. Materials Used"),
                          _buildPreviewMaterialList("Acetate (Tow)", _acetate),
                          _buildPreviewMaterialList("Paper", _paper),
                          _buildPreviewMaterialList(
                            "PVA (Cold Glue)",
                            _pvaGlue,
                          ),
                          _buildPreviewMaterialList("Hot Melt Glue", _hmGlue),
                          _buildPreviewMaterialList("Triacetin", _triacetin),

                          _previewSectionTitle("5. Remarks"),
                          Text(
                            _remarksController.text.isEmpty
                                ? "No remarks."
                                : _remarksController.text,
                            style: const TextStyle(fontStyle: FontStyle.italic),
                          ),
                      ],
                    ),
                  ),
                ),
                   const Divider(),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      TextButton(
                        onPressed: () => Navigator.pop(ctx, false),
                        child: const Text(
                          "EDIT",
                          style: TextStyle(color: Colors.grey),
                        ),
                      ),
                      const SizedBox(width: 12),
                      ElevatedButton.icon(
                        onPressed: () => _printReportPdf(_buildReportPayload()),
                        icon: const Icon(Icons.print),
                        label: const Text("PRINT/PDF"),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.grey[700],
                          foregroundColor: Colors.white,
                        ),
                      ),
                      const SizedBox(width: 12),
                      ElevatedButton(
                        onPressed: () => Navigator.pop(ctx, true),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.deepPurple,
                          foregroundColor: Colors.white,
                        ),
                        child: const Text("CONFIRM & SUBMIT"),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ) ??
        false;

    if (confirm) {
      _submitReport();
    }
  }

  Widget _previewSectionTitle(String title) => Padding(
    padding: const EdgeInsets.only(top: 16, bottom: 8),
    child: Text(
      title,
      style: const TextStyle(
        fontWeight: FontWeight.bold,
        fontSize: 16,
        color: Colors.blueGrey,
      ),
    ),
  );
  Widget _previewRow(String label, String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          flex: 2,
          child: Text(label, style: const TextStyle(color: Colors.grey)),
        ),
        Expanded(
          flex: 3,
          child: Text(
            value,
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        ),
      ],
    ),
  );

  Widget _buildPreviewMaterialList(String title, List<MaterialItem> list) {
    if (list.isEmpty) return const SizedBox();

    List<Widget> children = [];
    children.add(
      Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
    );
    children.add(const SizedBox(height: 6));

    children.add(
      Row(
        children: const [
          Expanded(
            flex: 4,
            child: Text(
              'Material Type',
              style: TextStyle(fontWeight: FontWeight.bold),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text('Batch', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
          Expanded(
            flex: 2,
            child: Text('Start', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
          Expanded(
            flex: 2,
            child: Text('Stop', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
          Expanded(
            flex: 2,
            child: Text('Used', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
    children.add(const SizedBox(height: 4));

    double overallTotal = 0.0;

    for (final it in list) {
      final String type = (it.type.text ?? 'Unknown').trim();
      final String batch = (it.batch.text.trim().isNotEmpty)
          ? it.batch.text
          : 'No Batch';
      final String start = it.start.text.trim().isNotEmpty ? it.start.text : '-';
      final String stop = it.stop.text.trim().isNotEmpty ? it.stop.text : '-';
      final double used = it.used;

      overallTotal += used;

      children.add(
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 2.0),
          child: Row(
            children: [
              Expanded(flex: 4, child: Text(type)),
              Expanded(flex: 2, child: Text(batch)),
              Expanded(flex: 2, child: Text(start)),
              Expanded(flex: 2, child: Text(stop)),
              Expanded(flex: 2, child: Text(used.toStringAsFixed(2))),
            ],
          ),
        ),
      );
    }

    children.add(const Divider());
    children.add(
      Padding(
        padding: const EdgeInsets.only(top: 4.0),
        child: Row(
          children: [
            Expanded(
              flex: 4,
              child: Text(
                'Overall Total',
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            ),
            const Expanded(flex: 2, child: SizedBox()),
            const Expanded(flex: 2, child: SizedBox()),
            const Expanded(flex: 2, child: SizedBox()),
            Expanded(
              flex: 2,
              child: Text(
                overallTotal.toStringAsFixed(2),
                textAlign: TextAlign.right,
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            ),
          ],
        ),
      ),
    );

    return Padding(
      padding: const EdgeInsets.only(bottom: 8.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final w in children)
            Padding(padding: const EdgeInsets.only(bottom: 2.0), child: w),
        ],
      ),
    );
  }

  // Проверяем, что никакой материал не имеет отрицательное значение
  bool _hasNegativeMaterials() {
    List<List<MaterialItem>> allLists = [
      _acetate,
      _paper,
      _pvaGlue,
      _hmGlue,
      _triacetin,
    ];
    for (var list in allLists) {
      for (var material in list) {
        // Ensure used is up-to-date from text fields
        material.calculateUsed();
        if (material.used < 0) {
          return true;
        }
      }
    }
    return false;
  }

  Future<void> _submitReport({bool? closeShiftOverride}) async {
    if (_isSubmitting) return;
    // Валидация формы
    if (!_formKey.currentState!.validate()) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          backgroundColor: Colors.red,
          content: Text('Please fix form errors before submitting.'),
        ),
      );
      return;
    }

    // Обновим расчёт для всех материалов и проверим отрицательные значения
    if (_hasNegativeMaterials()) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          backgroundColor: Colors.red,
          content: Text(
            "Error: Material 'Stop' cannot be greater than 'Start'. Check all materials before submitting.",
          ),
        ),
      );
      return;
    }

    String date = _getShiftDateString();
    String uniqueKey =
        "$date|${_selectedMachine?.name}|${_selectedShift?.name}|${_startTimeCtrl.text}-${_endTimeCtrl.text}";

    if (_editingSourceId == null &&
        AppData.submittedReports.contains(uniqueKey)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          backgroundColor: Colors.red,
          content: Text("Error: Report already submitted!"),
        ),
      );
      return;
    }

    final closeShiftAfter = closeShiftOverride ?? await _promptSmartShiftClose();

    setState(() => _isSubmitting = true);

    // Use the canonical payload builder to include material lists and correct fields
    final reportData = _buildReportPayload();

    try {
      final reportId = await ApiService.submitProductionReport(reportData);

      if (_editingSourceId != null) {
        await LocalDB.instance.updateStatus(_editingSourceId!, 'obsolete');
      }

      if (reportId != null) {
        if (_editingSourceId != null) {
          await LocalDB.instance.updateStatus(_editingSourceId!, 'obsolete');
        }
        if (_currentDraftId != null) {
          await LocalDB.instance.updateStatus(_currentDraftId!, 'synced');
        } else {
          _currentDraftId = await LocalDB.instance.saveReport(
            'synced',
            reportData,
          );
        }
        AppData.submittedReports.add(uniqueKey);

        // --- Generate PDF in Flutter and upload to server ---
        try {
          final pdfDoc = pw.Document();
          pdfDoc.addPage(
            pw.MultiPage(
              pageFormat: PdfPageFormat.a4,
              build: (ctx) {
                List<pw.Widget> rows = [];
                void addRow(String label, String value) {
                  rows.add(pw.Row(
                    mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
                    children: [
                      pw.Expanded(child: pw.Text(label, style: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 10))),
                      pw.Text(value, style: pw.TextStyle(fontSize: 10)),
                    ],
                  ));
                  rows.add(pw.SizedBox(height: 4));
                }
                void addSection(String title) {
                  rows.add(pw.SizedBox(height: 12));
                  rows.add(pw.Text(title, style: pw.TextStyle(fontSize: 12, fontWeight: pw.FontWeight.bold)));
                  rows.add(pw.Divider());
                }
                addSection('General Info');
                addRow('Operator', reportData['operator_name'] ?? '');
                addRow('Shift Date', reportData['shift_date'] ?? reportData['report_date'] ?? '');
                addRow('Shift', '${reportData['shift_name']} (${reportData['shift_time_range'] ?? ''})');
                addRow('Machine', reportData['machine_name'] ?? '');
                addRow('MO Number', reportData['po_number'] ?? '');
                addRow('Lot Number', reportData['lot_number'] ?? '');
                addSection('PO Specifications');
                addRow('Box Type', reportData['box_type'].toString());
                addRow('Diameter / Length', '${reportData['diameter']} / ${reportData['length']}');
                addRow('PD / Weight', '${reportData['pd']} / ${reportData['weight']}');
                addSection('Production Log');
                addRow('Boxes Produced', reportData['boxes_produced'].toString());
                addRow('Produced Rods', reportData['produced_rods'].toString());
                addRow('Machine Counter', reportData['machine_counter'].toString());
                addRow('Difference', '${reportData['difference']} (${reportData['diff_percent']})');
                addRow('Waste (kg)', reportData['waste_kg'].toString());
                addRow('Efficiency (%)', reportData['machine_efficiency'].toString());
                addSection('Total Materials');
                addRow('Acetate', reportData['total_acetate']?.toString() ?? '0.0');
                addRow('Paper', reportData['total_paper']?.toString() ?? '0.0');
                addRow('PVA (Cold Glue)', reportData['total_pva']?.toString() ?? '0.0');
                addRow('Hot Melt Glue', reportData['total_hm']?.toString() ?? '0.0');
                addRow('Triacetin', reportData['total_triacetin']?.toString() ?? '0.0');

                void addMaterialsTable(String title, List<dynamic>? items) {
                  if (items == null || items.isEmpty) return;
                  addSection(title);
                  double toDouble(dynamic v) {
                    if (v == null) return 0.0;
                    if (v is num) return v.toDouble();
                    return double.tryParse(v.toString()) ?? 0.0;
                  }
                  double total = 0.0;
                  final List<List<String>> table = [['Material Type', 'Batch', 'Start', 'Stop', 'Used']];
                  for (final it in items) {
                    final type = (it['type']?.toString() ?? 'Unknown').trim();
                    final batch = (it['batch']?.toString().isNotEmpty == true) ? it['batch'].toString() : 'No Batch';
                    final start = it['start']?.toString().trim().isNotEmpty == true ? it['start'].toString() : '-';
                    final stop = it['stop']?.toString().trim().isNotEmpty == true ? it['stop'].toString() : '-';
                    final used = it.containsKey('used') && it['used'] != null ? toDouble(it['used']) : (toDouble(it['start']) - toDouble(it['stop']));
                    total += used;
                    table.add([type, batch, start, stop, used.toStringAsFixed(2)]);
                  }
                  table.add(['Total', '', '', '', total.toStringAsFixed(2)]);
                  rows.add(pw.Table.fromTextArray(
                    headers: table.first,
                    data: table.sublist(1),
                    headerStyle: pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 9),
                    cellStyle: pw.TextStyle(fontSize: 9),
                    headerDecoration: const pw.BoxDecoration(color: PdfColors.grey300),
                  ));
                  rows.add(pw.SizedBox(height: 6));
                }

                addMaterialsTable('Acetate (Tow)', reportData['acetate_list'] as List<dynamic>?);
                addMaterialsTable('Paper', reportData['paper_list'] as List<dynamic>?);
                addMaterialsTable('PVA (Cold Glue)', reportData['pva_list'] as List<dynamic>?);
                addMaterialsTable('Hot Melt Glue', reportData['hm_list'] as List<dynamic>?);
                addMaterialsTable('Triacetin', reportData['tri_list'] as List<dynamic>?);

                addSection('Remarks');
                rows.add(pw.Text(
                  reportData['remarks']?.toString().isNotEmpty == true ? reportData['remarks'] : 'No remarks.',
                  style: pw.TextStyle(fontSize: 10),
                ));

                return [pw.Header(level: 0, text: 'Production Report'), ...rows];
              },
            ),
          );

          final pdfBytes = await pdfDoc.save();
          final shiftDate = (reportData['report_date'] ?? '').toString().split('T').first;
          final machineName = (reportData['machine_name'] ?? 'Machine').toString().replaceAll(RegExp(r'[^\w\s]'), '');
          final shiftName = (reportData['shift_name'] ?? 'Shift').toString().replaceAll(RegExp(r'[^\w\s]'), '');
          final filename = '$shiftDate Production reports $machineName $shiftName.pdf';

          unawaited(ApiService.uploadPdf(
            pdfBytes: pdfBytes,
            filename: filename,
            reportDate: shiftDate,
            reportId: reportId,
          ));
        } catch (pdfErr) {
          debugPrint('PDF upload error (non-critical): $pdfErr');
        }

        try {
          await AppData.loadDataFromServer(forceSync: true);
        } catch (_) {
          // Если обновление не удалось, отчет все равно отправлен.
        }

        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text("✅ Sent to server!"),
              backgroundColor: Colors.green,
            ),
          );
          if (closeShiftAfter) {
            await _closeActiveShift();
          } else {
            Navigator.pushReplacement(
              context,
              MaterialPageRoute(
                builder: (_) => ReportPage(operator: widget.operator),
              ),
            );
          }
        }
      } else {
        await LocalDB.instance.saveReport(
          'pending',
          reportData,
          existingId: _currentDraftId,
        );
        if (_editingSourceId != null) {
          await LocalDB.instance.updateStatus(_editingSourceId!, 'obsolete');
        }
        AppData.submittedReports.add(uniqueKey);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text("⚠️ Report not sent. Saved to local queue."),
              backgroundColor: Colors.orange,
            ),
          );
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(
              builder: (_) => ReportPage(operator: widget.operator),
            ),
          );
        }
      }
    } catch (e) {
      await LocalDB.instance.saveReport(
        'pending',
        reportData,
        existingId: _currentDraftId,
      );
      if (_editingSourceId != null) {
        await LocalDB.instance.updateStatus(_editingSourceId!, 'obsolete');
      }
      if (mounted) {
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(
            builder: (_) => ReportPage(operator: widget.operator),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  // -------------------------------------------------------------------------
  // ГЛАВНЫЙ ФИКС ОТОБРАЖЕНИЯ: Эта функция ставит текст строго над рамкой
  // -------------------------------------------------------------------------
  Widget _labeledField(String label, Widget child) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 4.0, left: 2.0),
          child: Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              color: Colors.blueGrey,
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
        child,
      ],
    );
  }

  String _odooCategory(MaterialCategory c) {
    switch (c) {
      case MaterialCategory.acetate: return 'acetate';
      case MaterialCategory.paper: return 'paper';
      case MaterialCategory.coldGlue:
      case MaterialCategory.hotMelt: return 'glue';
      case MaterialCategory.triacetin: return 'triacetin';
    }
  }

  List<String> _allowedTypes(MaterialCategory category) {
    final am = _selectedPO?.allowedMaterials;
    if (am == null) return [];
    final list = am[_odooCategory(category)];
    if (list is! List) return [];
    return list
        .map((e) => (e is Map ? e['product_name']?.toString() ?? '' : ''))
        .where((s) => s.isNotEmpty)
        .toList();
  }

  Widget _buildMaterialTable(
    String title,
    List<MaterialItem> list,
    String defaultType,
    MaterialCategory category,
  ) {
    // ВАЖНО: Мы полностью убираем labelText из стилей!
    final fieldStyle = InputDecoration(
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(6)),
      contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
      isDense: true,
    );

    return Card(
      elevation: 2,
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                    color: Colors.deepPurple,
                  ),
                ),
                IconButton(
                  icon: const Icon(
                    Icons.add_circle,
                    color: Colors.green,
                    size: 28,
                  ),
                  onPressed: () => setState(
                    () => list.add(MaterialItem(defaultType: defaultType)),
                  ),
                ),
              ],
            ),
            const Divider(),

            if (list.isEmpty)
              const Padding(
                padding: EdgeInsets.all(8.0),
                child: Text(
                  "No items added",
                  style: TextStyle(
                    color: Colors.grey,
                    fontStyle: FontStyle.italic,
                  ),
                ),
              ),

            ...list.asMap().entries.map((e) {
              List<String> availableMaterials = _allowedTypes(category);
              if (availableMaterials.isEmpty) {
                availableMaterials = AppData.materialDictionary
                    .where((m) => m.category == category && !m.isHidden)
                    .map((m) => m.type)
                    .toList();
              }
              String currentType = e.value.type.text;
              if (currentType.isNotEmpty &&
                  !availableMaterials.contains(currentType)) {
                availableMaterials.add(currentType);
              }

              return Container(
                margin: const EdgeInsets.only(bottom: 12),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.grey[50],
                  border: Border.all(color: Colors.grey[300]!),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    final isNarrow = constraints.maxWidth < 620;

                    Widget typeField = _labeledField(
                      "Type",
                      DropdownButtonFormField<String>(
                        initialValue: currentType.isEmpty ? null : currentType,
                        decoration: fieldStyle.copyWith(
                          filled: !_isModifyEnabled,
                          fillColor: _isModifyEnabled ? null : Colors.grey[200],
                        ),
                        isExpanded: true,
                        validator: _reqValidator,
                        selectedItemBuilder: (context) =>
                            availableMaterials
                                .map((m) => Tooltip(
                                      message: m,
                                      child: Text(
                                        m,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ))
                                .toList(),
                        items: availableMaterials
                            .map(
                              (m) => DropdownMenuItem(
                                value: m,
                                child: Tooltip(
                                  message: m,
                                  child: Text(
                                    m,
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              ),
                            )
                            .toList(),
                        onChanged: _isModifyEnabled
                            ? (v) {
                                if (v != null) setState(() => e.value.type.text = v);
                              }
                            : null,
                      ),
                    );

                    Widget batchField = _labeledField(
                      "Batch #",
                      TextFormField(
                        controller: e.value.batch,
                        decoration: fieldStyle.copyWith(
                          hintText: "Optional",
                        ),
                      ),
                    );

                    return Column(
                      children: [
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(child: typeField),
                            if (!isNarrow) const SizedBox(width: 8),
                            if (!isNarrow) Expanded(child: batchField),
                            Padding(
                              padding: const EdgeInsets.only(top: 20),
                              child: IconButton(
                                icon: const Icon(
                                  Icons.delete_outline,
                                  color: Colors.red,
                                ),
                                onPressed: () => setState(() => list.removeAt(e.key)),
                              ),
                            ),
                          ],
                        ),
                        if (isNarrow) ...[
                          const SizedBox(height: 8),
                          batchField,
                        ],
                        const SizedBox(height: 12),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Expanded(
                              child: _labeledField(
                                "Start",
                                TextFormField(
                                  controller: e.value.start,
                                  keyboardType:
                                      const TextInputType.numberWithOptions(decimal: true),
                                  autovalidateMode: AutovalidateMode.onUserInteraction,
                                  decoration: fieldStyle,
                                  validator: (val) {
                                    if (val == null || val.trim().isEmpty) return 'Req';
                                    final parsed = double.tryParse(val.replaceAll(',', '.'));
                                    if (parsed == null) return 'Invalid';
                                    if (parsed < 0) return 'Must be ≥ 0';
                                    if (e.value.stop.text.trim().isNotEmpty) {
                                      final stop = double.tryParse(e.value.stop.text.replaceAll(',', '.'));
                                      if (stop != null && parsed < stop) return 'Start < Stop';
                                    }
                                    return null;
                                  },
                                  onChanged: (_) => setState(() => e.value.calculateUsed()),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: _labeledField(
                                "Stop",
                                TextFormField(
                                  controller: e.value.stop,
                                  keyboardType:
                                      const TextInputType.numberWithOptions(decimal: true),
                                  autovalidateMode: AutovalidateMode.onUserInteraction,
                                  decoration: fieldStyle,
                                  validator: (val) {
                                    if (val == null || val.trim().isEmpty) return 'Req';
                                    final parsed = double.tryParse(val.replaceAll(',', '.'));
                                    if (parsed == null) return 'Invalid';
                                    if (parsed < 0) return 'Must be ≥ 0';
                                    if (e.value.start.text.trim().isNotEmpty) {
                                      final start = double.tryParse(e.value.start.text.replaceAll(',', '.'));
                                      if (start != null && parsed > start) return 'Stop > Start';
                                    }
                                    return null;
                                  },
                                  onChanged: (_) => setState(() => e.value.calculateUsed()),
                                ),
                              ),
                            ),
                            const SizedBox(width: 12),
                            Column(
                              children: [
                                const Text(
                                  "Used",
                                  style: TextStyle(fontSize: 12, color: Colors.grey),
                                ),
                                Text(
                                  e.value.used == e.value.used.truncateToDouble()
                                      ? e.value.used.toInt().toString()
                                      : e.value.used.toStringAsFixed(1),
                                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18, color: Colors.blue),
                                ),
                              ],
                            ),
                            const SizedBox(width: 4),
                          ],
                        ),
                      ],
                    );
                  },
                ),
              );
            }),

            const Divider(),
            Align(
              alignment: Alignment.centerRight,
              child: Padding(
                padding: const EdgeInsets.only(top: 4, right: 8),
                child: Text(
                  () {
                    final total = _calculateTotal(list);
                    return "TOTAL: ${total == total.truncateToDouble() ? total.toInt().toString() : total.toStringAsFixed(1)}";
                  }(),
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: Colors.deepPurple,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // ВАЖНО: Мы полностью убираем labelText из стилей!
    final activeStyle = InputDecoration(
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(6)),
      contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
      isDense: true,
    );

    final lockedStyle = activeStyle.copyWith(
      filled: true,
      fillColor: Colors.grey[200],
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(6),
        borderSide: BorderSide.none,
      ),
    );

    final poValueStyle = _isModifyEnabled ? activeStyle : lockedStyle;

    return Scaffold(
      appBar: AppBar(
        title: Text("Operator: ${widget.operator.name}"),
        backgroundColor: Colors.deepPurple,
        foregroundColor: Colors.white,
        bottom: const DevBannerBar(),
        actions: [
          IconButton(
            icon: const Icon(Icons.history),
            tooltip: 'Production History',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) =>
                      HistoryScreen(operator: widget.operator),
                ),
              );
            },
          ),
          if (_activeShift != null) ...[
            IconButton(
              icon: const Icon(Icons.swap_horiz),
              tooltip: 'Change MO / Order',
              onPressed: _changeMo,
            ),
            IconButton(
              icon: const Icon(Icons.fact_check_outlined),
              tooltip: 'Quality Checks',
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (context) =>
                        ManualQualityChecksScreen(shiftContext: _activeShift),
                  ),
                );
              },
            ),
          ],
          IconButton(
            icon: const Icon(Icons.assignment_late_outlined),
            tooltip: 'Pending Reports',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (context) => PendingShiftsScreen(operator: widget.operator)),
              );
            },
          ),
          if (_activeShift != null)
            IconButton(
              icon: const Icon(Icons.stop_circle_outlined),
              tooltip: 'End Shift',
              onPressed: _endShift,
            ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Logout',
            onPressed: () => Navigator.pushAndRemoveUntil(
              context,
              MaterialPageRoute(builder: (context) => const LoginScreen()),
              (route) => false,
            ),
          ),
        ],
      ),
      body: _activeShift == null
          ? _buildInactiveShiftView()
          : Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 650),
          child: Form(
            key: _formKey,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _buildSectionHeader("Shift & Machine"),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      children: [
                        _labeledField(
                          "Shift Date",
                          InkWell(
                            onTap: _adjustTime
                                ? () async {
                                    DateTime initial = DateTime.now();
                                    try {
                                      initial = DateTime.parse(_getShiftDateString());
                                    } catch (_) {}
                                    final picked = await showDatePicker(
                                      context: context,
                                      initialDate: initial,
                                      firstDate: DateTime(2000),
                                      lastDate: DateTime(2100),
                                    );
                                    if (picked != null) {
                                      setState(() => _manualShiftDate = picked);
                                    }
                                  }
                                : null,
                            child: Container(
                              width: double.infinity,
                              padding: const EdgeInsets.symmetric(
                                vertical: 14,
                                horizontal: 12,
                              ),
                              decoration: BoxDecoration(
                                color: Colors.grey[100],
                                borderRadius: BorderRadius.circular(6),
                                border: Border.all(color: Colors.grey.shade400),
                              ),
                              child: Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Text(
                                    _getShiftDateDisplay(),
                                    style: const TextStyle(fontSize: 16),
                                  ),
                                  if (_adjustTime)
                                    const Icon(Icons.edit, size: 18),
                                ],
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        _labeledField(
                          "Select Shift",
                          DropdownButtonFormField<Shift>(
                            initialValue: _selectedShift,
                            decoration: activeStyle,
                            validator: (v) => v == null ? 'Required' : null,
                            items: AppData.shifts
                                .map(
                                  (s) => DropdownMenuItem(
                                    value: s,
                                    child: Text(s.name),
                                  ),
                                )
                                .toList(),
                            // Locked: the shift is fixed when the shift is opened.
                            onChanged: null,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            Expanded(
                              child: _labeledField(
                                "Start Time",
                                TextFormField(
                                  controller: _startTimeCtrl,
                                  readOnly: !_adjustTime,
                                  decoration: activeStyle.copyWith(
                                    filled: !_adjustTime,
                                    fillColor: _adjustTime
                                        ? null
                                        : Colors.grey[100],
                                  ),
                                ),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: _labeledField(
                                "End Time",
                                TextFormField(
                                  controller: _endTimeCtrl,
                                  readOnly: !_adjustTime,
                                  decoration: activeStyle.copyWith(
                                    filled: !_adjustTime,
                                    fillColor: _adjustTime
                                        ? null
                                        : Colors.grey[100],
                                  ),
                                ),
                              ),
                            ),
                            Padding(
                              padding: const EdgeInsets.only(top: 18, left: 8),
                              child: Column(
                                children: [
                                  const Text(
                                    "Adjust",
                                    style: TextStyle(fontSize: 10),
                                  ),
                                  Checkbox(
                                    value: _adjustTime,
                                    onChanged: (v) =>
                                        setState(() => _adjustTime = v!),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        _labeledField(
                          "Machine #",
                          DropdownButtonFormField<Machine>(
                            initialValue: _selectedMachine,
                            decoration: activeStyle,
                            validator: (v) => v == null ? 'Required' : null,
                            items: AppData.machines
                                .where(
                                  (m) => !m.isInactive || m == _selectedMachine,
                                )
                                .toSet()
                                .map(
                                  (m) => DropdownMenuItem<Machine>(
                                    value: m,
                                    child: Text(m.name),
                                  ),
                                )
                                .toList(),
                            // Locked: the machine is part of the shift / run (like the MO).
                            // Use the "Change machine" button in the app bar to move it.
                            onChanged: null,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),

                _buildSectionHeader("Manufacturing Order"),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      children: [
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Expanded(
                              child: _labeledField(
                                "Select MO #",
                                DropdownButtonFormField<PurchaseOrder>(
                                  initialValue: _selectedPO,
                                  decoration: activeStyle,
                                  items: AppData.activePOs
                                      .where(
                                        (po) =>
                                            !po.isHidden || po == _selectedPO,
                                      )
                                      .toSet()
                                      .map(
                                        (po) => DropdownMenuItem(
                                          value: po,
                                          child: Text(po.poNumber),
                                        ),
                                      )
                                      .toList(),
                                  onChanged: null, // locked: MO set via Start Shift / AppBar switch
                                  validator: (value) =>
                                      value == null ? 'Required' : null,
                                ),
                              ),
                            ),
                            if (_isDataModified)
                              const Padding(
                                padding: EdgeInsets.only(left: 8, bottom: 10),
                                child: Text(
                                  "MODIFIED",
                                  style: TextStyle(
                                    color: Colors.red,
                                    fontWeight: FontWeight.bold,
                                    fontSize: 10,
                                  ),
                                ),
                              ),
                            if (widget.operator.canModifyPO)
                              Padding(
                                padding: const EdgeInsets.only(left: 8),
                                child: Column(
                                  children: [
                                    const Text(
                                      "Modify",
                                      style: TextStyle(fontSize: 10),
                                    ),
                                    Checkbox(
                                      value: _isModifyEnabled,
                                      onChanged: _confirmModify,
                                    ),
                                  ],
                                ),
                              ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        _labeledField(
                          "Lot Number",
                          TextFormField(
                            controller: _lotController,
                            decoration: activeStyle,
                            keyboardType: TextInputType.visiblePassword,
                            autocorrect: false,
                            enableSuggestions: false,
                            validator: _reqValidator,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            Expanded(
                              child: _labeledField(
                                "Box Type",
                                TextFormField(
                                  controller: _boxTypeController,
                                  enabled: _isModifyEnabled,
                                  keyboardType: TextInputType.number,
                                  validator: _validatePositiveInt,
                                  decoration: poValueStyle,
                                ),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: _labeledField(
                                "Diameter",
                                TextFormField(
                                  controller: _diameterController,
                                  enabled: _isModifyEnabled,
                                  keyboardType:
                                      const TextInputType.numberWithOptions(
                                        decimal: true,
                                      ),
                                  validator: _validateDiameter,
                                  decoration: poValueStyle,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            Expanded(
                              child: _labeledField(
                                "Length",
                                TextFormField(
                                  controller: _lengthController,
                                  enabled: _isModifyEnabled,
                                  keyboardType:
                                      const TextInputType.numberWithOptions(
                                        decimal: true,
                                      ),
                                  validator: _validateLengthWeight,
                                  decoration: poValueStyle,
                                ),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: _labeledField(
                                "PD",
                                TextFormField(
                                  controller: _pdController,
                                  enabled: _isModifyEnabled,
                                  keyboardType: TextInputType.number,
                                  validator: _validatePositiveInt,
                                  decoration: poValueStyle,
                                ),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: _labeledField(
                                "Weight",
                                TextFormField(
                                  controller: _weightController,
                                  enabled: _isModifyEnabled,
                                  keyboardType:
                                      const TextInputType.numberWithOptions(
                                        decimal: true,
                                      ),
                                  validator: _validateLengthWeight,
                                  decoration: poValueStyle,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),

                _buildSectionHeader("Raw Materials"),
                _buildMaterialTable(
                  "Acetate (Tow)",
                  _acetate,
                  _selectedPO?.acetateType ?? "",
                  MaterialCategory.acetate,
                ),
                _buildMaterialTable(
                  "Paper",
                  _paper,
                  _selectedPO?.paperType ?? "",
                  MaterialCategory.paper,
                ),
                _buildMaterialTable(
                  "PVA (Cold Glue)",
                  _pvaGlue,
                  _selectedPO?.pvaGlueType ?? "",
                  MaterialCategory.coldGlue,
                ),
                _buildMaterialTable(
                  "Hot Melt Glue",
                  _hmGlue,
                  _selectedPO?.hmGlueType ?? "",
                  MaterialCategory.hotMelt,
                ),
                _buildMaterialTable(
                  "Triacetin",
                  _triacetin,
                  _selectedPO?.triacetinType ?? "",
                  MaterialCategory.triacetin,
                ),

                _buildSectionHeader("Production Log"),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      children: [
                        _labeledField(
                          "Box Produced",
                          TextFormField(
                            controller: _boxProducedController,
                            decoration: activeStyle,
                            validator: _reqValidator,
                            keyboardType: TextInputType.number,
                            onChanged: (_) => _calculateProductionLog(),
                          ),
                        ),
                        const SizedBox(height: 12),
                        _labeledField(
                          "Machine Counter",
                          TextFormField(
                            controller: _machineCounterController,
                            decoration: activeStyle,
                            validator: _reqValidator,
                            keyboardType: TextInputType.number,
                            onChanged: (_) => _calculateProductionLog(),
                          ),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            Expanded(
                              child: _labeledField(
                                "Produced Rods",
                                TextFormField(
                                  controller: _rodsProducedController,
                                  readOnly: true,
                                  decoration: lockedStyle,
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: _labeledField(
                                "Difference",
                                TextFormField(
                                  controller: _differenceController,
                                  readOnly: true,
                                  decoration: lockedStyle,
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: _labeledField(
                                "Diff %",
                                TextFormField(
                                  controller: _diffPercentController,
                                  readOnly: true,
                                  decoration: lockedStyle,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            Expanded(
                              child: _labeledField(
                                "Waste (kg)",
                                TextFormField(
                                  controller: _wasteController,
                                  decoration: activeStyle,
                                  validator: _reqValidator,
                                  keyboardType: TextInputType.number,
                                ),
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: _labeledField(
                                "Efficiency %",
                                TextFormField(
                                  controller: _efficiencyController,
                                  decoration: activeStyle,
                                  validator: _reqValidator,
                                  keyboardType: TextInputType.number,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),

                _buildSectionHeader("Remarks"),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: _labeledField(
                      "Comments",
                      TextFormField(
                        controller: _remarksController,
                        maxLines: 2,
                        decoration: activeStyle.copyWith(
                          hintText: "Optional notes...",
                        ),
                      ),
                    ),
                  ),
                ),

                const SizedBox(height: 32),
                Column(
                  children: [
                    Row(
                        children: [
                          Expanded(
                            child: OutlinedButton(
                            onPressed: (_isSubmitting || _isSaving) ? null : _saveAsDraft,
                              style: OutlinedButton.styleFrom(
                                minimumSize: const Size(0, 56),
                                side: const BorderSide(
                                  color: Colors.deepPurple,
                                ),
                              ),
                            child: _isSaving
                                ? const SizedBox(
                                    width: 24,
                                    height: 24,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.deepPurple,
                                    ),
                                  )
                                : const Text(
                                "SAVE DRAFT",
                                style: TextStyle(
                                  color: Colors.deepPurple,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            flex: 2,
                            child: ElevatedButton(
                            onPressed: (_isSubmitting || _isSaving || _activeShift == null)
                  ? null
                  : _showPreviewAndSubmit,
                              style: ElevatedButton.styleFrom(
                                minimumSize: const Size(0, 56),
                                backgroundColor: Colors.deepPurple,
                                foregroundColor: Colors.white,
                              ),
                            child: _isSubmitting
                                ? const SizedBox(
                                    width: 24,
                                    height: 24,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.white,
                                    ),
                                  )
                                : const Text(
                                "SUBMIT REPORT",
                                style: TextStyle(
                                  fontSize: 18,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                          ),
                      ],
                    ),
                    if (_isSubmitting) ...[
                      const SizedBox(height: 8),
                      const Text(
                        "Sending report...",
                        style: TextStyle(color: Colors.grey, fontSize: 13),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 60),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildSectionHeader(String title) => Padding(
    padding: const EdgeInsets.only(top: 20, bottom: 8, left: 4),
    child: Text(
      title,
      style: const TextStyle(
        fontSize: 18,
        fontWeight: FontWeight.bold,
        color: Colors.deepPurple,
      ),
    ),
  );
}
