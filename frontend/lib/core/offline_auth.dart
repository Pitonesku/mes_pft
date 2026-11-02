// lib/core/offline_auth.dart
// Device-bound offline login.
//
// When a user logs in ONLINE, we store a PBKDF2-HMAC-SHA256 verifier of the
// password (random salt per user) together with their profile. When the server
// is unreachable, login verifies the entered password against the stored
// verifier and enters the app in offline mode (orange banner).
//
// This replaces the old insecure fallback: only users who have logged in on
// THIS device can log in offline, always with their real password.

import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:shared_preferences/shared_preferences.dart';

class OfflineAuth {
  static const String _prefsKey = 'offline_users';
  static const int _iterations = 10000;

  /// Derive a PBKDF2-HMAC-SHA256 key of 32 bytes.
  static String _pbkdf2(String password, String saltB64) {
    final salt = base64.decode(saltB64);
    final hmac = Hmac(sha256, utf8.encode(password));
    var u = hmac.convert([...salt, 0, 0, 0, 1]).bytes;
    final result = List<int>.from(u);
    for (var i = 1; i < _iterations; i++) {
      u = hmac.convert(u).bytes;
      for (var j = 0; j < result.length; j++) {
        result[j] ^= u[j];
      }
    }
    return base64.encode(result);
  }

  static String _randomSalt() {
    final rnd = Random.secure();
    final bytes = List<int>.generate(16, (_) => rnd.nextInt(256));
    return base64.encode(bytes);
  }

  static Future<Map<String, dynamic>> _readAll() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_prefsKey);
    if (raw == null || raw.isEmpty) return {};
    try {
      final decoded = jsonDecode(raw);
      return decoded is Map<String, dynamic> ? decoded : {};
    } catch (_) {
      return {};
    }
  }

  /// Store the verifier after a successful ONLINE login.
  static Future<void> cacheCredentials({
    required String username,
    required String password,
    required Map<String, dynamic> userJson,
  }) async {
    final all = await _readAll();
    final salt = _randomSalt();
    all[username] = {
      'salt': salt,
      'verifier': _pbkdf2(password, salt),
      'user': userJson,
    };
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, jsonEncode(all));
  }

  /// True when this device can verify [username] offline.
  static Future<bool> hasOfflineCredentials(String username) async {
    final all = await _readAll();
    return all.containsKey(username);
  }

  /// Verify the password locally; returns the cached user JSON on success.
  static Future<Map<String, dynamic>?> verifyOffline(
      String username, String password) async {
    final all = await _readAll();
    final entry = all[username];
    if (entry == null) return null;
    final salt = entry['salt'] as String?;
    final verifier = entry['verifier'] as String?;
    if (salt == null || verifier == null) return null;
    final candidate = _pbkdf2(password, salt);
    // constant-ish compare: no early exit on length
    final a = utf8.encode(candidate);
    final b = utf8.encode(verifier);
    if (a.length != b.length) return null;
    var diff = 0;
    for (var i = 0; i < a.length; i++) {
      diff |= a[i] ^ b[i];
    }
    if (diff != 0) return null;
    return entry['user'] as Map<String, dynamic>?;
  }
}
