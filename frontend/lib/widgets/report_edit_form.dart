// lib/widgets/report_edit_form.dart
// Full-parity supervisor report editor. Replaces the old stripped-down dialog
// with a full-screen form mirroring the operator submission screen. On save it
// returns the PUT payload consumed by ApiService.updateReport (PUT /api/reports/{id}).
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../models.dart';
import '../api_service.dart';

/// Opens the full-screen report editor. Returns the PUT payload on save, or
/// null when cancelled. Callers then invoke ApiService.updateReport with it.
Future<Map<String, dynamic>?> showReportEditOverlay(
  BuildContext context,
  Map<String, dynamic> report,
) {
  return showGeneralDialog<Map<String, dynamic>>(
    context: context,
    barrierDismissible: false,
    barrierLabel: 'Edit report',
    transitionDuration: const Duration(milliseconds: 180),
    pageBuilder: (ctx, a1, a2) => _ReportEditForm(report: report),
  );
}

class _ReportEditForm extends StatefulWidget {
  final Map<String, dynamic> report;
  const _ReportEditForm({required this.report});
  @override
  State<_ReportEditForm> createState() => _ReportEditFormState();
}

class _ReportEditFormState extends State<_ReportEditForm> {
  final _formKey = GlobalKey<FormState>();

  late final bool _lockRunFields;

  late final TextEditingController _shiftController;
  late final TextEditingController _machineController;
  late final TextEditingController _operatorController;
  late final TextEditingController _poController;
  late final TextEditingController _timeRangeController;
  late final TextEditingController _lotController;
  late final TextEditingController _boxTypeController;
  late final TextEditingController _diameterController;
  late final TextEditingController _lengthController;
  late final TextEditingController _pdController;
  late final TextEditingController _weightController;
  late final TextEditingController _boxesController;
  late final TextEditingController _counterController;
  late final TextEditingController _rodsController;
  late final TextEditingController _differenceController;
  late final TextEditingController _diffPercentController;
  late final TextEditingController _wasteController;
  late final TextEditingController _efficiencyController;
  late final TextEditingController _remarksController;

  DateTime? _reportDate;

  final List<MaterialItem> _acetate = [];
  final List<MaterialItem> _paper = [];
  final List<MaterialItem> _pva = [];
  final List<MaterialItem> _hm = [];
  final List<MaterialItem> _tri = [];

  PurchaseOrder? _po;

  static String _s(dynamic v) => v == null ? '' : v.toString();

  static List<MaterialItem> _list(dynamic v) {
    if (v is! List) return [];
    return v
        .whereType<Map>()
        .map((e) => MaterialItem.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }

  @override
  void initState() {
    super.initState();
    final r = widget.report;
    _lockRunFields = r['run_id'] != null;

    _shiftController = TextEditingController(text: _s(r['shift_name']));
    _machineController = TextEditingController(text: _s(r['machine_name']));
    _operatorController = TextEditingController(text: _s(r['operator_name']));
    _poController = TextEditingController(text: _s(r['po_number']));
    _timeRangeController = TextEditingController(text: _s(r['shift_time_range']));
    _lotController = TextEditingController(text: _s(r['lot_number']));
    _boxTypeController = TextEditingController(text: _s(r['box_type']));
    _diameterController = TextEditingController(text: _s(r['diameter']));
    _lengthController = TextEditingController(text: _s(r['length']));
    _pdController = TextEditingController(text: _s(r['pd']));
    _weightController = TextEditingController(text: _s(r['weight']));
    _boxesController = TextEditingController(text: _s(r['boxes_produced']));
    _counterController = TextEditingController(text: _s(r['machine_counter']));
    _rodsController = TextEditingController(text: _s(r['produced_rods']));
    _differenceController = TextEditingController(text: _s(r['difference']));
    _diffPercentController = TextEditingController(
        text: _s(r['diff_percent']).replaceAll('%', ''));
    _wasteController = TextEditingController(text: _s(r['waste_kg']));
    _efficiencyController = TextEditingController(text: _s(r['machine_efficiency']));
    _remarksController = TextEditingController(text: _s(r['remarks']));

    final dateStr = _s(r['report_date']);
    _reportDate = DateTime.tryParse(dateStr) ?? DateTime.now();

    _acetate.addAll(_list(r['acetate_list']));
    _paper.addAll(_list(r['paper_list']));
    _pva.addAll(_list(r['pva_list']));
    _hm.addAll(_list(r['hm_list']));
    _tri.addAll(_list(r['tri_list']));

    _loadOptions();
  }

  @override
  void dispose() {
    for (final c in [
      _shiftController, _machineController, _operatorController, _poController,
      _timeRangeController, _lotController, _boxTypeController, _diameterController,
      _lengthController, _pdController, _weightController, _boxesController,
      _counterController, _rodsController, _differenceController,
      _diffPercentController, _wasteController, _efficiencyController,
      _remarksController,
    ]) {
      c.dispose();
    }
    for (final list in [_acetate, _paper, _pva, _hm, _tri]) {
      for (final m in list) {
        m.dispose();
      }
    }
    super.dispose();
  }
  Future<void> _loadOptions() async {
    final pos = await ApiService.fetchPurchaseOrders();
    if (pos != null && mounted) {
      PurchaseOrder? found;
      for (final p in pos.whereType<Map>()) {
        final po = PurchaseOrder.fromJson(Map<String, dynamic>.from(p));
        if (po.poNumber == _poController.text.trim()) {
          found = po;
          break;
        }
      }
      if (found != null) setState(() => _po = found);
    }
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
    final result = <String>[];
    final am = _po?.allowedMaterials;
    if (am != null) {
      final list = am[_odooCategory(category)];
      if (list is List) {
        for (final e in list) {
          final name = (e is Map ? e['product_name']?.toString() ?? '' : '');
          if (name.isNotEmpty) result.add(name);
        }
      }
    }
    // No BOM alternatives? Fall back to the MO's single configured type only —
    // never the global factory dictionary (BOM integrity).
    if (result.isEmpty) {
      final moType = _defaultType(category).trim();
      if (moType.isNotEmpty) result.add(moType);
    }
    return result;
  }

  String _defaultType(MaterialCategory c) {
    final po = _po;
    if (po == null) return '';
    switch (c) {
      case MaterialCategory.acetate: return po.acetateType;
      case MaterialCategory.paper: return po.paperType;
      case MaterialCategory.coldGlue: return po.pvaGlueType;
      case MaterialCategory.hotMelt: return po.hmGlueType;
      case MaterialCategory.triacetin: return po.triacetinType;
    }
  }

  String _moLabel(MaterialCategory c) {
    final t = _defaultType(c).trim();
    return t.isEmpty ? '' : 'MO expects: $t';
  }

  InputDecoration get _style => InputDecoration(
    border: OutlineInputBorder(borderRadius: BorderRadius.circular(6)),
    contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
    isDense: true,
  );

  InputDecoration get _lockedStyle => _style.copyWith(filled: true, fillColor: Colors.grey[200]);

  Widget _labeledField(String label, Widget child) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Padding(
        padding: const EdgeInsets.only(bottom: 4, left: 2),
        child: Text(label, style: const TextStyle(fontSize: 12, color: Colors.blueGrey, fontWeight: FontWeight.bold)),
      ),
      child,
    ],
  );

  Widget _sectionHeader(String title) => Padding(
    padding: const EdgeInsets.only(top: 20, bottom: 8, left: 4),
    child: Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.deepPurple)),
  );

  Widget _field(String label, TextEditingController c,
      {bool enabled = true, TextInputType? keyboard, String? Function(String?)? validator, ValueChanged<String>? onChanged}) {
    return _labeledField(label, TextFormField(
      controller: c,
      enabled: enabled,
      keyboardType: keyboard,
      validator: validator,
      onChanged: onChanged,
      decoration: enabled ? _style : _lockedStyle,
    ));
  }

  String? _numValidator(String? v) {
    if (v == null || v.trim().isEmpty) return null;
    if (double.tryParse(v.trim().replaceAll(',', '.')) == null) return 'Invalid';
    return null;
  }

  Widget _dateField() {
    final display = _reportDate != null ? DateFormat('dd.MM.yyyy').format(_reportDate!) : '';
    return _labeledField('Report Date', InkWell(
      onTap: () async {
        final picked = await showDatePicker(
          context: context,
          initialDate: _reportDate ?? DateTime.now(),
          firstDate: DateTime(2000),
          lastDate: DateTime(2100),
        );
        if (picked != null) setState(() => _reportDate = picked);
      },
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 12),
        decoration: BoxDecoration(
          color: Colors.grey[100],
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: Colors.grey.shade400),
        ),
        child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text(display, style: const TextStyle(fontSize: 16)),
          const Icon(Icons.edit, size: 18),
        ]),
      ),
    ));
  }
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Edit Report #${widget.report['id'] ?? ''}'),
        backgroundColor: Colors.deepPurple,
        foregroundColor: Colors.white,
        leading: IconButton(
          icon: const Icon(Icons.close),
          tooltip: 'Cancel',
          onPressed: () => Navigator.pop(context),
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: TextButton.icon(
              onPressed: _save,
              icon: const Icon(Icons.save, color: Colors.white),
              label: const Text('SAVE', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
            ),
          ),
        ],
      ),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            if (_lockRunFields)
              Container(
                margin: const EdgeInsets.only(bottom: 12),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.amber.shade50,
                  border: Border.all(color: Colors.amber.shade300),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Row(children: [
                  Icon(Icons.lock_outline, size: 18, color: Colors.orange),
                  SizedBox(width: 8),
                  Expanded(child: Text('This report is bound to a production run — PO/MO and Machine cannot be changed here.', style: TextStyle(fontSize: 12))),
                ]),
              ),
            _sectionHeader('General'),
            Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(children: [
              _dateField(),
              const SizedBox(height: 12),
              _field('Shift Name', _shiftController),
              const SizedBox(height: 12),
              _field('Machine', _machineController, enabled: !_lockRunFields),
              const SizedBox(height: 12),
              _field('Operator', _operatorController),
              const SizedBox(height: 12),
              _field('PO / MO Number', _poController, enabled: !_lockRunFields),
              const SizedBox(height: 12),
              _field('Shift Time Range', _timeRangeController),
            ]))),

            _sectionHeader('Technical Specification'),
            Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(children: [
              _field('Lot Number', _lotController),
              const SizedBox(height: 12),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: _field('Box Type', _boxTypeController, keyboard: TextInputType.number, validator: _numValidator, onChanged: (_) => _recalc())),
                const SizedBox(width: 10),
                Expanded(child: _field('Diameter', _diameterController, keyboard: const TextInputType.numberWithOptions(decimal: true), validator: _numValidator)),
              ]),
              const SizedBox(height: 12),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: _field('Length', _lengthController, keyboard: const TextInputType.numberWithOptions(decimal: true), validator: _numValidator)),
                const SizedBox(width: 10),
                Expanded(child: _field('PD', _pdController, keyboard: TextInputType.number, validator: _numValidator)),
              ]),
              const SizedBox(height: 12),
              _field('Weight', _weightController, keyboard: const TextInputType.numberWithOptions(decimal: true), validator: _numValidator),
            ]))),
            _sectionHeader('Raw Materials'),
            _materialCard('Acetate (Tow)', _acetate, MaterialCategory.acetate),
            _materialCard('Paper', _paper, MaterialCategory.paper),
            _materialCard('PVA (Cold Glue)', _pva, MaterialCategory.coldGlue),
            _materialCard('Hot Melt Glue', _hm, MaterialCategory.hotMelt),
            _materialCard('Triacetin', _tri, MaterialCategory.triacetin),

            _sectionHeader('Production Output'),
            Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(children: [
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: _field('Boxes Produced', _boxesController, keyboard: TextInputType.number, validator: _numValidator, onChanged: (_) => _recalc())),
                const SizedBox(width: 10),
                Expanded(child: _field('Machine Counter', _counterController, keyboard: TextInputType.number, validator: _numValidator, onChanged: (_) => _recalc())),
              ]),
              const SizedBox(height: 12),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: _field('Produced Rods', _rodsController, enabled: false)),
                const SizedBox(width: 8),
                Expanded(child: _field('Difference', _differenceController, enabled: false)),
                const SizedBox(width: 8),
                Expanded(child: _field('Diff %', _diffPercentController, enabled: false)),
              ]),
              const SizedBox(height: 12),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: _field('Waste (kg)', _wasteController, keyboard: const TextInputType.numberWithOptions(decimal: true), validator: _numValidator)),
                const SizedBox(width: 10),
                Expanded(child: _field('Efficiency %', _efficiencyController, keyboard: const TextInputType.numberWithOptions(decimal: true), validator: _numValidator)),
              ]),
            ]))),

            _sectionHeader('Remarks'),
            Card(child: Padding(padding: const EdgeInsets.all(16), child: _labeledField('Comments', TextFormField(
              controller: _remarksController,
              maxLines: 3,
              decoration: _style.copyWith(hintText: 'Optional notes...'),
            )))),

            const SizedBox(height: 32),
            Row(children: [
              Expanded(child: OutlinedButton(
                onPressed: () => Navigator.pop(context),
                style: OutlinedButton.styleFrom(minimumSize: const Size(0, 52), side: const BorderSide(color: Colors.deepPurple)),
                child: const Text('CANCEL', style: TextStyle(color: Colors.deepPurple, fontWeight: FontWeight.bold)),
              )),
              const SizedBox(width: 12),
              Expanded(flex: 2, child: ElevatedButton(
                onPressed: _save,
                style: ElevatedButton.styleFrom(minimumSize: const Size(0, 52), backgroundColor: Colors.deepPurple, foregroundColor: Colors.white),
                child: const Text('SAVE CHANGES', style: TextStyle(fontWeight: FontWeight.bold)),
              )),
            ]),
          ],
        ),
      ),
    );
  }
  Widget _materialCard(String title, List<MaterialItem> list, MaterialCategory category) {
    return Card(
      elevation: 2,
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Text(title, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.deepPurple)),
            IconButton(
              icon: const Icon(Icons.add_circle, color: Colors.green, size: 28),
              onPressed: () => setState(() => list.add(MaterialItem(defaultType: _defaultType(category)))),
            ),
          ]),
          if (_moLabel(category).isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(_moLabel(category),
                  style: const TextStyle(fontSize: 11, color: Colors.blueGrey, fontStyle: FontStyle.italic)),
            ),
          const Divider(),
          if (list.isEmpty)
            const Padding(padding: EdgeInsets.all(8), child: Text('No items added', style: TextStyle(color: Colors.grey, fontStyle: FontStyle.italic))),
          ...list.asMap().entries.map((e) => _materialRow(e.key, e.value, category, list)),
          const Divider(),
          Align(
            alignment: Alignment.centerRight,
            child: Padding(
              padding: const EdgeInsets.only(top: 4, right: 8),
              child: Text('TOTAL: ${_fmtTotal(_total(list))}',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.deepPurple)),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _materialRow(int index, MaterialItem item, MaterialCategory category, List<MaterialItem> list) {
    final options = <String>[..._allowedTypes(category)];
    final currentType = item.type.text.trim();
    if (currentType.isNotEmpty && !options.contains(currentType)) options.add(currentType);
    if (options.isEmpty) options.add(currentType);

    return Container(
      key: ValueKey('mat-${category.name}-$index-$currentType'),
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.grey[50],
        border: Border.all(color: Colors.grey[300]!),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: _labeledField('Type', DropdownButtonFormField<String>(
            initialValue: currentType.isEmpty ? null : currentType,
            isExpanded: true,
            decoration: _style,
            items: options.map((m) => DropdownMenuItem(value: m, child: Text(m, maxLines: 2, overflow: TextOverflow.ellipsis))).toList(),
            onChanged: (v) { if (v != null) setState(() => item.type.text = v); },
          ))),
          const SizedBox(width: 8),
          Expanded(child: _labeledField('Batch #', TextFormField(
            controller: item.batch,
            decoration: _style.copyWith(hintText: 'Optional'),
          ))),
          Padding(padding: const EdgeInsets.only(top: 20), child: IconButton(
            icon: const Icon(Icons.delete_outline, color: Colors.red),
            onPressed: () => setState(() => list.removeAt(index)),
          )),
        ]),
        const SizedBox(height: 12),
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Expanded(child: _labeledField('Start', TextFormField(
            controller: item.start,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: _style,
            validator: _numValidator,
            onChanged: (_) => setState(() => item.calculateUsed()),
          ))),
          const SizedBox(width: 12),
          Expanded(child: _labeledField('Stop', TextFormField(
            controller: item.stop,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: _style,
            validator: _numValidator,
            onChanged: (_) => setState(() => item.calculateUsed()),
          ))),
          const SizedBox(width: 12),
          Column(children: [
            const Text('Used', style: TextStyle(fontSize: 12, color: Colors.grey)),
            Text(_fmtUsed(item.used), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18, color: Colors.blue)),
          ]),
          const SizedBox(width: 4),
        ]),
      ]),
    );
  }

  String _fmtUsed(double v) => v == v.truncateToDouble() ? v.toInt().toString() : v.toStringAsFixed(1);
  String _fmtTotal(double v) => v == v.truncateToDouble() ? v.toInt().toString() : v.toStringAsFixed(1);

  double _total(List<MaterialItem> items) {
    var sum = 0.0;
    for (final it in items) {
      it.calculateUsed();
      sum += it.used;
    }
    return sum;
  }
  void _recalc() {
    final boxType = int.tryParse(_boxTypeController.text.trim()) ?? 0;
    final boxes = int.tryParse(_boxesController.text.trim()) ?? 0;
    final counter = int.tryParse(_counterController.text.trim()) ?? 0;
    final rods = boxes * boxType;
    final diff = counter - rods;
    final diffPct = counter > 0 ? (diff / counter) * 100 : 0.0;
    setState(() {
      _rodsController.text = rods.toString();
      _differenceController.text = diff.toString();
      _diffPercentController.text = diffPct.toStringAsFixed(2);
    });
  }

  bool _hasNegativeMaterials() {
    for (final list in [_acetate, _paper, _pva, _hm, _tri]) {
      for (final m in list) {
        m.calculateUsed();
        if (m.used < 0) return true;
      }
    }
    return false;
  }

  double _d(TextEditingController c) => double.tryParse(c.text.trim().replaceAll(',', '.')) ?? 0.0;
  int _i(TextEditingController c) => int.tryParse(c.text.trim()) ?? 0;

  String get _reportDateStr => _reportDate != null ? DateFormat('yyyy-MM-dd').format(_reportDate!) : '';

  Map<String, dynamic> _buildPayload() {
    final acetateList = _acetate.map((m) { m.calculateUsed(); return m.toJson(); }).toList();
    final paperList = _paper.map((m) { m.calculateUsed(); return m.toJson(); }).toList();
    final pvaList = _pva.map((m) { m.calculateUsed(); return m.toJson(); }).toList();
    final hmList = _hm.map((m) { m.calculateUsed(); return m.toJson(); }).toList();
    final triList = _tri.map((m) { m.calculateUsed(); return m.toJson(); }).toList();

    String flattenType(List<MaterialItem> items) {
      for (final it in items) {
        if (it.type.text.trim().isNotEmpty) return it.type.text.trim();
      }
      return '';
    }
    String flattenBatch(List<MaterialItem> items) {
      for (final it in items) {
        if (it.type.text.trim().isNotEmpty) {
          final b = it.batch.text.trim();
          return b.isEmpty ? 'No Batch' : b;
        }
      }
      return 'No Batch';
    }

    final materialsJson = jsonEncode({
      'acetate_list': acetateList,
      'paper_list': paperList,
      'pva_list': pvaList,
      'hm_list': hmList,
      'tri_list': triList,
    });

    final payload = <String, dynamic>{
      'report_date': _reportDateStr,
      'shift_name': _shiftController.text.trim(),
      'machine_name': _machineController.text.trim(),
      'operator_name': _operatorController.text.trim(),
      'po_number': _poController.text.trim(),
      'shift_time_range': _timeRangeController.text.trim(),
      'lot_number': _lotController.text.trim(),
      'box_type': _i(_boxTypeController),
      'diameter': _d(_diameterController),
      'length': _d(_lengthController),
      'pd': _i(_pdController),
      'weight': _d(_weightController),
      'boxes_produced': _i(_boxesController),
      'machine_counter': _i(_counterController),
      'produced_rods': _i(_rodsController),
      'difference': _d(_differenceController),
      'diff_percent': '${_diffPercentController.text.trim()}%',
      'waste_kg': _d(_wasteController),
      'machine_efficiency': _d(_efficiencyController),
      'total_acetate': _total(_acetate),
      'total_paper': _total(_paper),
      'total_pva': _total(_pva),
      'total_hm': _total(_hm),
      'total_triacetin': _total(_tri),
      'remarks': _remarksController.text.trim(),
      'acetate_type': flattenType(_acetate),
      'acetate_batch': flattenBatch(_acetate),
      'paper_type': flattenType(_paper),
      'paper_batch': flattenBatch(_paper),
      'pva_glue_type': flattenType(_pva),
      'pva_batch': flattenBatch(_pva),
      'hm_glue_type': flattenType(_hm),
      'hm_batch': flattenBatch(_hm),
      'triacetin_type': flattenType(_tri),
      'tri_batch': flattenBatch(_tri),
    };

    final originalMj = widget.report['materials_json'];
    if (originalMj == null || originalMj.toString() != materialsJson) {
      payload['materials_json'] = materialsJson;
    }

    return payload;
  }

  void _save() {
    if (!_formKey.currentState!.validate()) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Please fix form errors before saving.'),
        backgroundColor: Colors.red,
      ));
      return;
    }
    if (_hasNegativeMaterials()) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text("Error: Material 'Stop' cannot be greater than 'Start'."),
        backgroundColor: Colors.red,
      ));
      return;
    }
    Navigator.pop(context, _buildPayload());
  }

}
