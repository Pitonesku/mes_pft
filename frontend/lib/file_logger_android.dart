// lib/file_logger_android.dart
//
// Android (and desktop) file logger implementation.
// Uses dart:io and path_provider to write logs to the local filesystem.
// Only compiled on platforms where dart:io is available.

import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'package:intl/intl.dart';
import 'file_logger_stub.dart';
export 'file_logger_stub.dart';

class _AndroidFileLogger implements FileLogger {
  File? _logFile;
  bool _initialized = false;
  final int _maxFileSize = 5 * 1024 * 1024; // 5 MB

  @override
  Future<void> initialize() async {
    if (_initialized) return;
    try {
      final directory = await getApplicationDocumentsDirectory();
      final logsDir = Directory('${directory.path}/logs');
      if (!await logsDir.exists()) {
        await logsDir.create(recursive: true);
      }
      _logFile = File('${logsDir.path}/app_logs.txt');
      _initialized = true;
      await _writeLog('=== APP STARTED ===', 'INFO');
    } catch (e) {
      // ignore: avoid_print
      print('❌ FileLogger initialization failed: $e');
    }
  }

  @override
  Future<void> log(String message, {String level = 'DEBUG'}) async {
    if (!_initialized) await initialize();
    try {
      await _writeLog(message, level);
    } catch (e) {
      // ignore: avoid_print
      print('❌ Error writing log: $e');
    }
  }

  Future<void> _writeLog(String message, String level) async {
    try {
      final timestamp =
          DateFormat('yyyy-MM-dd HH:mm:ss.SSS').format(DateTime.now());
      final logLine = '[$timestamp] [$level] $message\n';
      final file = _logFile;
      if (file == null) return;
      if (await file.exists()) {
        final fileSize = await file.length();
        if (fileSize > _maxFileSize) await _rotateLog();
      }
      await file.writeAsString(logLine, mode: FileMode.append);
    } catch (e) {
      // ignore: avoid_print
      print('❌ Error in _writeLog: $e');
    }
  }

  Future<void> _rotateLog() async {
    try {
      final file = _logFile;
      if (file == null) return;
      final directory = file.parent;
      final timestamp =
          DateFormat('yyyy-MM-dd_HH-mm-ss').format(DateTime.now());
      final backupFile =
          File('${directory.path}/app_logs_$timestamp.txt');
      await file.rename(backupFile.path);
      _logFile = File(file.path);
      await _logFile!.create();
      await _writeLog('=== LOG ROTATED ===', 'INFO');
    } catch (e) {
      // ignore: avoid_print
      print('❌ Error rotating log: $e');
    }
  }

  @override
  Future<String> getLogContent() async {
    if (!_initialized) await initialize();
    try {
      final file = _logFile;
      if (file != null && await file.exists()) {
        return await file.readAsString();
      }
      return 'No logs yet.';
    } catch (e) {
      return 'Error reading logs: $e';
    }
  }

  @override
  Future<void> clearLogs() async {
    if (!_initialized) await initialize();
    try {
      final file = _logFile;
      if (file != null && await file.exists()) {
        await file.delete();
      }
      _logFile = File(_logFile!.path);
      await _logFile!.create();
      await _writeLog('=== LOGS CLEARED ===', 'INFO');
    } catch (e) {
      // ignore: avoid_print
      print('❌ Error clearing logs: $e');
    }
  }

  @override
  Future<String> getLogFilePath() async {
    if (!_initialized) await initialize();
    return _logFile?.path ?? 'N/A';
  }

  @override
  Future<List<String>> getAllLogFilePaths() async {
    try {
      final directory = await getApplicationDocumentsDirectory();
      final logsDir = Directory('${directory.path}/logs');
      if (!await logsDir.exists()) return [];
      final files = logsDir
          .listSync()
          .whereType<File>()
          .where((f) => f.path.endsWith('.txt'))
          .toList();
      files.sort(
          (a, b) => b.statSync().modified.compareTo(a.statSync().modified));
      return files.map((f) => f.path).toList();
    } catch (e) {
      // ignore: avoid_print
      print('❌ Error getting log files: $e');
      return [];
    }
  }
}

FileLogger createFileLogger() => _AndroidFileLogger();

/// Convenience singleton
final FileLogger fileLogger = createFileLogger();