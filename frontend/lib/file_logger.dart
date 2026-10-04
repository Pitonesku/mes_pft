// lib/file_logger.dart
//
// Conditional export hub — this is the ONLY file the rest of the app imports.
// Dart's conditional export picks the correct implementation at compile time,
// preventing dart:io from being compiled on the web platform.

export 'file_logger_stub.dart'
    if (dart.library.html) 'file_logger_web.dart'
    if (dart.library.io)   'file_logger_android.dart';
