// lib/widgets/quality_control_chart.dart
// Reusable control chart (individuals chart) with Target/USL/LSL reference
// lines, rejected-rod markers, pan/zoom, midnight day dividers, and a rich tooltip.
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

class QualityControlChart extends StatelessWidget {
  final String title;
  final String parameter;
  final Color lineColor;
  final Map<String, dynamic>? series;
  final String Function(double) formatValue;
  final TransformationController? transformationController;
  final double height;
  final bool showOutliers;
  final double valueScale;
  final String? unitLabel;
  final double? yMin;
  final double? yMax;

  const QualityControlChart({
    super.key,
    required this.title,
    required this.parameter,
    required this.lineColor,
    required this.series,
    required this.formatValue,
    this.transformationController,
    this.height = 190,
    this.showOutliers = false,
    this.valueScale = 1.0,
    this.unitLabel,
    this.yMin,
    this.yMax,
  });

  @override
  Widget build(BuildContext context) {
    var points = _points();
    if (!showOutliers) {
      points = points.where((p) => !p.rejected).toList();
    }
    if (points.isEmpty) {
      return _frame(null, const Center(child: Text('No data available',
          style: TextStyle(color: Colors.grey, fontSize: 12))));
    }

    final params = (series?['params'] as Map<String, dynamic>?) ?? const {};
    final p = (params[parameter] as Map<String, dynamic>?) ?? const {};
    final target = _scaled(_num(p['target']));
    final usl = _scaled(_num(p['usl']));
    final lsl = _scaled(_num(p['lsl']));

    final all = <FlSpot>[];
    final byX = <double, _Point>{};
    for (final pt in points) {
      all.add(FlSpot(pt.x, pt.y));
      byX[pt.x] = pt;
    }

    // Y-axis: prefer the spec band (LSL - 1.5*tol .. USL + 1.5*tol) so a single
    // gross outlier can't flatten the valid production band. Fall back to the
    // data range when limits are missing.
    double autoMinY;
    double autoMaxY;
    if (usl != null && lsl != null && usl > lsl) {
      final tol = (usl - lsl) / 2;
      autoMinY = lsl - 1.5 * tol;
      autoMaxY = usl + 1.5 * tol;
    } else {
      final ys = <double>[for (final pt in points) pt.y];
      if (target != null) ys.add(target);
      if (usl != null) ys.add(usl);
      if (lsl != null) ys.add(lsl);
      autoMinY = ys.reduce((a, b) => a < b ? a : b);
      autoMaxY = ys.reduce((a, b) => a > b ? a : b);
      if (autoMinY == autoMaxY) { autoMinY -= 1; autoMaxY += 1; }
      final pad = (autoMaxY - autoMinY) * 0.15;
      autoMinY -= pad; autoMaxY += pad;
    }

    var minY = yMin ?? autoMinY;
    var maxY = yMax ?? autoMaxY;
    if (minY >= maxY) {
      minY = autoMinY;
      maxY = autoMaxY;
    }

    final minX = points.first.x;
    final maxX = points.last.x;
    final span = maxX - minX;
    final padX = (span * 0.12) > (30 * 60 * 1000) ? (span * 0.12) : (30 * 60 * 1000.0);
    final rawMinX = minX - padX;
    final chartMaxX = maxX + padX;
    final tickStep = _tickStepMs(chartMaxX - rawMinX);
    // fl_chart draws ticks at minX + k*interval: snap minX down to the tick grid so
    // labels land on whole hours (06:00, 09:00 ...) instead of 06:34, 07:34 ...
    final chartMinX = (rawMinX / tickStep).floorToDouble() * tickStep;
    final midnights = _midnights(chartMinX, chartMaxX);
    final firstDate = _dateLabel(minX);
    final lastDate = _dateLabel(maxX);
    final dateSuffix = firstDate == lastDate ? firstDate : '$firstDate → $lastDate';

    return _frame(dateSuffix, LineChart(
      LineChartData(
        minX: chartMinX,
        maxX: chartMaxX,
        minY: minY,
        maxY: maxY,
        clipData: const FlClipData.all(),
        gridData: FlGridData(show: true, drawVerticalLine: false, horizontalInterval: (maxY - minY) / 5),
        borderData: FlBorderData(show: true, border: Border.all(color: Colors.black12, width: 0.5)),
        titlesData: FlTitlesData(
          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          leftTitles: AxisTitles(sideTitles: SideTitles(
            showTitles: true,
            reservedSize: 48,
            getTitlesWidget: (v, meta) => Text(formatValue(v), style: const TextStyle(fontSize: 10, color: Colors.black54)),
          )),
          bottomTitles: AxisTitles(sideTitles: SideTitles(
            showTitles: true,
            reservedSize: 34,
            interval: tickStep,
            getTitlesWidget: (v, meta) {
              // The max edge label can collide with its neighbour; skip it.
              if (v == meta.max) return const SizedBox.shrink();
              return _bottomTitle(v, tickStep);
            },
          )),
        ),
        extraLinesData: ExtraLinesData(
          horizontalLines: [
            if (target != null) HorizontalLine(y: target, color: Colors.green, strokeWidth: 1.2, dashArray: [8, 4], label: HorizontalLineLabel(show: true, labelResolver: (_) => 'T ${formatValue(target)}', style: const TextStyle(fontSize: 9, color: Colors.green))),
            if (usl != null) HorizontalLine(y: usl, color: Colors.red, strokeWidth: 1.2, dashArray: [8, 4], label: HorizontalLineLabel(show: true, labelResolver: (_) => 'USL ${formatValue(usl)}', style: const TextStyle(fontSize: 9, color: Colors.red))),
            if (lsl != null) HorizontalLine(y: lsl, color: Colors.red, strokeWidth: 1.2, dashArray: [8, 4], label: HorizontalLineLabel(show: true, labelResolver: (_) => 'LSL ${formatValue(lsl)}', style: const TextStyle(fontSize: 9, color: Colors.red))),
          ],
          verticalLines: [
            for (final m in midnights)
              VerticalLine(x: m, color: Colors.grey.shade400, strokeWidth: 1, dashArray: [4, 4], label: VerticalLineLabel(show: true, alignment: Alignment.bottomCenter, labelResolver: (_) => _dateLabel(m), style: const TextStyle(fontSize: 9, color: Colors.black54))),
          ],
        ),
        lineTouchData: LineTouchData(
          enabled: true,
          touchTooltipData: LineTouchTooltipData(
            getTooltipItems: (spots) => _tooltipItems(spots, byX, params),
            getTooltipColor: (_) => const Color(0xFF20242E),
            tooltipRoundedRadius: 8,
            tooltipPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            maxContentWidth: 240,
          ),
        ),
        lineBarsData: [
          LineChartBarData(
            spots: all,
            isCurved: false,
            color: lineColor,
            barWidth: 0,
            dotData: FlDotData(show: true, getDotPainter: (spot, pct, bar, index) {
              final pt = byX[spot.x];
              final rejected = pt?.rejected ?? false;
              return FlDotCirclePainter(radius: rejected ? 3.5 : 3, color: rejected ? Colors.redAccent : lineColor, strokeWidth: 0);
            }),
          ),
        ],
      ),
      transformationConfig: FlTransformationConfig(
        scaleAxis: FlScaleAxis.horizontal,
        panEnabled: true,
        scaleEnabled: true,
        maxScale: 2000,
        transformationController: transformationController,
      ),
    ));
  }

  /// Tick spacing chosen from the visible span so there are at most ~8 labels.
  double _tickStepMs(double spanMs) {
    const hour = 3600 * 1000.0;
    const steps = [1, 2, 3, 6, 12, 24, 48, 72, 168];
    for (final h in steps) {
      if (spanMs / (h * hour) <= 8) return h * hour;
    }
    return 168 * hour;
  }

  Widget _bottomTitle(double value, double step) {
    final dt = DateTime.fromMillisecondsSinceEpoch(value.toInt(), isUtc: true);
    final hh = dt.hour.toString().padLeft(2, '0');
    final mm = dt.minute.toString().padLeft(2, '0');
    final date = _dateLabel(value).substring(5); // MM-DD
    const style = TextStyle(fontSize: 9, color: Colors.black54);
    if (step >= 24 * 3600 * 1000.0) {
      return Text(date, style: style);
    }
    // Hours + a second line with the date, so one-day charts still show the day.
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Text('$hh:$mm', style: style),
      Text(date, style: const TextStyle(fontSize: 8, color: Colors.black38)),
    ]);
  }

  List<LineTooltipItem?> _tooltipItems(List<LineBarSpot> spots, Map<double, _Point> byX, Map<String, dynamic> params) {
    final p = (params[parameter] as Map<String, dynamic>?) ?? const {};
    final rawTarget = _num(p['target']);
    final target = rawTarget == null ? null : rawTarget * valueScale;
    final unit = unitLabel ?? p['unit']?.toString() ?? '';
    return spots.map((s) {
      final pt = byX[s.x];
      if (pt == null) return null;
      final ts = pt.timestamp ?? '-';
      final val = s.y;
      final diff = target != null ? ' (Δ ${(val >= target ? '+' : '') + formatValue(val - target)})' : '';
      final statusColor = pt.rejected ? Colors.redAccent : Colors.greenAccent;
      return LineTooltipItem('', const TextStyle(), children: [
        TextSpan(text: '$ts\n', style: const TextStyle(color: Colors.white70, fontSize: 11)),
        TextSpan(text: 'Rod #${pt.rodNo ?? '-'}\n', style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold)),
        TextSpan(text: '$title: ${formatValue(val)}${unit.isNotEmpty ? ' $unit' : ''}$diff\n', style: const TextStyle(color: Colors.white, fontSize: 12)),
        TextSpan(text: pt.rejected ? 'REJECTED (Outlier)' : 'OK', style: TextStyle(color: statusColor, fontSize: 12, fontWeight: FontWeight.bold)),
      ]);
    }).toList();
  }

  Widget _frame(String? dateText, Widget child) => Container(
    padding: const EdgeInsets.all(8),
    decoration: BoxDecoration(color: Colors.white, border: Border.all(color: Colors.black12), borderRadius: BorderRadius.circular(8)),
    child: LayoutBuilder(builder: (ctx, constraints) {
      final Widget chart = constraints.hasBoundedHeight
          ? Expanded(child: child)
          : SizedBox(height: height, width: double.infinity, child: child);
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(dateText == null ? title : '$title · $dateText',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
        const SizedBox(height: 4),
        chart,
      ]);
    }),
  );

  List<double> _midnights(double minX, double maxX) {
    final out = <double>[];
    final start = DateTime.fromMillisecondsSinceEpoch(minX.toInt(), isUtc: true);
    // x values are plant wall-clock time encoded as UTC, so build midnights in UTC
    // (a local DateTime would shift every divider by the browser's UTC offset).
    var d = DateTime.utc(start.year, start.month, start.day);
    while (d.millisecondsSinceEpoch <= maxX.toInt()) {
      if (d.millisecondsSinceEpoch >= minX.toInt()) out.add(d.millisecondsSinceEpoch.toDouble());
      d = d.add(const Duration(days: 1));
    }
    return out;
  }

  String _dateLabel(double x) {
    final dt = DateTime.fromMillisecondsSinceEpoch(x.toInt(), isUtc: true);
    final mo = dt.month.toString().padLeft(2, '0');
    final dd = dt.day.toString().padLeft(2, '0');
    return '${dt.year}-$mo-$dd';
  }

  List<_Point> _points() {
    final raw = (series?['points'] as List<dynamic>?) ?? const [];
    final out = <_Point>[];
    for (final r in raw) {
      final m = r as Map<String, dynamic>;
      final x = (m['x'] as num?)?.toDouble();
      final rawY = (m[parameter] as num?)?.toDouble();
      final y = rawY == null ? null : rawY * valueScale;
      if (x == null || y == null) continue;
      out.add(_Point(
        x: x,
        y: y,
        rejected: m['rejected'] == true,
        rodNo: (m['rod_no'] as num?)?.toInt(),
        timestamp: m['synthetic_timestamp']?.toString(),
      ));
    }
    out.sort((a, b) => a.x.compareTo(b.x));
    return out;
  }

  double? _num(dynamic v) => v == null ? null : (v is num ? v.toDouble() : double.tryParse('$v'));

  double? _scaled(double? v) => v == null ? null : v * valueScale;
}

class _Point {
  final double x;
  final double y;
  final bool rejected;
  final int? rodNo;
  final String? timestamp;
  _Point({
    required this.x,
    required this.y,
    required this.rejected,
    this.rodNo,
    this.timestamp,
  });
}