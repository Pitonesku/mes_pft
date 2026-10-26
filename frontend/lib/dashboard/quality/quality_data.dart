// lib/dashboard/quality/quality_data.dart
// Snapshot of the live-quality payload handed to every Quality Monitor widget.
class QualityMonitorData {
  final Map<String, dynamic>? live;

  const QualityMonitorData({this.live});

  /// Per-parameter aggregated stats (mean/sd/status) keyed by parameter name.
  Map<String, dynamic> get parameters =>
      (live?['parameters'] as Map<String, dynamic>?) ?? const {};

  /// Time-series payload: `params` (target/usl/lsl/unit) + `points`.
  Map<String, dynamic> get series =>
      (live?['series'] as Map<String, dynamic>?) ?? const {};

  Map<String, dynamic>? parameterEntry(String key) {
    final e = parameters[key];
    return e is Map<String, dynamic> ? e : null;
  }
}
