// lib/file_logger_stub.dart
//
// Abstract interface for the file logger.
// Used as the fallback on platforms where neither dart:io nor dart:html is available.
// All types are platform-agnostic (no dart:io File references).

import 'package:intl/intl.dart';

abstract class FileLogger {
  Future<void> initialize();
  Future<void> log(String message, {String level = 'DEBUG'});
  Future<String> getLogContent();
  Future<void> clearLogs();
  Future<String> getLogFilePath();
  /// Returns a list of log file paths (as Strings, not dart:io File objects).
  Future<List<String>> getAllLogFilePaths();
}

/// No-op implementation for unsupported platforms.
class _StubFileLogger implements FileLogger {
  @override
  Future<void> initialize() async {}

  @override
  Future<void> log(String message, {String level = 'DEBUG'}) async {
    final ts = DateFormat('HH:mm:ss').format(DateTime.now());
    // ignore: avoid_print
    print('[$ts] [$level] $message');
  }

  @override
  Future<String> getLogContent() async =>
      'File logging not available on this platform.';

  @override
  Future<void> clearLogs() async {}

  @override
  Future<String> getLogFilePath() async => 'N/A';

  @override
  Future<List<String>> getAllLogFilePaths() async => [];
}

FileLogger createFileLogger() => _StubFileLogger();

/// Convenience singleton — import file_logger.dart and use this.
final FileLogger fileLogger = createFileLogger();
