import 'package:flutter/material.dart';
import '../../models.dart';
import '../../app_state.dart';

class MachineShiftSetupScreen extends StatefulWidget {
  const MachineShiftSetupScreen({super.key});
  @override State<MachineShiftSetupScreen> createState() => _MachineShiftSetupScreenState();
}

class _MachineShiftSetupScreenState extends State<MachineShiftSetupScreen> {
  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text("Machines & Shifts"), 
          backgroundColor: Colors.blueGrey[800],
          foregroundColor: Colors.white,
          bottom: const TabBar(
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white70,
            tabs: [Tab(text: "MACHINES"), Tab(text: "SHIFTS")]
          )
        ),
        body: TabBarView(children: [_buildMachineTab(), _buildShiftTab()]),
      ),
    );
  }

  // --- ТАБ СТАНКОВ ---
  Widget _buildMachineTab() {
    return Scaffold(
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: AppData.machines.length,
        itemBuilder: (ctx, i) {
          final m = AppData.machines[i];
          return Card(
            color: m.isInactive ? Colors.grey[200] : Colors.white,
            child: ListTile(
              title: Text(m.name, style: const TextStyle(fontWeight: FontWeight.bold)),
              subtitle: Text(m.remarks),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(icon: const Icon(Icons.edit, color: Colors.blue), onPressed: () => _editMachine(m)),
                IconButton(
                  icon: const Icon(Icons.delete, color: Colors.red),
                  onPressed: () async {
                    setState(() => AppData.machines.remove(m));
                    await AppData.saveMachinesCache();
                    await AppData.enqueueSetupChange('machine', 'delete', m.toJson(), oldName: m.name);
                    bool synced = await AppData.syncPendingSetupChanges();
                    if (!synced && mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text("Deleted locally, will sync when online"),
                          backgroundColor: Colors.orange,
                        ),
                      );
                    }
                  },
                ),
              ]),
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _editMachine(null), 
        backgroundColor: Colors.blueGrey[800],
        child: const Icon(Icons.add, color: Colors.white)
      ),
    );
  }

  void _editMachine(Machine? m) {
    final nameC = TextEditingController(text: m?.name ?? "");
    final remC = TextEditingController(text: m?.remarks ?? "");
    bool inactive = m?.isInactive ?? false;

    showDialog(context: context, builder: (ctx) => StatefulBuilder(builder: (ctx, setS) {
      bool _saving = false;
      return AlertDialog(
      title: Text(m == null ? "Add Machine" : "Edit Machine"),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: nameC, decoration: const InputDecoration(labelText: "Machine Name")),
        TextField(controller: remC, decoration: const InputDecoration(labelText: "Remarks")),
        CheckboxListTile(title: const Text("Is Inactive"), value: inactive, onChanged: (v) => setS(() => inactive = v!)),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text("CANCEL")),
        ElevatedButton(
          onPressed: _saving ? null : () async {
            if (nameC.text.isEmpty) return;
            setS(() => _saving = true);
            try {
              final updatedMachine = Machine(
                name: nameC.text,
                remarks: remC.text,
                isInactive: inactive,
              );

              String? oldName;
              setState(() {
                if (m == null) {
                  AppData.machines.add(updatedMachine);
                } else {
                  oldName = m.name;
                  m.name = nameC.text;
                  m.remarks = remC.text;
                  m.isInactive = inactive;
                }
              });

              await AppData.saveMachinesCache();
              await AppData.enqueueSetupChange('machine', m == null ? 'add' : 'update', updatedMachine.toJson(), oldName: oldName);
              bool synced = await AppData.syncPendingSetupChanges();

              if (ctx.mounted) Navigator.pop(ctx);
              if (!synced && mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text("Machine saved locally, will sync when online"),
                    backgroundColor: Colors.orange,
                  ),
                );
              }
            } finally {
              if (ctx.mounted) setS(() => _saving = false);
            }
          }, 
          child: _saving
              ? const SizedBox(
                  width: 20, height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                )
              : const Text("SAVE"),
        ),
      ],
    );
    }));
  }

  // --- ТАБ СМЕН ---
  Widget _buildShiftTab() {
    return Scaffold(
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: AppData.shifts.length,
        itemBuilder: (ctx, i) {
          final s = AppData.shifts[i];
          return Card(
            child: ListTile(
              title: Text(s.name, style: const TextStyle(fontWeight: FontWeight.bold)),
              subtitle: Text("${s.start} - ${s.end}"),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(icon: const Icon(Icons.edit, color: Colors.blue), onPressed: () => _editShift(s)),
                IconButton(
                  icon: const Icon(Icons.delete, color: Colors.red),
                  onPressed: () async {
                    setState(() => AppData.shifts.remove(s));
                    await AppData.saveShiftsCache();
                    await AppData.enqueueSetupChange('shift', 'delete', s.toJson(), oldName: s.name);
                    bool synced = await AppData.syncPendingSetupChanges();
                    if (!synced && mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text("Deleted locally, will sync when online"),
                          backgroundColor: Colors.orange,
                        ),
                      );
                    }
                  },
                ),
              ]),
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _editShift(null), 
        backgroundColor: Colors.blueGrey[800],
        child: const Icon(Icons.add, color: Colors.white)
      ),
    );
  }

  void _editShift(Shift? s) {
    final nameC = TextEditingController(text: s?.name ?? "");
    final startC = TextEditingController(text: s?.start ?? "00:00");
    final endC = TextEditingController(text: s?.end ?? "00:00");

    showDialog(context: context, builder: (ctx) => StatefulBuilder(builder: (ctx, setS) {
      bool _saving = false;
      return AlertDialog(
      title: Text(s == null ? "Add Shift" : "Edit Shift"),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: nameC, decoration: const InputDecoration(labelText: "Shift Name")),
        TextField(controller: startC, decoration: const InputDecoration(hintText: "Start HH:mm")),
        TextField(controller: endC, decoration: const InputDecoration(hintText: "End HH:mm")),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text("CANCEL")),
        ElevatedButton(
          onPressed: _saving ? null : () async {
            if (nameC.text.isEmpty) return;

            if (_checkOverlap(startC.text, endC.text, s)) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text("Error: Shifts overlap!"), backgroundColor: Colors.red)
              );
              return;
            }
            setS(() => _saving = true);
            try {
              final updatedShift = Shift(name: nameC.text, start: startC.text, end: endC.text);
              String? oldName;

              setState(() {
                if (s == null) {
                  AppData.shifts.add(updatedShift);
                } else {
                  oldName = s.name;
                  s.name = nameC.text;
                  s.start = startC.text;
                  s.end = endC.text;
                }
              });

              await AppData.saveShiftsCache();
              await AppData.enqueueSetupChange('shift', s == null ? 'add' : 'update', updatedShift.toJson(), oldName: oldName);
              bool synced = await AppData.syncPendingSetupChanges();

              if (ctx.mounted) Navigator.pop(ctx);
              if (!synced && mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text("Shift saved locally, will sync when online"),
                    backgroundColor: Colors.orange,
                  ),
                );
              }
            } finally {
              if (ctx.mounted) setS(() => _saving = false);
            }
          }, 
          child: _saving
              ? const SizedBox(
                  width: 20, height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                )
              : const Text("SAVE"),
        ),
      ],
    );
    }));
  }

  bool _checkOverlap(String start, String end, Shift? current) {
    int newS = _toMin(start);
    int newE = _toMin(end);

    List<List<int>> getIntervals(int s, int e) {
      if (s < e) return [[s, e]]; 
      return [[s, 1440], [0, e]]; 
    }

    var newIntervals = getIntervals(newS, newE);

    for (var s in AppData.shifts) {
      if (s == current) continue;
      int sS = _toMin(s.start);
      int sE = _toMin(s.end);
      var existingIntervals = getIntervals(sS, sE);

      for (var nI in newIntervals) {
        for (var eI in existingIntervals) {
          if (nI[0] < eI[1] && nI[1] > eI[0]) return true; 
        }
      }
    }
    return false;
  }

  int _toMin(String t) {
    var p = t.split(':'); 
    return int.parse(p[0]) * 60 + int.parse(p[1]);
  }
}