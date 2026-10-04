// lib/features/pdf_export/pdf_export.dart
//
// Conditional export hub — this is the ONLY file the rest of the app imports.
// Dart's conditional export picks the correct implementation at compile time,
// preventing dart:html / dart:io from being compiled on the wrong platform.

export 'pdf_export_stub.dart'
    if (dart.library.html) 'pdf_export_web.dart'
    if (dart.library.io) 'pdf_export_android.dart';
