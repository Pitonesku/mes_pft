import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:install_plugin/install_plugin.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';
import 'api_service.dart';
import 'utils/logger.dart';

class UpdateChecker {
  static String get _baseUrl => ApiService.baseUrl;

  /// Compares two version strings like "1.0.3" vs "1.0.0"
  /// Returns true if serverVersion is newer than currentVersion
  static bool _isNewer(String serverVersion, String currentVersion) {
    try {
      final serverParts = serverVersion.split('.').map(int.parse).toList();
      final currentParts = currentVersion.split('.').map(int.parse).toList();
      // Pad to same length
      while (serverParts.length < 3) {
        serverParts.add(0);
      }
      while (currentParts.length < 3) {
        currentParts.add(0);
      }
      for (int i = 0; i < 3; i++) {
        if (serverParts[i] > currentParts[i]) return true;
        if (serverParts[i] < currentParts[i]) return false;
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  /// Check for updates and show dialog if a newer version is available.
  /// Call this from the login screen or main app init.
  static Future<void> checkForUpdate(BuildContext context) async {
    try {
      // Get current app version
      final packageInfo = await PackageInfo.fromPlatform();
      final currentVersion = packageInfo.version;
      final currentBuild = int.tryParse(packageInfo.buildNumber) ?? 0;

      // Query server for latest version
      final response = await http
          .get(Uri.parse('$_baseUrl/app/latest-version'))
          .timeout(const Duration(seconds: 5));

      if (response.statusCode != 200) return;

      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final serverVersion = data['version_name']?.toString() ?? '';
      final serverBuild = (data['build_number'] as num?)?.toInt() ?? 0;
      final serverSize = (data['size_bytes'] as num?)?.toInt() ?? 0;

      AppLog.i('Update check: current=$currentVersion+$currentBuild, server=$serverVersion+$serverBuild');

      // Show dialog if server has a newer version
      final hasNewerVersion = _isNewer(serverVersion, currentVersion) ||
          (serverVersion == currentVersion && serverBuild > currentBuild);

      if (!hasNewerVersion) return;
      if (!context.mounted) return;

      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => AlertDialog(
          title: Row(
            children: const [
              Icon(Icons.system_update, color: Colors.deepPurple),
              SizedBox(width: 8),
              Text('Update Available', style: TextStyle(color: Colors.deepPurple)),
            ],
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('A new version is available:'),
              const SizedBox(height: 8),
              Text(
                'Current: v$currentVersion (build $currentBuild)\nNew: v$serverVersion (build $serverBuild)',
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 12),
              const Text(
                'Would you like to download and install the update now?',
                style: TextStyle(fontSize: 13),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('LATER', style: TextStyle(color: Colors.grey)),
            ),
            ElevatedButton.icon(
              icon: const Icon(Icons.download),
              label: const Text('UPDATE NOW'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.deepPurple,
                foregroundColor: Colors.white,
              ),
              onPressed: () {
                Navigator.pop(ctx);
                _downloadAndInstall(context, serverVersion, serverBuild, serverSize);
              },
            ),
          ],
        ),
      );
    } catch (e) {
      AppLog.w('Update check failed (non-critical): $e');
    }
  }

  static Future<void> _downloadAndInstall(
    BuildContext context,
    String version,
    int build,
    int sizeBytes,
  ) async {
    if (!context.mounted) return;

    final progress = ValueNotifier<double>(0.0);
    final progressLabel = ValueNotifier<String>('Starting download...');
    var cancelled = false;

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => ValueListenableBuilder<double>(
        valueListenable: progress,
        builder: (context, value, _) => AlertDialog(
          title: const Text('Downloading Update...'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              LinearProgressIndicator(value: value),
              const SizedBox(height: 16),
              Text('${(value * 100).clamp(0, 100).toStringAsFixed(0)}%',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      fontSize: 30, fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              ValueListenableBuilder<String>(
                valueListenable: progressLabel,
                builder: (context, label, _) => Text(label,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 12, color: Colors.grey)),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () {
                cancelled = true;
                Navigator.pop(ctx);
              },
              child: const Text('CANCEL'),
            ),
          ],
        ),
      ),
    );

    http.Client? client;
    IOSink? sink;
    File? apkFile;
    try {
      // Write to internal app documents (covered by FileProvider <files-path>)
      // so install_plugin can serve a content:// URI for the installer.
      final dir = await getApplicationDocumentsDirectory();
      apkFile = File('${dir.path}/prod_log_update_v${version}_b$build.apk');
      sink = apkFile.openWrite();

      client = http.Client();
      final request = http.Request('GET', Uri.parse('$_baseUrl/app/download'));
      final response = await client.send(request).timeout(const Duration(minutes: 10));

      if (response.statusCode != 200) {
        if (context.mounted) Navigator.pop(context);
        _showError(context, 'Download failed: server returned ${response.statusCode}');
        return;
      }

      final total = sizeBytes > 0 ? sizeBytes : (response.contentLength ?? 0);
      var received = 0;
      await for (final chunk in response.stream) {
        if (cancelled) break;
        sink.add(chunk);
        received += chunk.length;
        if (total > 0) {
          progress.value = received / total;
          progressLabel.value = '${_formatBytes(received)} / ${_formatBytes(total)}';
        } else {
          progressLabel.value = '${_formatBytes(received)} downloaded...';
        }
      }

      if (cancelled) {
        try { await sink.close(); } catch (_) {}
        sink = null;
        if (apkFile.existsSync()) await apkFile.delete();
        return;
      }

      await sink.flush();
      await sink.close();
      sink = null;

      if (context.mounted) Navigator.pop(context); // Close progress dialog

      AppLog.i('APK downloaded to: ${apkFile.path}');

      // Trigger the Android package installer. install_plugin builds the
      // FileProvider content:// URI (${applicationId}.fileprovider), fires the
      // ACTION_VIEW intent with GRANT_READ_URI_PERMISSION and handles the
      // "install unknown apps" flow (REQUEST_INSTALL_PACKAGES).
      final result = await InstallPlugin.installApk(apkFile.path, appId: 'com.example.production_app');
      final ok = result is Map && result['isSuccess'] == true;
      if (ok) {
        AppLog.i('APK installed successfully.');
        _showSuccess(context, 'Update installed — please reopen the app.');
      } else {
        final msg = result is Map
            ? (result['errorMessage']?.toString() ?? 'Unknown install error')
            : 'Unknown install error';
        AppLog.e('APK install failed: $msg');
        _showError(context, 'Update failed: $msg');
      }
    } catch (e) {
      try { await sink?.close(); } catch (_) {}
      if (context.mounted) Navigator.pop(context);
      if (!cancelled) _showError(context, 'Download/install error: $e');
    } finally {
      client?.close();
    }
  }

  static String _formatBytes(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  static void _showError(BuildContext context, String message) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('❌ $message'),
        backgroundColor: Colors.red,
        duration: const Duration(seconds: 6),
      ),
    );
  }

  static void _showSuccess(BuildContext context, String message) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('✅ $message'),
        backgroundColor: Colors.green,
        duration: const Duration(seconds: 6),
      ),
    );
  }
}
