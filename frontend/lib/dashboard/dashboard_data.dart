// lib/dashboard/dashboard_data.dart
// Snapshot of data handed to every dashboard widget.
import '../models.dart';

class DashboardData {
  final Map<String, dynamic>? summary;
  final List<Map<String, dynamic>> recentReports;
  final User user;

  const DashboardData({
    this.summary,
    this.recentReports = const [],
    required this.user,
  });

  List<Map<String, dynamic>> get machines => _list(summary?['machines']);
  List<Map<String, dynamic>> get orders => _list(summary?['orders']);
  Map<String, dynamic> get kpis =>
      (summary?['kpis'] as Map<String, dynamic>?) ?? const {};
  Map<String, dynamic> get ingestion =>
      (summary?['ingestion'] as Map<String, dynamic>?) ?? const {};

  static List<Map<String, dynamic>> _list(dynamic v) =>
      ((v as List<dynamic>?) ?? const []).cast<Map<String, dynamic>>();
}
