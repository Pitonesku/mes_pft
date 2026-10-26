// lib/dashboard/dashboard_layout.dart
// Domain models + persistence for the customizable dashboard grid.
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// Fluid 24-column grid: the canvas always spans the full container width and
/// each widget occupies an integer number of columns (w) and rows (h).
const int kColumns = 24;
const int kMinWidgetWidth = 2;

class DashboardItem {
  final String id;
  String type;
  Map<String, dynamic> config;
  int x; // column 0..columns-1
  int y; // row 0..
  int w; // column span (2..24)
  int h; // row span (1..n)

  DashboardItem({
    required this.id,
    required this.type,
    this.config = const {},
    this.x = 0,
    this.y = 0,
    this.w = 2,
    this.h = 1,
  });

  factory DashboardItem.fromJson(Map<String, dynamic> json) => DashboardItem(
        id: json['id'] as String? ?? _newId(),
        type: json['type'] as String? ?? 'kpi',
        config: (json['config'] as Map<String, dynamic>?) ?? const {},
        x: json['x'] as int? ?? 0,
        y: json['y'] as int? ?? 0,
        w: json['w'] as int? ?? _legacyW(json['size']),
        h: json['h'] as int? ?? _legacyH(json['size']),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'type': type,
        'config': config,
        'x': x,
        'y': y,
        'w': w,
        'h': h,
      };

  DashboardItem copyWith(
          {Map<String, dynamic>? config, int? x, int? y, int? w, int? h}) =>
      DashboardItem(
        id: id,
        type: type,
        config: config ?? this.config,
        x: x ?? this.x,
        y: y ?? this.y,
        w: w ?? this.w,
        h: h ?? this.h,
      );

  /// Maps the legacy `size` preset (small/wide/large/extra) to a column span.
  static int _legacyW(dynamic size) => switch (size?.toString()) {
        'small' => 1,
        'large' => 2,
        'extra' => 4,
        _ => 2, // wide
      };

  static int _legacyH(dynamic size) => switch (size?.toString()) {
        'small' => 1,
        'wide' => 1,
        'large' => 2,
        'extra' => 2,
        _ => 1,
      };

  static String _newId() => 'w${DateTime.now().microsecondsSinceEpoch}';
}

class DashboardLayout {
  final int version;
  final int columns;
  final List<DashboardItem> items;

  const DashboardLayout({
    this.version = 1,
    this.columns = kColumns,
    this.items = const [],
  });

  factory DashboardLayout.fromJson(Map<String, dynamic> json) => DashboardLayout(
        version: json['version'] as int? ?? 1,
        columns: json['columns'] as int? ?? kColumns,
        items: ((json['widgets'] as List<dynamic>?) ?? const [])
            .map((e) => DashboardItem.fromJson(e as Map<String, dynamic>))
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'version': version,
        'columns': columns,
        'widgets': items.map((e) => e.toJson()).toList(),
      };

  static DashboardLayout defaultLayout() => DashboardLayout(items: [
        DashboardItem(
            id: 'kpi_output',
            type: 'kpi',
            config: const {'metric': 'output_today'},
            x: 0,
            y: 0,
            w: 6,
            h: 1),
        DashboardItem(
            id: 'kpi_scrap',
            type: 'kpi',
            config: const {'metric': 'scrap_rate'},
            x: 6,
            y: 0,
            w: 6,
            h: 1),
        DashboardItem(
            id: 'kpi_compliance',
            type: 'kpi',
            config: const {'metric': 'compliance'},
            x: 12,
            y: 0,
            w: 6,
            h: 1),
        DashboardItem(
            id: 'kpi_operators',
            type: 'kpi',
            config: const {'metric': 'active_operators'},
            x: 18,
            y: 0,
            w: 6,
            h: 1),
        DashboardItem(
            id: 'machine_m1',
            type: 'machine',
            config: const {'alias': 'M1'},
            x: 0,
            y: 1,
            w: 12,
            h: 2),
        DashboardItem(
            id: 'orders',
            type: 'orders',
            config: const {},
            x: 12,
            y: 1,
            w: 12,
            h: 2),
        DashboardItem(
            id: 'reports',
            type: 'recent_reports',
            config: const {},
            x: 0,
            y: 3,
            w: 24,
            h: 3),
      ]);

  /// Compact default for the Quality Monitor: six small KPI cards (mean + SD
  /// for the two core parameters, plus weight and hardness) and two charts.
  /// All KPI cards use h=1 so they stay roughly half the height of the old
  /// static cards; the operator can add length, resize or rearrange freely.
  static DashboardLayout defaultQualityLayout() => DashboardLayout(items: [
        DashboardItem(
            id: 'kpi_pd_mean',
            type: 'quality_kpi',
            config: const {'parameter': 'pd', 'metric': 'mean'},
            x: 0, y: 0, w: 4, h: 1),
        DashboardItem(
            id: 'kpi_pd_sd',
            type: 'quality_kpi',
            config: const {'parameter': 'pd', 'metric': 'sd'},
            x: 4, y: 0, w: 4, h: 1),
        DashboardItem(
            id: 'kpi_dia_mean',
            type: 'quality_kpi',
            config: const {'parameter': 'diameter', 'metric': 'mean'},
            x: 8, y: 0, w: 4, h: 1),
        DashboardItem(
            id: 'kpi_dia_sd',
            type: 'quality_kpi',
            config: const {'parameter': 'diameter', 'metric': 'sd'},
            x: 12, y: 0, w: 4, h: 1),
        DashboardItem(
            id: 'kpi_weight_mean',
            type: 'quality_kpi',
            config: const {'parameter': 'weight', 'metric': 'mean'},
            x: 16, y: 0, w: 4, h: 1),
        DashboardItem(
            id: 'kpi_hardness_mean',
            type: 'quality_kpi',
            config: const {'parameter': 'hardness', 'metric': 'mean'},
            x: 20, y: 0, w: 4, h: 1),
        DashboardItem(
            id: 'chart_pd',
            type: 'quality_chart',
            config: const {'parameter': 'pd'},
            x: 0, y: 1, w: 12, h: 4),
        DashboardItem(
            id: 'chart_dia',
            type: 'quality_chart',
            config: const {'parameter': 'diameter'},
            x: 12, y: 1, w: 12, h: 4),
      ]);
}

/// Persists a user's dashboard layout to [SharedPreferences] (localStorage on
/// web). Layouts are keyed per-username so each operator/manager keeps their
/// own board; the default layout is returned when nothing has been saved yet.
class DashboardLayoutStore {
  static const String _keyPrefix = 'dashboard_layout_v2';

  static Future<DashboardLayout> load(String username) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString('$_keyPrefix/${_safe(username)}');
      if (raw != null && raw.isNotEmpty) {
        return DashboardLayout.fromJson(
            jsonDecode(raw) as Map<String, dynamic>);
      }
    } catch (_) {}
    return DashboardLayout.defaultLayout();
  }

  static Future<void> save(String username, DashboardLayout layout) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
        '$_keyPrefix/${_safe(username)}', jsonEncode(layout.toJson()));
  }

  static Future<void> reset(String username) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('$_keyPrefix/${_safe(username)}');
  }

  static String _safe(String s) => s.trim().isEmpty ? 'default' : s;
}

/// Per-machine Quality Monitor layout store. The kiosk has no logged-in user,
/// so layouts are keyed by machine alias (each TV remembers its own board) and
/// fall back to [DashboardLayout.defaultQualityLayout] when nothing is saved.
class QualityLayoutStore {
  static const String _keyPrefix = 'dashboard_layout_quality';

  static Future<DashboardLayout> load(String machineAlias) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString('$_keyPrefix/${_safe(machineAlias)}');
      if (raw != null && raw.isNotEmpty) {
        return DashboardLayout.fromJson(jsonDecode(raw) as Map<String, dynamic>);
      }
    } catch (_) {}
    return DashboardLayout.defaultQualityLayout();
  }

  static Future<void> save(String machineAlias, DashboardLayout layout) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
        '$_keyPrefix/${_safe(machineAlias)}', jsonEncode(layout.toJson()));
  }

  static Future<void> reset(String machineAlias) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('$_keyPrefix/${_safe(machineAlias)}');
  }

  static String _safe(String s) => s.trim().isEmpty ? 'kiosk' : s.trim();
}
