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

  /// Server-side SD-only statuses (GREEN/YELLOW/RED/NO_DATA) for the two
  /// parameters that have SD thresholds. Kiosk tiles colour by SD only.
  String? get statusPd => live?['status_pd']?.toString();

  String? get statusDia => live?['status_dia']?.toString();

  /// Triacetin summary from the live payload (overall/last/last_at/status/...).
  Map<String, dynamic>? get triacetin =>
      live?['triacetin'] as Map<String, dynamic>?;
}
