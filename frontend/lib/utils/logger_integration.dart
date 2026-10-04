import 'logger.dart';
import '../file_logger.dart';

/// Integration layer between AppLog and FileLogger
/// This ensures all logs are written to both console and file
class LoggerIntegration {
  static Future<void> initialize() async {
    await fileLogger.initialize();
  }

  /// Log to both console and file
  static void logToFile(String message, {String level = 'DEBUG'}) {
    // Log to console
    switch (level) {
      case 'ERROR':
        AppLog.e(message);
        break;
      case 'WARNING':
        AppLog.w(message);
        break;
      case 'INFO':
        AppLog.i(message);
        break;
      default:
        AppLog.d(message);
    }

    // Log to file
    fileLogger.log(message, level: level);
  }

  /// Log HTTP request
  static void logRequest(String method, String url, {Map<String, String>? headers, String? body}) {
    final message = '📤 [$method] $url\n   Headers: $headers\n   Body: $body';
    logToFile(message, level: 'INFO');
  }

  /// Log HTTP response
  static void logResponse(int statusCode, int durationMs, {String? body}) {
    final message = '📥 Status: $statusCode (${durationMs}ms)\n   Body: $body';
    logToFile(message, level: 'INFO');
  }

  /// Log HTTP error
  static void logError(String url, String error, {String? stackTrace}) {
    final message = '❌ Error connecting to $url\n   Error: $error\n   Stack: $stackTrace';
    logToFile(message, level: 'ERROR');
  }

  /// Log timeout
  static void logTimeout(String url) {
    final message = '⏱️  TIMEOUT: $url (10 seconds)';
    logToFile(message, level: 'ERROR');
  }
}
