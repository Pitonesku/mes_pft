// lib/features/pdf_export/report_pdf_controller.dart
//
// Business logic layer for PDF generation and export.
// The UI (both Web and Android) calls a single unified method.
// This class knows nothing about dart:html or dart:io — it delegates
// platform-specific work to the PdfExporter obtained via the conditional export.

import 'package:flutter/foundation.dart';

import '../../models.dart';
import 'pdf_export.dart';        // ← conditional export hub (platform-correct)
import 'pdf_layout_service.dart';

/// Manages PDF generation state and orchestrates the layout + export pipeline.
///
/// Usage with ChangeNotifierProvider (or pass directly):
/// ```dart
/// final controller = ReportPdfController();
/// controller.addListener(() => setState(() {}));
/// ```
class ReportPdfController extends ChangeNotifier {
  // ─── State ─────────────────────────────────────────────────────────────────
  bool _isGenerating = false;
  String? _lastError;
  String? _lastFilename;

  bool get isGenerating => _isGenerating;
  String? get lastError => _lastError;
  String? get lastFilename => _lastFilename;

  // ─── Services ──────────────────────────────────────────────────────────────
  final _layoutService = PdfLayoutService();
  final _exporter = createPdfExporter(); // platform-correct instance

  // ─── Public API ────────────────────────────────────────────────────────────

  /// Generates a Production Report PDF and exports/prints it.
  ///
  /// Called identically from both Web [reports_screen.dart] and
  /// Android [operator_screen.dart] — the platform difference is
  /// handled transparently by [PdfExporter].
  Future<void> generateAndExportReport({
    required Map<String, dynamic> reportData,
    required PurchaseOrder po,
  }) async {
    _setGenerating(true);

    try {
      // 1. Build PDF bytes — platform-agnostic, pure Dart
      final pdfBytes = await _layoutService.buildProductionReport(
        reportData: reportData,
        po: po,
      );

      // 2. Compose a descriptive filename
      final date    = (reportData['report_date'] ?? _today()).toString().replaceAll('/', '-');
      final machine = (reportData['machine_name'] ?? 'machine').toString().replaceAll(' ', '_');
      final shift   = (reportData['shift_name']   ?? 'shift').toString().replaceAll(' ', '_');
      final filename = 'production_report_${date}_${machine}_$shift.pdf';

      // 3. Export — Web opens browser print dialog; Android saves + system print
      await _exporter.exportPdf(pdfBytes: pdfBytes, filename: filename);

      _lastFilename = filename;
      _lastError    = null;
    } catch (e, stack) {
      _lastError = e.toString();
      debugPrint('[ReportPdfController] generateAndExportReport error: $e\n$stack');
    } finally {
      _setGenerating(false);
    }
  }

  /// Generates a Purchase Order summary PDF and exports/prints it.
  Future<void> generateAndExportPurchaseOrder({
    required PurchaseOrder po,
  }) async {
    _setGenerating(true);

    try {
      final pdfBytes = await _layoutService.buildPurchaseOrderSummary(po: po);

      final poNum    = po.poNumber.replaceAll('/', '-').replaceAll(' ', '_');
      final filename = 'purchase_order_$poNum.pdf';

      await _exporter.exportPdf(pdfBytes: pdfBytes, filename: filename);

      _lastFilename = filename;
      _lastError    = null;
    } catch (e, stack) {
      _lastError = e.toString();
      debugPrint('[ReportPdfController] generateAndExportPurchaseOrder error: $e\n$stack');
    } finally {
      _setGenerating(false);
    }
  }

  /// Clears the last error so the UI can reset its error display.
  void clearError() {
    _lastError = null;
    notifyListeners();
  }

  // ─── Private helpers ───────────────────────────────────────────────────────

  void _setGenerating(bool value) {
    _isGenerating = value;
    notifyListeners();
  }

  String _today() {
    final now = DateTime.now();
    return '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
  }
}
