import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'utils/logger.dart';

/// Enhanced HTTP client wrapper with detailed logging for debugging network issues
class LoggingHttpClient extends http.BaseClient {
  final http.Client _inner = http.Client();

  /// Mask the Authorization header value so tokens never land in the log file.
  static Map<String, String> _redactHeaders(Map<String, String> headers) {
    return headers.map((k, v) {
      if (k.toLowerCase() == 'authorization') {
        return MapEntry(k, 'Bearer [REDACTED]');
      }
      return MapEntry(k, v);
    });
  }

  /// Mask credential/token fields inside JSON payloads; everything else is kept.
  static String _redactBody(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map) {
        return jsonEncode(_redactMap(Map<String, dynamic>.from(decoded)));
      }
      if (decoded is List) {
        return jsonEncode(decoded
            .map((e) => e is Map ? _redactMap(Map<String, dynamic>.from(e)) : e)
            .toList());
      }
    } catch (_) {}
    return body;
  }

  static Map<String, dynamic> _redactMap(Map<String, dynamic> map) {
    return map.map((k, v) {
      final key = k.toLowerCase();
      if (key.contains('password') ||
          key == 'token' ||
          key == 'api_key' ||
          key == 'access_token' ||
          key == 'authorization') {
        return MapEntry(k, '***');
      }
      if (v is Map) return MapEntry(k, _redactMap(Map<String, dynamic>.from(v)));
      if (v is List) {
        return MapEntry(k, v
            .map((e) => e is Map ? _redactMap(Map<String, dynamic>.from(e)) : e)
            .toList());
      }
      return MapEntry(k, v);
    });
  }

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final stopwatch = Stopwatch()..start();
    final requestId = DateTime.now().millisecondsSinceEpoch;

    // Log request details
    AppLog.d(
      '📤 [REQUEST #$requestId] ${request.method} ${request.url}',
    );
    AppLog.d('   Headers: ${_redactHeaders(request.headers)}');
    
    if (request.contentLength != null && request.contentLength! > 0) {
      try {
        if (request is http.Request) {
          AppLog.d('   Body: ${_redactBody(request.body)}');
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

      // Log response body for debugging (never break binary payloads).
      final bodyBytes = await response.stream.toBytes();
      try {
        final bodyString = utf8.decode(bodyBytes);
        if (bodyString.isNotEmpty && bodyString.length < 500) {
          AppLog.d('   Response Body: ${_redactBody(bodyString)}');
        } else if (bodyString.isNotEmpty) {
          AppLog.d('   Response Body: [${bodyString.length} bytes]');
        }
      } catch (_) {
        AppLog.d('   Response Body: [Binary data, ${bodyBytes.length} bytes]');
      }

      // Return response with the exact body bytes we already read.
      return http.StreamedResponse(
        http.ByteStream.fromBytes(bodyBytes),
        response.statusCode,
        contentLength: bodyBytes.length,
        request: response.request,
        headers: response.headers,
        isRedirect: response.isRedirect,
        persistentConnection: response.persistentConnection,
        reasonPhrase: response.reasonPhrase,
      );
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
