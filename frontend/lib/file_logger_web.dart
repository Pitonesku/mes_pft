// lib/file_logger_web.dart
//
// Web implementation of FileLogger.
// Completely free of dart:io — redirects all logs to print() / browser console.
// Only compiled on platforms where dart:html is available (Flutter Web).

import 'package:intl/intl.dart';
import 'file_logger_stub.dart';
export 'file_logger_stub.dart';

class _WebFileLogger implements FileLogger {
  final List<String> _buffer = [];

  @override
  Future<void> initialize() async {
    // ignore: avoid_print
    print('[FileLogger] Web mode — logs go to browser console only.');
  }

  @override
  Future<void> log(String message, {String level = 'DEBUG'}) async {
    final ts = DateFormat('HH:mm:ss.SSS').format(DateTime.now());
    final line = '[$ts] [$level] $message';
    _buffer.add(line);
    // ignore: avoid_print
    print(line);
  }

  @override
  Future<String> getLogContent() async => _buffer.join('\n');

  @override
  Future<void> clearLogs() async => _buffer.clear();

  @override
  Future<String> getLogFilePath() async => 'N/A (web)';

  @override
  Future<List<String>> getAllLogFilePaths() async => [];
}

FileLogger createFileLogger() => _WebFileLogger();

/// Convenience singleton
final FileLogger fileLogger = createFileLogger();