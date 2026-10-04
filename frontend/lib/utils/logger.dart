import 'package:logger/logger.dart';
import '../file_logger.dart';

/// Custom [LogOutput] that writes to **both** the console and the file logger.
/// Every [AppLog.d]/[AppLog.i]/[AppLog.w]/[AppLog.e] call in the entire app
/// is automatically captured and written to the on-device log file.
class _DualOutput extends LogOutput {
  final ConsoleOutput _console = ConsoleOutput();
  final FileLogger _file;

  _DualOutput(this._file);

  // Map Logger level strings to our FileLogger level labels
  static String _levelToLabel(Level level) {
    if (level.value >= Level.error.value) return 'ERROR';
    if (level.value >= Level.warning.value) return 'WARNING';
    if (level.value >= Level.info.value) return 'INFO';
    return 'DEBUG';
  }

  @override
  void output(OutputEvent event) {
    // 1. Print to console (coloured, emoji, etc.)
    _console.output(event);

    // 2. Write to file (on-device log)
    for (final line in event.lines) {
      try {
        _file.log(line, level: _levelToLabel(event.level));
      } catch (_) {
        // If file logger fails (e.g. not initialized yet), silently ignore
      }
    }
  }
}

/// Global logger instance for the whole application.
/// Writes to **console** (coloured with emojis) AND **file** (app_logs.txt).
final AppLog = Logger(
  output: _DualOutput(fileLogger),
  printer: PrettyPrinter(
    methodCount: 0,
    errorMethodCount: 5,
    lineLength: 80,
    colors: true,
    printEmojis: true,
    dateTimeFormat: DateTimeFormat.none,
  ),
);
