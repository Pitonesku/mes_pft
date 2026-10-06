// lib/screens/web/quality_control_screen.dart
// Full-page Quality Control module: filters, KPI strip, control charts and
// a paginated measurements table.
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../api_service.dart';
import '../../core/app_navigation.dart';
import '../../widgets/quality_control_chart.dart';
import '../../widgets/quality_report_dialog.dart';

class QualityControlScreen extends StatefulWidget {
  final QualityRequest? initial;
  const QualityControlScreen({super.key, this.initial});
  @override
  State<QualityControlScreen> createState() => _QualityControlScreenState();
}

class _QualityControlScreenState extends State<QualityControlScreen> {
  String _machine = 'all';
  int? _poId;
  int? _shiftId;
  String _window = 'rods';
  int _windowValue = 50;
  int _page = 1;
  String _chartTab = '';
  bool _showOutliers = false;
  String? _initialPo;

  List<dynamic> _machines = [];
  List<dynamic> _pos = [];
  List<dynamic> _shifts = [];
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    final i = widget.initial;
    if (i != null) {
      _machine = i.machine ?? 'all';
      _shiftId = i.shiftId;
      _poId = i.poId;
      _initialPo = i.po;
    }
    _loadFilters();
  }

  Future<void> _loadFilters() async {
    final f = await ApiService.fetchQualityFilters();
    if (!mounted) return;
    setState(() {
      _machines = (f?['machines'] as List<dynamic>?) ?? [];
      _pos = (f?['pos'] as List<dynamic>?) ?? [];
      _shifts = (f?['shifts'] as List<dynamic>?) ?? [];
      if (_initialPo != null && _poId == null) {
        for (final p in _pos) {
          if (p['po_number'] == _initialPo) {
            _poId = p['id'] as int;
            break;
          }
        }
      }
    });
    _load();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    final d = await ApiService.fetchQualityData(
      machine: _machine,
      poId: _poId,
      shiftId: _window == 'po' ? null : _shiftId,
      window: _window,
      windowValue: _windowValue,
      page: _page,
      pageSize: 50,
    );
    if (!mounted) return;
    setState(() {
      _data = d;
      _loading = false;
      _error = d == null ? 'No data from server' : null;
      final ms = (d?['active_machines'] as List<dynamic>?) ?? [];
      if (ms.isNotEmpty && !ms.contains(_chartTab)) _chartTab = ms.first.toString();
      if (ms.isEmpty) _chartTab = '';
    });
  }

  void _reset() {
    setState(() { _machine = 'all'; _poId = null; _shiftId = null; _window = 'rods'; _windowValue = 50; _page = 1; });
    _load();
  }

  int? _machineId(String name) {
    for (final m in _machines) {
      if (m['name'] == name) return m['id'] as int;
    }
    return null;
  }

  List<dynamic> get _filteredShifts {
    var list = _shifts;
    final mid = _machineId(_machine);
    if (mid != null) list = list.where((s) => s['machine_id'] == mid).toList();
    if (_poId != null) {
      list = list.where((s) => ((s['po_ids'] as List<dynamic>?) ?? const []).contains(_poId)).toList();
    }
    return list;
  }

  void _setMachine(String m) {
    setState(() {
      _machine = m;
      _page = 1;
      final valid = _filteredShifts.any((s) => s['id'] == _shiftId);
      if (_shiftId != null && !valid) _shiftId = null;
    });
    _load();
  }

  void _setPo(int? id) {
    setState(() {
      _poId = id;
      _page = 1;
      final list = _filteredShifts;
      _shiftId = (id != null && list.isNotEmpty) ? (list.first['id'] as int) : null;
    });
    _load();
  }

  void _setShift(int? id) { setState(() { _shiftId = id; _page = 1; }); _load(); }
  void _setWindow(String w, int v) { setState(() { _window = w; _windowValue = v; _page = 1; }); _load(); }
  void _setPage(int p) { setState(() => _page = p); _load(); }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _filterBar(),
        const SizedBox(height: 16),
        if (_error != null) ...[
          Text(_error!, style: const TextStyle(color: Colors.red, fontSize: 13)),
          const SizedBox(height: 8),
        ],
        _kpiStrip(),
        const SizedBox(height: 16),
        Expanded(child: _split()),
      ]),
    );
  }

  // ── Filter bar ────────────────────────────────────────────────────────────
  Widget _filterBar() {
    return Wrap(spacing: 12, runSpacing: 10, crossAxisAlignment: WrapCrossAlignment.center, children: [
      _machinePills(),
      _poDropdown(),
      _shiftDropdown(),
      _windowChips(),
      IconButton(tooltip: 'Reset filters', onPressed: _reset, icon: const Icon(Icons.refresh)),
    ]);
  }

  Widget _machinePills() {
    final opts = <String>['all', ..._machines.map((m) => m['name'].toString())];
    return Wrap(spacing: 6, children: [
      for (final m in opts)
        ChoiceChip(
          label: Text(m == 'all' ? 'All' : m),
          selected: _machine == m,
          onSelected: (_) => _setMachine(m),
          showCheckmark: false,
        ),
    ]);
  }

  Widget _poDropdown() {
    return _dropdown<int?>(
      value: _poId,
      hint: 'PO',
      items: [null, ..._pos.map((p) => p['id'] as int)],
      label: (id) => id == null ? 'All POs' : (_pos.firstWhere((p) => p['id'] == id, orElse: () => {'po_number': '#$id'})['po_number']).toString(),
      onChanged: _setPo,
    );
  }

  Widget _shiftDropdown() {
    final shifts = _filteredShifts;
    final dimmed = _window == 'po';
    return Opacity(
      opacity: dimmed ? 0.4 : 1.0,
      child: _dropdown<int?>(
        value: dimmed ? null : _shiftId,
        hint: 'Shift',
        items: [null, ...shifts.map((s) => s['id'] as int)],
        label: (id) => dimmed
            ? 'All Shifts'
            : (id == null ? 'All shifts' : (shifts.firstWhere((s) => s['id'] == id, orElse: () => {'label': '#$id'})['label']).toString()),
        onChanged: dimmed ? null : _setShift,
      ),
    );
  }

  Widget _dropdown<T>({required T value, required String hint, required List<T> items, required String Function(T) label, ValueChanged<T?>? onChanged}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10),
      decoration: BoxDecoration(border: Border.all(color: Colors.grey.shade300), borderRadius: BorderRadius.circular(8)),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<T>(
          value: value,
          hint: Text(hint),
          isDense: true,
          items: [for (final it in items) DropdownMenuItem(value: it, child: Text(label(it)))],
          onChanged: onChanged,
        ),
      ),
    );
  }

  Widget _windowChips() {
    final opts = [('Entire PO', 'po', 0), ('Selected Shift', 'shift', 0), ('Last 100 rods', 'rods', 100), ('Last 50 rods', 'rods', 50)];
    return Wrap(spacing: 6, children: [
      for (final (l, t, v) in opts)
        ChoiceChip(
          label: Text(l),
          selected: _window == t && (_windowValue == v || t != 'rods'),
          onSelected: (_) => _setWindow(t, v),
          showCheckmark: false,
        ),
    ]);
  }

  // ── KPI strip ─────────────────────────────────────────────────────────────
  Widget _kpiStrip() {
    final k = _data?['kpis'] as Map<String, dynamic>? ?? const {};
    final c1 = _statusColor(k['status_pd']);
    final c2 = _statusColor(k['status_dia']);
    return Row(children: [
      _kpiCard('MEAN PD', _fmt(_num(k['mean_pd']), 1), 'mm WG', Colors.white70),
      _kpiCard('SD PD', _fmt(_num(k['sd_pd']), 2), 'mm WG · ${_pct(_num(k['sd_pd_percent']))}', c1),
      _kpiCard('MEAN DIA', _fmt(_num(k['mean_dia']), 3), 'mm', Colors.white70),
      _kpiCard('SD DIA', _fmt(_num(k['sd_dia']), 4), 'mm · ${_pct(_num(k['sd_dia_percent']))}', c2),
      _kpiCard('VALID RODS', '${k['sample_size'] ?? 0}', 'in window', Colors.blue),
      _kpiCard('REJECTED', '${k['rods_rejected'] ?? 0}', '3× tolerance', Colors.redAccent),
    ]);
  }

  Widget _kpiCard(String label, String value, String sub, Color accent) {
    return Expanded(
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 5),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(10), border: Border.all(color: accent.withValues(alpha: 0.5))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: Colors.black54)),
          const SizedBox(height: 4),
          Text(value, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
          Text(sub, style: const TextStyle(fontSize: 11, color: Colors.black45)),
        ]),
      ),
    );
  }

  // ── Split content ─────────────────────────────────────────────────────────
  Widget _split() {
    return LayoutBuilder(builder: (ctx, c) {
      final wide = c.maxWidth > 1000;
      final charts = _chartsPanel();
      final table = _tablePanel();
      if (wide) {
        return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Expanded(child: table),
          const SizedBox(width: 16),
          Expanded(child: charts),
        ]);
      }
      return Column(children: [
        Expanded(child: charts),
        const SizedBox(height: 16),
        Expanded(child: table),
      ]);
    });
  }

  Widget _chartsPanel() {
    final series = (_data?['series'] as Map<String, dynamic>?) ?? const {};
    final machines = (_data?['active_machines'] as List<dynamic>?) ?? [];
    Widget body;
    if (series.isEmpty) {
      body = const Center(child: Text('No data', style: TextStyle(color: Colors.grey)));
    } else {
      final selected = (_chartTab.isNotEmpty && series.containsKey(_chartTab)) ? _chartTab : series.keys.first.toString();
      final s = (series[selected] as Map<String, dynamic>?) ?? const {};
      body = SingleChildScrollView(child: Column(children: [
        if (machines.length > 1)
          Wrap(spacing: 6, children: [for (final m in machines) ChoiceChip(label: Text('$m'), selected: selected == '$m', onSelected: (_) => setState(() => _chartTab = '$m'), showCheckmark: false)]),
        if (machines.length > 1) const SizedBox(height: 8),
        QualityControlChart(title: 'Pressure Drop (PD) — $selected', parameter: 'pd', lineColor: Colors.blue, series: s, formatValue: (v) => v.toStringAsFixed(1), showOutliers: _showOutliers),
        const SizedBox(height: 10),
        QualityControlChart(title: 'Diameter — $selected', parameter: 'diameter', lineColor: Colors.teal, series: s, formatValue: (v) => v.toStringAsFixed(3), showOutliers: _showOutliers),
      ]));
    }
    return _panel('Control Charts', body, actions: [
      if (!series.isEmpty) ...[
        Checkbox(
          value: _showOutliers,
          onChanged: (v) => setState(() => _showOutliers = v ?? false),
          visualDensity: VisualDensity.compact,
          materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
        ),
        const Text('Show Outliers (3× Tol)', style: TextStyle(fontSize: 12)),
        const SizedBox(width: 8),
      ],
      IconButton(
        tooltip: 'Expand',
        icon: const Icon(Icons.open_in_full, size: 18),
        onPressed: series.isEmpty ? null : () => _openFullscreenCharts(),
      ),
    ]);
  }

  void _openFullscreenCharts() {
    final series = (_data?['series'] as Map<String, dynamic>?) ?? const {};
    final selected = (_chartTab.isNotEmpty && series.containsKey(_chartTab)) ? _chartTab : series.keys.first.toString();
    final s = (series[selected] as Map<String, dynamic>?) ?? const {};
    final controller = TransformationController();
    showDialog(
      context: context,
      builder: (_) => Dialog.fullscreen(
        child: Scaffold(
          backgroundColor: const Color(0xFFF5F5F5),
          appBar: AppBar(title: Text('Control Charts — $selected'), actions: [
            IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
          ]),
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(children: [
              Expanded(child: QualityControlChart(title: 'Pressure Drop (PD) — $selected', parameter: 'pd', lineColor: Colors.blue, series: s, formatValue: (v) => v.toStringAsFixed(1), height: 300, transformationController: controller, showOutliers: _showOutliers)),
              const SizedBox(height: 12),
              Expanded(child: QualityControlChart(title: 'Diameter — $selected', parameter: 'diameter', lineColor: Colors.teal, series: s, formatValue: (v) => v.toStringAsFixed(3), height: 300, transformationController: controller, showOutliers: _showOutliers)),
            ]),
          ),
        ),
      ),
    );
  }

  Widget _tablePanel() {
    final m = _data?['measurements'] as Map<String, dynamic>? ?? const {};
    final rows = (m['rows'] as List<dynamic>?) ?? [];
    final total = m['total'] as int? ?? 0;
    final page = m['page'] as int? ?? 1;
    final pages = (total / 50).ceil();
    return _panel('Measurements', Column(children: [
      Row(children: [
        Text('$total rods', style: const TextStyle(fontSize: 12, color: Colors.black54)),
        const Spacer(),
        OutlinedButton.icon(icon: const Icon(Icons.print, size: 16), label: const Text('Print Report'), onPressed: _openPrintReport),
        const SizedBox(width: 8),
        OutlinedButton.icon(icon: const Icon(Icons.download, size: 16), label: const Text('Export CSV'), onPressed: _exportCsv),
      ]),
      const SizedBox(height: 8),
      Expanded(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : rows.isEmpty
                ? const Center(child: Text('No measurements match the current filters.'))
                : SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: SingleChildScrollView(
                      scrollDirection: Axis.vertical,
                      child: DataTable(
                        headingRowColor: WidgetStatePropertyAll(Colors.grey.shade100),
                        columns: const [
                          DataColumn(label: Text('Timestamp', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12))),
                          DataColumn(label: Text('Rod #', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12))),
                          DataColumn(label: Text('Machine', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12))),
                          DataColumn(label: Text('PO', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12))),
                          DataColumn(label: Text('Diameter', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12))),
                          DataColumn(label: Text('PD', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12))),
                          DataColumn(label: Text('Weight', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12))),
                          DataColumn(label: Text('Status', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12))),
                        ],
                        rows: [for (final r in rows) _row(r)],
                      ),
                    ),
                  ),
      ),
      if (!_loading && rows.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Row(children: [
            IconButton(onPressed: page > 1 ? () => _setPage(page - 1) : null, icon: const Icon(Icons.chevron_left)),
            Text('Page $page / ${pages == 0 ? 1 : pages}'),
            IconButton(onPressed: page < pages ? () => _setPage(page + 1) : null, icon: const Icon(Icons.chevron_right)),
          ]),
        ),
    ]));
  }

  DataRow _row(dynamic r) {
    final m = r as Map<String, dynamic>;
    final rejected = m['rejected'] == true;
    final ts = (m['measured_at'] ?? '-').toString();
    String f(dynamic v, [int d = 3]) => v == null ? '-' : (v is num ? v.toStringAsFixed(d) : '$v');
    return DataRow(cells: [
      DataCell(Text(ts.length > 19 ? ts.substring(0, 19) : ts, style: const TextStyle(fontSize: 12))),
      DataCell(Text('${m['rod_no'] ?? '-'}', style: const TextStyle(fontSize: 12))),
      DataCell(Text('${m['machine_name'] ?? '-'}', style: const TextStyle(fontSize: 12))),
      DataCell(Text('${m['po_number'] ?? '-'}', style: const TextStyle(fontSize: 12))),
      DataCell(Text(f(m['diameter']), style: const TextStyle(fontSize: 12))),
      DataCell(Text(f(m['pd'], 1), style: const TextStyle(fontSize: 12))),
      DataCell(Text(f(m['weight']), style: const TextStyle(fontSize: 12))),
      DataCell(rejected
          ? Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(color: Colors.red.shade100, borderRadius: BorderRadius.circular(8)),
              child: const Text('REJECTED (3× Tol)', style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: Colors.red)))
          : const Text('OK', style: TextStyle(fontSize: 12, color: Colors.green))),
    ]);
  }

  Widget _panel(String title, Widget child, {List<Widget> actions = const []}) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.black12)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold))),
            ...actions,
          ]),
          const SizedBox(height: 8),
          Expanded(child: child),
        ]),
      );

  void _exportCsv() {
    final qp = <String, String>{'fmt': 'csv', 'window': _window, 'window_value': '$_windowValue'};
    if (_machine != 'all') qp['machine'] = _machine;
    if (_poId != null) qp['po_id'] = '$_poId';
    if (_shiftId != null) qp['shift_id'] = '$_shiftId';
    final uri = Uri.parse('${ApiService.effectiveBaseUrl}/v2/quality').replace(queryParameters: qp);
    launchUrl(Uri.base.resolve(uri.toString()), webOnlyWindowName: '_blank');
  }

  Future<void> _openPrintReport() async {
    final d = await ApiService.fetchQualityData(
      machine: _machine,
      poId: _poId,
      shiftId: _window == 'po' ? null : _shiftId,
      window: _window,
      windowValue: _windowValue,
      page: 1,
      pageSize: 50,
      includeRaw: true,
    );
    if (!mounted) return;
    if (d == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to load report data')));
      return;
    }
    final machines = (d['active_machines'] as List<dynamic>?) ?? const [];
    final selected = (machines.contains(_chartTab))
        ? _chartTab
        : (machines.isNotEmpty ? machines.first.toString() : '');
    showDialog(
      context: context,
      builder: (_) => QualityReportDialog(data: d, machine: selected),
    );
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