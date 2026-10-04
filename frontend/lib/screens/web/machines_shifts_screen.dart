// lib/screens/web/machines_shifts_screen.dart
// Web version of Machine & Shift Setup (tabbed, same as Android MachineShiftSetupScreen).
import 'package:flutter/material.dart';
import '../../models.dart';
import '../../app_state.dart';

class MachinesShiftsScreen extends StatefulWidget {
  final User user;
  const MachinesShiftsScreen({super.key, required this.user});
  @override State<MachinesShiftsScreen> createState() => _MachinesShiftsScreenState();
}

class _MachinesShiftsScreenState extends State<MachinesShiftsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tab;

  @override
  void initState() {
    super.initState();
    _tab = TabController(length: 2, vsync: this);
  }

  @override
  void dispose() { _tab.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      Container(
        color: Colors.white,
        child: TabBar(
          controller: _tab,
          labelColor: Colors.deepPurple,
          unselectedLabelColor: Colors.grey,
          indicatorColor: Colors.deepPurple,
          tabs: const [
            Tab(icon: Icon(Icons.precision_manufacturing), text: 'Machines'),
            Tab(icon: Icon(Icons.schedule), text: 'Shifts'),
          ],
        ),
      ),
      const Divider(height: 1),
      Expanded(child: TabBarView(controller: _tab, children: [
        _MachinesTab(onChanged: () => setState(() {})),
        _ShiftsTab(onChanged: () => setState(() {})),
      ])),
    ]);
  }
}

// ── Machines Tab ──────────────────────────────────────────────────────────────
class _MachinesTab extends StatefulWidget {
  final VoidCallback onChanged;
  const _MachinesTab({required this.onChanged});
  @override State<_MachinesTab> createState() => _MachinesTabState();
}

class _MachinesTabState extends State<_MachinesTab> {
  bool _loading = false;

  Future<void> _save() async {
    setState(() => _loading = true);
    await AppData.saveMachinesCache();
    await AppData.syncPendingSetupChanges();
    setState(() => _loading = false);
  }

  Future<void> _editMachine(Machine? m) async {
    final nameC = TextEditingController(text: m?.name ?? '');
    final remC  = TextEditingController(text: m?.remarks ?? '');
    bool inactive = m?.isInactive ?? false;

    final ok = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(builder: (ctx, setD) {
        bool _saving = false;
        return AlertDialog(
        title: Text(m == null ? 'Add Machine' : 'Edit Machine'),
        content: SizedBox(width: 380, child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: nameC,
            decoration: const InputDecoration(labelText: 'Machine Name *')),
          const SizedBox(height: 10),
          TextField(controller: remC,
            decoration: const InputDecoration(labelText: 'Remarks')),
          const SizedBox(height: 8),
          CheckboxListTile(
            title: const Text('Inactive'),
            value: inactive,
            onChanged: (v) => setD(() => inactive = v!),
            contentPadding: EdgeInsets.zero),
        ])),
        actions: [
          TextButton(
            onPressed: _saving ? null : () => Navigator.pop(ctx, false),
            child: const Text('CANCEL')),
          FilledButton(
            onPressed: _saving ? null : () async {
              if (nameC.text.trim().isEmpty) return;
              setD(() => _saving = true);
              try {
                final updated = Machine(
                  name: nameC.text.trim(),
                  remarks: remC.text.trim(),
                  isInactive: inactive);

                setState(() {
                  if (m == null) {
                    AppData.machines.add(updated);
                  } else {
                    final idx = AppData.machines.indexOf(m);
                    if (idx != -1) AppData.machines[idx] = updated;
                  }
                });
                widget.onChanged();
                await AppData.enqueueSetupChange('machine',
                  m == null ? 'add' : 'update', updated.toJson(), oldName: m?.name);
                await _save();
                if (ctx.mounted) Navigator.pop(ctx, true);
              } finally {
                if (ctx.mounted) setD(() => _saving = false);
              }
            },
            child: _saving
                ? const SizedBox(
                    width: 20, height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : Text(m == null ? 'ADD' : 'SAVE')),
        ],
      );
      }),
    );
  }

  Future<void> _deleteMachine(Machine m) async {
    bool _saving = false;
    final ok = await showDialog<bool>(context: context,
      builder: (ctx) => StatefulBuilder(builder: (ctx, setD) => AlertDialog(
        title: const Text('Delete Machine?'),
        content: Text('Delete "${m.name}"?'),
        actions: [
          TextButton(
            onPressed: _saving ? null : () => Navigator.pop(ctx, false),
            child: const Text('CANCEL')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            onPressed: _saving ? null : () async {
              setD(() => _saving = true);
              try {
                setState(() => AppData.machines.remove(m));
                widget.onChanged();
                await AppData.enqueueSetupChange('machine', 'delete', m.toJson(), oldName: m.name);
                await _save();
                if (ctx.mounted) Navigator.pop(ctx, true);
              } finally {
                if (ctx.mounted) setD(() => _saving = false);
              }
            },
            child: _saving
                ? const SizedBox(
                    width: 20, height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Text('DELETE', style: TextStyle(color: Colors.white))),
        ],
      )));
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Text('Machines', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const Spacer(),
          Text('${AppData.machines.length} machines',
            style: const TextStyle(color: Colors.grey, fontSize: 13)),
          const SizedBox(width: 12),
          FilledButton.icon(
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Add Machine'),
            onPressed: () => _editMachine(null)),
        ]),
        const SizedBox(height: 14),
        Expanded(
          child: AppData.machines.isEmpty
            ? const Center(child: Text('No machines configured'))
            : Card(
              margin: EdgeInsets.zero,
              child: SingleChildScrollView(
                child: SizedBox(
                  width: double.infinity,
                  child: DataTable(
                    showCheckboxColumn: false,
                    headingRowColor: WidgetStateProperty.all(const Color(0xFFF5F5F5)),
                    columnSpacing: 18,
                    columns: const [
                      DataColumn(label: Text('Machine Name')),
                      DataColumn(label: Text('Remarks')),
                      DataColumn(label: Text('Status')),
                      DataColumn(label: Text('Actions')),
                    ],
                    rows: AppData.machines.map((m) => DataRow(cells: [
                      DataCell(Text(m.name,
                        style: TextStyle(
                          fontWeight: FontWeight.w600,
                          color: m.isInactive ? Colors.grey : Colors.deepPurple))),
                      DataCell(Text(m.remarks.isEmpty ? '-' : m.remarks,
                        style: const TextStyle(fontSize: 13))),
                      DataCell(Chip(
                        label: Text(m.isInactive ? 'Inactive' : 'Active',
                          style: const TextStyle(fontSize: 11, color: Colors.white)),
                        backgroundColor: m.isInactive ? Colors.grey : Colors.green,
                        padding: EdgeInsets.zero,
                        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap)),
                      DataCell(Row(mainAxisSize: MainAxisSize.min, children: [
                        IconButton(
                          icon: const Icon(Icons.edit, size: 18, color: Colors.orange),
                          tooltip: 'Edit',
                          onPressed: () => _editMachine(m),
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(minWidth: 32, minHeight: 32)),
                        IconButton(
                          icon: const Icon(Icons.delete_outline, size: 18, color: Colors.red),
                          tooltip: 'Delete',
                          onPressed: () => _deleteMachine(m),
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(minWidth: 32, minHeight: 32)),
                      ])),
                    ])).toList(),
                  ),
                ),
              ),
            ),
        ),
      ]),
    );
  }
}

// ── Shifts Tab ────────────────────────────────────────────────────────────────
class _ShiftsTab extends StatefulWidget {
  final VoidCallback onChanged;
  const _ShiftsTab({required this.onChanged});
  @override State<_ShiftsTab> createState() => _ShiftsTabState();
}

class _ShiftsTabState extends State<_ShiftsTab> {
  bool _loading = false;

  Future<void> _save() async {
    setState(() => _loading = true);
    await AppData.saveShiftsCache();
    await AppData.syncPendingSetupChanges();
    setState(() => _loading = false);
  }

  Future<void> _editShift(Shift? s) async {
    final nameC  = TextEditingController(text: s?.name ?? '');
    final startC = TextEditingController(text: s?.start ?? '');
    final endC   = TextEditingController(text: s?.end ?? '');

    final ok = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(builder: (ctx, setD) {
        bool _saving = false;
        return AlertDialog(
        title: Text(s == null ? 'Add Shift' : 'Edit Shift'),
        content: SizedBox(width: 380, child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: nameC,
            decoration: const InputDecoration(labelText: 'Shift Name *')),
          const SizedBox(height: 10),
          TextField(controller: startC,
            decoration: const InputDecoration(
              labelText: 'Start Time', hintText: 'e.g. 06:00')),
          const SizedBox(height: 10),
          TextField(controller: endC,
            decoration: const InputDecoration(
              labelText: 'End Time', hintText: 'e.g. 14:00')),
        ])),
        actions: [
          TextButton(
            onPressed: _saving ? null : () => Navigator.pop(ctx, false),
            child: const Text('CANCEL')),
          FilledButton(
            onPressed: _saving ? null : () async {
              if (nameC.text.trim().isEmpty) return;
              setD(() => _saving = true);
              try {
                final updated = Shift(
                  name: nameC.text.trim(),
                  start: startC.text.trim(),
                  end: endC.text.trim());

                setState(() {
                  if (s == null) {
                    AppData.shifts.add(updated);
                  } else {
                    final idx = AppData.shifts.indexOf(s);
                    if (idx != -1) AppData.shifts[idx] = updated;
                  }
                });
                widget.onChanged();
                await AppData.enqueueSetupChange('shift',
                  s == null ? 'add' : 'update', updated.toJson(), oldName: s?.name);
                await _save();
                if (ctx.mounted) Navigator.pop(ctx, true);
              } finally {
                if (ctx.mounted) setD(() => _saving = false);
              }
            },
            child: _saving
                ? const SizedBox(
                    width: 20, height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : Text(s == null ? 'ADD' : 'SAVE')),
        ],
      );
      }),
    );
  }

  Future<void> _deleteShift(Shift s) async {
    bool _saving = false;
    final ok = await showDialog<bool>(context: context,
      builder: (ctx) => StatefulBuilder(builder: (ctx, setD) => AlertDialog(
        title: const Text('Delete Shift?'),
        content: Text('Delete "${s.name}"?'),
        actions: [
          TextButton(
            onPressed: _saving ? null : () => Navigator.pop(ctx, false),
            child: const Text('CANCEL')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            onPressed: _saving ? null : () async {
              setD(() => _saving = true);
              try {
                setState(() => AppData.shifts.remove(s));
                widget.onChanged();
                await AppData.enqueueSetupChange('shift', 'delete', s.toJson(), oldName: s.name);
                await _save();
                if (ctx.mounted) Navigator.pop(ctx, true);
              } finally {
                if (ctx.mounted) setD(() => _saving = false);
              }
            },
            child: _saving
                ? const SizedBox(
                    width: 20, height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Text('DELETE', style: TextStyle(color: Colors.white))),
        ],
      )));
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Text('Shifts', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const Spacer(),
          Text('${AppData.shifts.length} shifts',
            style: const TextStyle(color: Colors.grey, fontSize: 13)),
          const SizedBox(width: 12),
          FilledButton.icon(
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Add Shift'),
            onPressed: () => _editShift(null)),
        ]),
        const SizedBox(height: 14),
        Expanded(
          child: AppData.shifts.isEmpty
            ? const Center(child: Text('No shifts configured'))
            : Card(
              margin: EdgeInsets.zero,
              child: SingleChildScrollView(
                child: SizedBox(
                  width: double.infinity,
                  child: DataTable(
                    showCheckboxColumn: false,
                    headingRowColor: WidgetStateProperty.all(const Color(0xFFF5F5F5)),
                    columnSpacing: 18,
                    columns: const [
                      DataColumn(label: Text('Shift Name')),
                      DataColumn(label: Text('Start')),
                      DataColumn(label: Text('End')),
                      DataColumn(label: Text('Actions')),
                    ],
                    rows: AppData.shifts.map((s) => DataRow(cells: [
                      DataCell(Text(s.name,
                        style: const TextStyle(
                          fontWeight: FontWeight.w600, color: Colors.deepPurple))),
                      DataCell(Text(s.start.isEmpty ? '-' : s.start,
                        style: const TextStyle(fontSize: 13))),
                      DataCell(Text(s.end.isEmpty ? '-' : s.end,
                        style: const TextStyle(fontSize: 13))),
                      DataCell(Row(mainAxisSize: MainAxisSize.min, children: [
                        IconButton(
                          icon: const Icon(Icons.edit, size: 18, color: Colors.orange),
                          tooltip: 'Edit',
                          onPressed: () => _editShift(s),
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(minWidth: 32, minHeight: 32)),
                        IconButton(
                          icon: const Icon(Icons.delete_outline, size: 18, color: Colors.red),
                          tooltip: 'Delete',
                          onPressed: () => _deleteShift(s),
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(minWidth: 32, minHeight: 32)),
                      ])),
                    ])).toList(),
                  ),
                ),
              ),
            ),
        ),
      ]),
    );
  }
}