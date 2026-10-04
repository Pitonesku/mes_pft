// lib/features/pdf_export/pdf_export_android.dart
//
// Android (and desktop) specific PDF export implementation.
// Uses dart:io and path_provider to save the file locally,
// then opens the system print dialog via the `printing` package.
// This file is ONLY compiled on non-Web platforms — never on Web.

import 'dart:io';
import 'dart:typed_data';

import 'package:path_provider/path_provider.dart';
import 'package:printing/printing.dart';

import 'pdf_export_stub.dart';

/// Android/Desktop implementation of [PdfExporterBase].
/// Saves the PDF to the app's documents directory and opens the
/// system print/share dialog so the user can print or share the file.
class PdfExporter implements PdfExporterBase {
  @override
  Future<void> exportPdf({
    required Uint8List pdfBytes,
    required String filename,
  }) async {
    // 1. Save to local storage for archiving / offline access.
    await _saveToLocalStorage(pdfBytes, filename);

    // 2. Open the system print dialog (Android print framework).
    //    On a tablet connected via ADB this shows the native print UI.
    await Printing.layoutPdf(
      onLayout: (_) async => pdfBytes,
      name: filename,
    );
  }

  /// Writes the PDF bytes to the app's documents directory.
  /// Returns the saved [File] for reference (e.g., to show a snackbar path).
  Future<File> _saveToLocalStorage(Uint8List bytes, String filename) async {
    final dir = await getApplicationDocumentsDirectory();
    final file = File('${dir.path}/$filename');
    await file.writeAsBytes(bytes, flush: true);
    return file;
  }
}

/// Factory — returns the Android/Desktop [PdfExporter] instance.
PdfExporter createPdfExporter() => PdfExporter();
