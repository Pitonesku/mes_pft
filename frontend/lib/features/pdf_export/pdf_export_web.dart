// lib/features/pdf_export/pdf_export_web.dart
//
// Web-specific PDF export implementation.
// Uses dart:html to trigger a browser download and the `printing` package
// for the native browser print dialog.
// This file is ONLY compiled on Web — never on Android.

// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:typed_data';

import 'package:printing/printing.dart';

import 'pdf_export_stub.dart';

/// Web implementation of [PdfExporterBase].
/// Provides two export paths:
///   1. Browser print dialog via the `printing` package (primary).
///   2. Direct file download via dart:html blob (fallback).
class PdfExporter implements PdfExporterBase {
  @override
  Future<void> exportPdf({
    required Uint8List pdfBytes,
    required String filename,
  }) async {
    try {
      // Primary: open the browser's native print dialog.
      // The `printing` package handles the Blob/URL internally on Web.
      await Printing.layoutPdf(
        onLayout: (_) async => pdfBytes,
        name: filename,
      );
    } catch (_) {
      // Fallback: trigger a direct browser download if print dialog fails.
      _triggerBrowserDownload(pdfBytes, filename);
    }
  }

  /// Creates a temporary object URL and clicks a hidden anchor to download.
  void _triggerBrowserDownload(Uint8List bytes, String filename) {
    final blob = html.Blob([bytes], 'application/pdf');
    final url = html.Url.createObjectUrlFromBlob(blob);
    final anchor = html.AnchorElement(href: url)
      ..setAttribute('download', filename)
      ..style.display = 'none';
    html.document.body?.append(anchor);
    anchor.click();
    anchor.remove();
    html.Url.revokeObjectUrl(url);
  }
}

/// Factory — returns the Web [PdfExporter] instance.
PdfExporter createPdfExporter() => PdfExporter();
