import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'utils/logger.dart';

/// Enhanced HTTP client wrapper with detailed logging for debugging network issues
class LoggingHttpClient extends http.BaseClient {
  final http.Client _inner = http.Client();

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final stopwatch = Stopwatch()..start();
    final requestId = DateTime.now().millisecondsSinceEpoch;

    // Log request details
    AppLog.d(
      '📤 [REQUEST #$requestId] ${request.method} ${request.url}',
    );
    AppLog.d('   Headers: ${request.headers}');
    
    if (request.contentLength != null && request.contentLength! > 0) {
      try {
        if (request is http.Request) {
          AppLog.d('   Body: ${request.body}');
        }
      } catch (e) {
        AppLog.d('   Body: [Binary data]');
      }
    }

    try {
      // Send request with timeout
      final response = await _inner.send(request).timeout(
        const Duration(seconds: 10),
        onTimeout: () {
          AppLog.e(
            '⏱️  [REQUEST #$requestId] TIMEOUT after 10 seconds for ${request.method} ${request.url}',
          );
          throw TimeoutException('Request timeout');
        },
      );

      stopwatch.stop();
      final duration = stopwatch.elapsedMilliseconds;

      // Log response details
      AppLog.d(
        '📥 [RESPONSE #$requestId] Status: ${response.statusCode} (${duration}ms)',
      );

      // Log response body for debugging
      try {
        final bodyBytes = await response.stream.toBytes();
        final bodyString = utf8.decode(bodyBytes);
        
        if (bodyString.isNotEmpty && bodyString.length < 500) {
          AppLog.d('   Response Body: $bodyString');
        } else if (bodyString.isNotEmpty) {
          AppLog.d('   Response Body: [${bodyString.length} bytes]');
        }

        // Return response with body
        return http.StreamedResponse(
          http.ByteStream.fromBytes(bodyBytes),
          response.statusCode,
          contentLength: response.contentLength,
          request: response.request,
          headers: response.headers,
          isRedirect: response.isRedirect,
          persistentConnection: response.persistentConnection,
          reasonPhrase: response.reasonPhrase,
        );
      } catch (e) {
        AppLog.d('   Response Body: [Unable to decode]');
        return response;
      }
    } on TimeoutException catch (e) {
      AppLog.e(
        '❌ [REQUEST #$requestId] TIMEOUT ERROR: $e\n'
        '   URL: ${request.url}\n'
        '   Method: ${request.method}\n'
        '   Possible causes:\n'
        '   - Server not responding\n'
        '   - Network connectivity issue\n'
        '   - WSL/WireGuard tunnel issue\n'
        '   - Port forwarding not working',
      );
      rethrow;
    } catch (e, stackTrace) {
      stopwatch.stop();
      final duration = stopwatch.elapsedMilliseconds;

      AppLog.e(
        '❌ [REQUEST #$requestId] ERROR after ${duration}ms\n'
        '   URL: ${request.url}\n'
        '   Method: ${request.method}\n'
        '   Error: $e\n'
        '   Stack: $stackTrace\n'
        '   Possible causes:\n'
        '   - Network connectivity issue\n'
        '   - DNS resolution failure\n'
        '   - WSL/WireGuard tunnel disconnected\n'
        '   - Port forwarding misconfigured',
      );
      rethrow;
    }
  }
}

/// Convenience function to create a logging HTTP client
http.Client createLoggingHttpClient() {
  return LoggingHttpClient();
}
