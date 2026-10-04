// lib/screens/web/materials_screen.dart
// Web version of the Material Dictionary management screen.
// Materials are grouped by category: Acetate → Paper → Cold Glue → HM Glue → Triacetin.
// Search bar searches across all columns: material type, category, batch, hidden status.
import 'package:flutter/material.dart';
import '../../models.dart';
import '../../app_state.dart';
import '../../api_service.dart';

class MaterialsScreen extends StatefulWidget {
  final User user;
  const MaterialsScreen({super.key, required this.user});
  @override State<MaterialsScreen> createState() => _MaterialsScreenState();
}

class _MaterialsScreenState extends State<MaterialsScreen> {
  bool _loading = false;
  String _filter = '';

  static const List<MaterialCategory> _categoryOrder = [
    MaterialCategory.acetate,
    MaterialCategory.paper,
    MaterialCategory.coldGlue,
    MaterialCategory.hotMelt,
    MaterialCategory.triacetin,
  ];

  static String _categoryDisplayName(MaterialCategory cat) {
    switch (cat) {
      case MaterialCategory.acetate: return 'Acetate';
      case MaterialCategory.paper: return 'Paper';
      case MaterialCategory.coldGlue: return 'Cold Glue';
      case MaterialCategory.hotMelt: return 'HM Glue';
      case MaterialCategory.triacetin: return 'Triacetin';
    }
  }

  static Color _categoryColor(MaterialCategory cat) {
    switch (cat) {
      case MaterialCategory.acetate: return const Color(0xFF673AB7);
      case MaterialCategory.paper: return const Color(0xFF009688);
      case MaterialCategory.coldGlue: return const Color(0xFF2196F3);
      case MaterialCategory.hotMelt: return const Color(0xFFFF9800);
      case MaterialCategory.triacetin: return const Color(0xFFE91E63);
    }
  }

  bool _matchesAll(RawMaterial m, String q) {
    if (q.isEmpty) return true;
    final lq = q.toLowerCase();
    return m.type.toLowerCase().contains(lq) ||
        _categoryDisplayName(m.category).toLowerCase().contains(lq) ||
        (m.batch ?? '').toLowerCase().contains(lq) ||
        (m.isHidden ? 'hidden' : 'visible').contains(lq) ||
        m.category.name.toLowerCase().contains(lq);
  }

  List<RawMaterial> get _filtered => AppData.materialDictionary
      .where((m) => _matchesAll(m, _filter))
      .toList();

  Future<void> _refresh() async {
    setState(() => _loading = true);
    await AppData.loadDataFromServer(forceSync: true);
    setState(() => _loading = false);
  }

  Future<void> _showDialog(RawMaterial? existing) async {
    final typeC  = TextEditingController(text: existing?.type ?? '');
    final batchC = TextEditingController(text: existing?.batch ?? '');
    MaterialCategory cat = existing?.category ?? MaterialCategory.acetate;
    bool hidden = existing?.isHidden ?? false;

    final ok = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(builder: (ctx, setD) {
        bool _saving = false;
        return AlertDialog(
        title: Text(existing == null ? 'Add Material' : 'Edit Material'),
        content: SizedBox(width: 400, child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: typeC,
            decoration: const InputDecoration(labelText: 'Material Type Name *')),
          const SizedBox(height: 12),
          DropdownButtonFormField<MaterialCategory>(
            initialValue: cat,
            decoration: const InputDecoration(labelText: 'Category'),
            items: MaterialCategory.values.map((c) =>
              DropdownMenuItem(value: c, child: Text(_categoryDisplayName(c)))).toList(),
            onChanged: (v) => setD(() => cat = v!)),
          const SizedBox(height: 12),
          TextField(controller: batchC,
            decoration: const InputDecoration(labelText: 'Default Batch')),
          const SizedBox(height: 8),
          CheckboxListTile(
            title: const Text('Hidden from operators'),
            value: hidden,
            onChanged: (v) => setD(() => hidden = v!),
            contentPadding: EdgeInsets.zero),
        ])),
        actions: [
          TextButton(
            onPressed: _saving ? null : () => Navigator.pop(ctx, false),
            child: const Text('CANCEL')),
          FilledButton(
            onPressed: _saving ? null : () async {
              if (typeC.text.trim().isEmpty) return;
              setD(() => _saving = true);
              try {
                final item = RawMaterial(
                  type: typeC.text.trim(),
                  category: cat,
                  batch: batchC.text.trim(),
                  isHidden: hidden,
                );

                bool success;
                if (existing == null) {
                  success = await ApiService.addMaterial(item);
                } else {
                  success = await ApiService.updateMaterial(existing.type, item);
                }
                if (success) await AppData.loadDataFromServer(forceSync: true);
                setState(() => _loading = false);
                if (ctx.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text(success ? 'Saved successfully' : 'Error saving material'),
                    backgroundColor: success ? Colors.green : Colors.red));
                  Navigator.pop(ctx, success);
                }
              } finally {
                if (ctx.mounted) setD(() => _saving = false);
              }
            },
            child: _saving
                ? const SizedBox(
                    width: 20, height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : Text(existing == null ? 'ADD' : 'SAVE')),
        ],
      );
      }),
    );
  }

  Future<void> _delete(RawMaterial m) async {
    bool _saving = false;
    final ok = await showDialog<bool>(context: context,
      builder: (ctx) => StatefulBuilder(builder: (ctx, setD) => AlertDialog(
        title: const Text('Delete Material?'),
        content: Text('Delete "${m.type}"? This cannot be undone.'),
        actions: [
          TextButton(
            onPressed: _saving ? null : () => Navigator.pop(ctx, false),
            child: const Text('CANCEL')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            onPressed: _saving ? null : () async {
              setD(() => _saving = true);
              try {
                setState(() => _loading = true);
                final success = await ApiService.deleteMaterial(m.type);
                if (success) await AppData.loadDataFromServer(forceSync: true);
                setState(() => _loading = false);
                if (ctx.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text(success ? 'Deleted' : 'Delete failed'),
                    backgroundColor: success ? Colors.green : Colors.red));
                  Navigator.pop(ctx, success);
                }
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

  Widget _buildCategorySection(MaterialCategory cat, List<RawMaterial> items) {
    final displayName = _categoryDisplayName(cat);
    final color = _categoryColor(cat);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 16, bottom: 8),
          child: Row(children: [
            Container(
              width: 4, height: 20,
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 8),
            Text(
              '$displayName (${items.length})',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.bold,
                color: color,
              ),
            ),
          ]),
        ),
        Card(
          margin: EdgeInsets.zero,
          child: DataTable(
            showCheckboxColumn: false,
            headingRowColor: WidgetStateProperty.all(Colors.grey.shade50),
            columnSpacing: 18,
            columns: const [
              DataColumn(label: Text('Material Type')),
              DataColumn(label: Text('Default Batch')),
              DataColumn(label: Text('Hidden')),
              DataColumn(label: Text('Actions')),
            ],
            rows: items.map((m) => DataRow(cells: [
              DataCell(Text(m.type,
                style: TextStyle(
                  fontWeight: FontWeight.w600,
                  color: m.isHidden ? Colors.grey : Colors.deepPurple))),
              DataCell(Text((m.batch?.isEmpty ?? true) ? '-' : m.batch!,
                style: const TextStyle(fontSize: 13))),
              DataCell(Icon(
                m.isHidden ? Icons.visibility_off : Icons.visibility,
                size: 18,
                color: m.isHidden ? Colors.grey : Colors.green)),
              DataCell(Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(
                  icon: const Icon(Icons.edit, size: 18, color: Colors.orange),
                  tooltip: 'Edit',
                  onPressed: () => _showDialog(m),
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(minWidth: 32, minHeight: 32)),
                IconButton(
                  icon: const Icon(Icons.delete_outline, size: 18, color: Colors.red),
                  tooltip: 'Delete',
                  onPressed: () => _delete(m),
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(minWidth: 32, minHeight: 32)),
              ])),
            ])).toList(),
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    // Build category-grouped sections from the filtered list
    final grouped = <MaterialCategory, List<RawMaterial>>{};
    for (final m in _filtered) {
      grouped.putIfAbsent(m.category, () => []).add(m);
    }

    final categoryWidgets = <Widget>[];
    for (final cat in _categoryOrder) {
      final items = grouped[cat] ?? [];
      if (items.isEmpty && _filter.isNotEmpty) continue; // Skip empty cats when filtering
      categoryWidgets.add(_buildCategorySection(cat, items));
    }

    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          SizedBox(width: 280,
            child: TextField(
              decoration: const InputDecoration(
                hintText: 'Search all columns...',
                prefixIcon: Icon(Icons.search), isDense: true),
              onChanged: (v) => setState(() => _filter = v))),
          const Spacer(),
          Text('${_filtered.length} materials',
            style: const TextStyle(color: Colors.grey, fontSize: 13)),
          const SizedBox(width: 12),
          OutlinedButton.icon(
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Add Material'),
            onPressed: () => _showDialog(null)),
          const SizedBox(width: 8),
          FilledButton.icon(
            icon: _loading
              ? const SizedBox(width: 16, height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.refresh, size: 18),
            label: const Text('Refresh'),
            onPressed: _loading ? null : _refresh),
        ]),
        const SizedBox(height: 14),
        Expanded(
          child: _filtered.isEmpty && _filter.isNotEmpty
            ? const Center(child: Text('No materials match your search'))
            : SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: categoryWidgets,
              ),
            ),
        ),
      ]),
    );
  }
}