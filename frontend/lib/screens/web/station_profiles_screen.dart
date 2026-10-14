// lib/screens/web/station_profiles_screen.dart
// Settings -> Quality Stations: manage station_profiles + their push-mode API keys.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../api_service.dart';
import '../../core/csv_column_mapper.dart';
import '../../core/download_bytes.dart';
import '../../core/pick_text_file.dart';

class StationProfilesScreen extends StatefulWidget {
  const StationProfilesScreen({super.key});
  @override
  State<StationProfilesScreen> createState() => _StationProfilesScreenState();
}

class _StationProfilesScreenState extends State<StationProfilesScreen> {
  List<Map<String, dynamic>> _profiles = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final r = await ApiService.fetchStationProfiles();
    if (!mounted) return;
    setState(() {
      _profiles =
          (r ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
      _loading = false;
      if (r == null) _error = ApiService.lastApiDetail;
    });
  }

  Future<void> _openDialog([Map<String, dynamic>? existing]) async {
    final changed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => _StationProfileDialog(existing: existing),
    );
    if (changed == true) _load();
  }

  Future<void> _delete(Map<String, dynamic> p) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete station?'),
        content: Text('Delete "${p['label'] ?? p['match_value']}" and revoke its key?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Delete', style: TextStyle(color: Colors.red))),
        ],
      ),
    );
    if (ok != true) return;
    final success = await ApiService.deleteStationProfile(p['id']);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(success ? 'Station deleted' : 'Failed to delete station')));
    if (success) _load();
  }

  bool _hasActiveKey(Map<String, dynamic> p) {
    final key = (p['key'] as Map?)?.cast<String, dynamic>();
    return key?['is_active'] == true;
  }

  String _formatLastUsed(dynamic iso) {
    if (iso is! String || iso.isEmpty) return 'Never used';
    final dt = DateTime.tryParse(iso);
    if (dt == null) return 'Never used';
    final local = dt.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${local.year}-${two(local.month)}-${two(local.day)} '
        '${two(local.hour)}:${two(local.minute)}';
  }

  Future<void> _revokeKey(Map<String, dynamic> p) async {
    final proceed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Revoke station key?'),
        content: const Text(
            'The station will immediately lose upload access until a new key is generated.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Revoke')),
        ],
      ),
    );
    if (proceed != true) return;

    final ok = await ApiService.revokeStationKey(p['id']);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(ok ? 'Key revoked' : 'Failed to revoke key')));
    if (ok) _load();
  }

  Future<void> _generateKey(Map<String, dynamic> p) async {
    final proceed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Generate new key?'),
        content: Text(_hasActiveKey(p)
            ? 'This replaces the current key. Any agent using the old key will stop uploading.'
            : 'A new station key will be generated and shown once.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Generate')),
        ],
      ),
    );
    if (proceed != true) return;

    final r = await ApiService.generateStationKey(p['id']);
    if (!mounted) return;
    if (r != null && r['plaintext_key'] is String) {
      await _showKeyDialog(r['plaintext_key'] as String);
      _load();
    } else {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Failed to generate key')));
    }
  }

  Future<void> _downloadBundle(Map<String, dynamic> p) async {
    final label = (p['label'] ?? p['match_value'] ?? 'station').toString();
    final proceed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Download agent bundle?'),
        content: Text(_hasActiveKey(p)
            ? 'Downloading generates a NEW station key for "$label" and revokes the '
                'current one. Any agent already running with the old key will stop '
                'uploading until you install this new bundle.'
            : 'A fresh station key will be generated and bundled into the ZIP for "$label".'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Download')),
        ],
      ),
    );
    if (proceed != true) return;

    final bytes = await ApiService.downloadStationAgentBundle(p['id']);
    if (!mounted) return;
    if (bytes == null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(
              'Failed to download bundle: ${ApiService.lastApiDetail ?? 'unknown error'}')));
      return;
    }
    final safe = label.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_');
    downloadBytes(bytes, 'station_agent_$safe.zip');
  }

  Future<void> _showKeyDialog(String key) => showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Station API key'),
          content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Copy this key now — it will not be shown again.'),
                const SizedBox(height: 12),
                SelectableText(key,
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
              ]),
          actions: [
            TextButton(
                onPressed: () => Clipboard.setData(ClipboardData(text: key)),
                child: const Text('Copy')),
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Done')),
          ],
        ),
      );

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Text('Quality Stations',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          const Spacer(),
          FilledButton.icon(
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Add Station'),
            onPressed: _loading ? null : () => _openDialog(),
          ),
        ]),
        const SizedBox(height: 16),
        if (_loading)
          const Center(child: CircularProgressIndicator())
        else if (_error != null)
          Text('Failed to load stations: $_error',
              style: const TextStyle(color: Colors.red))
        else if (_profiles.isEmpty)
          const Text('No stations configured yet.')
        else
          _buildTable(),
      ]),
    );
  }

  Widget _buildTable() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: DataTable(
          columnSpacing: 24,
          columns: const [
            DataColumn(label: Text('Station')),
            DataColumn(label: Text('Match')),
            DataColumn(label: Text('Mode')),
            DataColumn(label: Text('API Key')),
            DataColumn(label: Text('Actions')),
          ],
          rows: _profiles.map((p) {
            final key = (p['key'] as Map?)?.cast<String, dynamic>();
            final active = key?['is_active'] == true;
            return DataRow(cells: [
              DataCell(Text(p['label']?.toString() ?? p['match_value']?.toString() ?? '—')),
              DataCell(Text('${p['match_key']} = ${p['match_value']}')),
              DataCell(Text(p['delivery_mode'] == 'pull' ? 'Pull' : 'Push')),
              DataCell(key == null
                  ? const Text('—')
                  : Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('${active ? '●' : '○'} ${key['prefix']}'),
                        Text(
                          _formatLastUsed(key['last_used_at']),
                          style: const TextStyle(fontSize: 11, color: Colors.grey),
                        ),
                      ],
                    )),
              DataCell(Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(
                    icon: const Icon(Icons.archive_outlined, size: 18, color: Colors.blue),
                    tooltip: 'Download Agent Bundle (ZIP)',
                    onPressed: () => _downloadBundle(p)),
                IconButton(
                    icon: const Icon(Icons.edit, size: 18),
                    tooltip: 'Edit',
                    onPressed: () => _openDialog(p)),
                IconButton(
                    icon: const Icon(Icons.key, size: 18, color: Colors.green),
                    tooltip: 'Generate key',
                    onPressed: () => _generateKey(p)),
                IconButton(
                    icon: const Icon(Icons.key_off, size: 18, color: Colors.orange),
                    tooltip: 'Revoke key',
                    onPressed: key == null ? null : () => _revokeKey(p)),
                IconButton(
                    icon: const Icon(Icons.delete_outline, size: 18, color: Colors.red),
                    tooltip: 'Delete',
                    onPressed: () => _delete(p)),
              ])),
            ]);
          }).toList(),
        ),
      ),
    );
  }
}


// ---------------------------------------------------------------------------
// Add / Edit dialog
// ---------------------------------------------------------------------------

const _matchKeys = ['instrument_id', 'maker', 'team'];
const _moFields = ['batch_description', 'comments', 'brand'];
const _encodings = ['utf-8', 'cp1251', 'cp1252', 'latin-1'];
const _columnFields = [
  'rod_no', 'pd', 'weight', 'diameter', 'ovality', 'roundness', 'shape', 'hardness'
];
const _columnLabels = {
  'rod_no': 'Rod Number Index',
  'pd': 'Pressure Drop (PD) Index',
  'weight': 'Weight Index',
  'diameter': 'Diameter Index',
  'ovality': 'Ovality Index',
  'roundness': 'Roundness Index',
  'shape': 'Shape Index',
  'hardness': 'Hardness Index',
};

class _StationProfileDialog extends StatefulWidget {
  final Map<String, dynamic>? existing;
  const _StationProfileDialog({this.existing});
  @override
  State<_StationProfileDialog> createState() => _StationProfileDialogState();
}

class _StationProfileDialogState extends State<_StationProfileDialog> {
  late final Map<String, dynamic> _e;
  late final TextEditingController _label;
  late final TextEditingController _matchValue;
  late final TextEditingController _dataStartRow;
  late final TextEditingController _watchPath;
  late final Map<String, TextEditingController> _col;
  String _matchKey = 'instrument_id';
  String _moField = 'batch_description';
  String _encoding = 'utf-8';
  String _mode = 'push';
  bool _genKeyOnSave = false;
  bool _saving = false;

  bool get _isEdit => _e['id'] != null;

  @override
  void initState() {
    super.initState();
    _e = (widget.existing ?? {}).cast<String, dynamic>();
    _label = TextEditingController(text: _e['label'] ?? '');
    _matchValue = TextEditingController(text: _e['match_value'] ?? '');
    _dataStartRow = TextEditingController(text: _e['data_start_row']?.toString() ?? '');
    _watchPath = TextEditingController(text: _e['watch_path'] ?? '');
    _matchKey = _e['match_key'] ?? 'instrument_id';
    _moField = _e['mo_field'] ?? 'batch_description';
    _encoding = _e['encoding'] ?? 'utf-8';
    _mode = _e['delivery_mode'] ?? 'push';
    final cm = (_e['column_map'] as Map?)?.cast<String, dynamic>() ?? {};
    _col = {
      for (final f in _columnFields)
        f: TextEditingController(text: cm[f]?.toString() ?? ''),
    };
  }

  @override
  void dispose() {
    for (final c in [_label, _matchValue, _dataStartRow, _watchPath, ..._col.values]) {
      c.dispose();
    }
    super.dispose();
  }

  Map<String, dynamic> _payload() {
    final cm = <String, dynamic>{};
    for (final f in _columnFields) {
      final t = _col[f]!.text.trim();
      cm[f] = t.isEmpty ? null : int.tryParse(t);
    }
    return {
      'label': _label.text.trim(),
      'match_key': _matchKey,
      'match_value': _matchValue.text.trim(),
      'mo_field': _moField,
      'data_start_row':
          _dataStartRow.text.trim().isEmpty ? null : int.tryParse(_dataStartRow.text.trim()),
      'encoding': _encoding,
      'delivery_mode': _mode,
      'watch_path': _watchPath.text.trim(),
      'generate_key': _genKeyOnSave,
      'column_map': cm,
    };
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    final id = _e['id'];
    final r =
        await ApiService.saveStationProfile(_payload(), id: id is int ? id : null);
    if (!mounted) return;
    setState(() => _saving = false);
    if (r == null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Failed to save: ${ApiService.lastApiDetail ?? 'unknown error'}')));
      return;
    }
    final plain = r['plaintext_key'];
    if (plain is String && plain.isNotEmpty) {
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Station API key'),
          content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Copy this key now — it will not be shown again.'),
                const SizedBox(height: 12),
                SelectableText(plain,
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
              ]),
          actions: [
            TextButton(
                onPressed: () => Clipboard.setData(ClipboardData(text: plain)),
                child: const Text('Copy')),
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Done')),
          ],
        ),
      );
    }
    if (mounted) Navigator.pop(context, true);
  }

  Future<void> _uploadSampleCsv() async {
    final text = await pickTextFile();
    if (text == null || text.isEmpty) return;
    final startRow = int.tryParse(_dataStartRow.text.trim());
    final headerIdx = findHeaderRow(text, startRow);
    if (headerIdx == null) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Could not find a column header row in the sample file.')));
      return;
    }
    final lines = text.split(RegExp(r'\r?\n'));
    final mapping = mapHeaderToColumns(lines[headerIdx].split(',').toList());
    if (mapping.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('No recognizable columns found in the header row.')));
      return;
    }
    setState(() {
      for (final e in mapping.entries) {
        _col[e.key]?.text = e.value.toString();
      }
    });
    if (!mounted) return;
    final summary = mapping.entries.map((e) => '${e.key}=${e.value}').join(', ');
    ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Mapped ${mapping.length} columns: $summary')));
  }

  Widget _indexField(String field) {
    return SizedBox(
      width: 120,
      child: TextField(
        controller: _col[field],
        keyboardType: TextInputType.number,
        textAlign: TextAlign.center,
        decoration: const InputDecoration(
          hintText: 'empty = off',
          isDense: true,
        ),
      ),
    );
  }

  Widget _mapRow(String field) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Expanded(child: Text(_columnLabels[field] ?? field, style: const TextStyle(fontSize: 13))),
        const SizedBox(width: 12),
        _indexField(field),
      ]),
    );
  }

  Widget _field(String label, Widget child) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: Theme.of(context).colorScheme.onSurfaceVariant)),
        const SizedBox(height: 6),
        child,
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(_isEdit ? 'Edit Station' : 'Add Station'),
      content: SizedBox(
        width: 560,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('General', style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              _field(
                'Station Name / Label',
                TextField(
                  controller: _label,
                  decoration: const InputDecoration(hintText: 'e.g. Line 1 — Quantum Neo'),
                ),
              ),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(
                  child: _field(
                    'Match Key',
                    DropdownButtonFormField<String>(
                      initialValue: _matchKey,
                      items: [for (final k in _matchKeys) DropdownMenuItem(value: k, child: Text(k))],
                      onChanged: (v) => setState(() => _matchKey = v!),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _field(
                    'Match Value',
                    TextField(
                      controller: _matchValue,
                      decoration: const InputDecoration(hintText: 'e.g. QN-01 / M1'),
                    ),
                  ),
                ),
              ]),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(
                  child: _field(
                    'MO Field',
                    DropdownButtonFormField<String>(
                      initialValue: _moField,
                      items: [for (final m in _moFields) DropdownMenuItem(value: m, child: Text(m))],
                      onChanged: (v) => setState(() => _moField = v!),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _field(
                    'Data Start Row',
                    TextField(
                      controller: _dataStartRow,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(hintText: 'e.g. 18'),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _field(
                    'Encoding',
                    DropdownButtonFormField<String>(
                      initialValue: _encoding,
                      items: [for (final e in _encodings) DropdownMenuItem(value: e, child: Text(e))],
                      onChanged: (v) => setState(() => _encoding = v!),
                    ),
                  ),
                ),
              ]),
              const SizedBox(height: 16),
              const Text('Delivery & Authentication',
                  style: TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'push', label: Text('Push (Agent)')),
                  ButtonSegment(value: 'pull', label: Text('Pull (Network Share)')),
                ],
                selected: {_mode},
                onSelectionChanged: (s) => setState(() => _mode = s.first),
              ),
              const SizedBox(height: 10),
              if (_mode == 'push')
                Row(children: [
                  const Icon(Icons.key, size: 18, color: Colors.green),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(_isEdit
                        ? 'Key management is available from the station list.'
                        : 'A station key can be generated on save.'),
                  ),
                ])
              else
                _field(
                  'Network folder path',
                  TextField(
                    controller: _watchPath,
                    decoration: const InputDecoration(hintText: 'UNC network path'),
                  ),
                ),
              if (!_isEdit && _mode == 'push') ...[
                const SizedBox(height: 8),
                CheckboxListTile(
                  value: _genKeyOnSave,
                  onChanged: (v) => setState(() => _genKeyOnSave = v ?? false),
                  title: const Text('Generate station key on save'),
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                ),
              ],
              const SizedBox(height: 16),
              Row(children: [
                const Expanded(
                    child: Text('Column Mapping',
                        style: TextStyle(fontWeight: FontWeight.bold))),
                TextButton.icon(
                  onPressed: _uploadSampleCsv,
                  icon: const Icon(Icons.upload_file, size: 18),
                  label: const Text('Upload Sample CSV'),
                ),
              ]),
              const SizedBox(height: 12),
              Text('Leave a column index blank to disable that measurement.',
                  style: TextStyle(
                      fontSize: 11,
                      color: Theme.of(context).colorScheme.onSurfaceVariant)),
              const SizedBox(height: 10),
              Text('Core Parameters',
                  style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: Theme.of(context).colorScheme.primary)),
              const SizedBox(height: 4),
              _mapRow('rod_no'),
              _mapRow('pd'),
              _mapRow('diameter'),
              _mapRow('weight'),
              const SizedBox(height: 8),
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                dense: true,
                title: const Text('Secondary / Geometry',
                    style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                children: [
                  _mapRow('hardness'),
                  _mapRow('ovality'),
                  _mapRow('roundness'),
                  _mapRow('shape'),
                ],
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel')),
        FilledButton(
          onPressed: _saving ? null : _save,
          child: Text(_saving ? 'Saving…' : 'Save'),
        ),
      ],
    );
  }
}


