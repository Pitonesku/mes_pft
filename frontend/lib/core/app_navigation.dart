// lib/core/app_navigation.dart
// Lightweight in-app navigation for cross-section actions (no router dependency).
import 'package:flutter/foundation.dart';

class QualityRequest {
  final String? machine;
  final int? shiftId;
  final int? poId;
  final String? po;
  final int? reportId;
  const QualityRequest({this.machine, this.shiftId, this.poId, this.po, this.reportId});
}

class AppNavigation {
  AppNavigation._();

  static final ValueNotifier<QualityRequest?> qualityRequest = ValueNotifier<QualityRequest?>(null);

  static void openQualityControl({String? machine, int? shiftId, int? poId, String? po, int? reportId}) {
    qualityRequest.value = QualityRequest(machine: machine, shiftId: shiftId, poId: poId, po: po, reportId: reportId);
  }

  static final ValueNotifier<int?> reportRequest = ValueNotifier<int?>(null);

  static void openReport(int reportId) {
    reportRequest.value = reportId;
  }

  static final ValueNotifier<String?> orderRequest = ValueNotifier<String?>(null);

  static void openOrder(String poNumber) {
    orderRequest.value = poNumber;
  }
}