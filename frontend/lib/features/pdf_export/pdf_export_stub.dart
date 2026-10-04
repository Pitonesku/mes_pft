// lib/features/pdf_export/pdf_export_stub.dart
//
// Abstract interface / stub implementation.
// This file is selected when neither dart:html nor dart:io is available.
// It must compile on ALL platforms — no platform-specific imports allowed here.

import 'dart:typed_data';

/// Abstract contract for platform-specific PDF export.
/// Concrete implementations live in pdf_export_web.dart and pdf_export_android.dart.
abstract class PdfExporterBase {
  /// Opens a print dialog or triggers a browser download.
  Future<void> exportPdf({
    required Uint8List pdfBytes,
    required String filename,
  });
}

/// Concrete stub class — satisfies the type system on all platforms.
/// At runtime this is always replaced by the conditional export.
class PdfExporter implements PdfExporterBase {
  @override
  Future<void> exportPdf({
    required Uint8List pdfBytes,
    required String filename,
  }) {
    throw UnimplementedError(
      'PdfExporter.exportPdf() is not implemented for this platform.',
    );
  }
}

/// Factory function — returns the platform-correct PdfExporter instance.
/// The conditional export in pdf_export.dart ensures the right version is used.
PdfExporter createPdfExporter() => PdfExporter();
