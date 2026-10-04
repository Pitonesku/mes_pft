import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:open_filex/open_filex.dart';
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
                _downloadAndInstall(context, serverVersion, serverBuild);
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
  ) async {
    // Show download progress dialog
    if (!context.mounted) return;

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => const AlertDialog(
        title: Text('Downloading Update...'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: 16),
            Text('Please wait while the update is downloaded.'),
          ],
        ),
      ),
    );

    try {
      final downloadUrl = '$_baseUrl/app/download';
      final response = await http
          .get(Uri.parse(downloadUrl))
          .timeout(const Duration(minutes: 5));

      if (response.statusCode != 200) {
        if (context.mounted) Navigator.pop(context);
        _showError(context, 'Download failed: server returned ${response.statusCode}');
        return;
      }

      // Save APK to downloads directory
      final dir = await getExternalStorageDirectory() ?? await getApplicationDocumentsDirectory();
      final apkFile = File('${dir.path}/prod_log_update_v${version}_b$build.apk');
      await apkFile.writeAsBytes(response.bodyBytes);

      if (context.mounted) Navigator.pop(context); // Close progress dialog

      AppLog.i('APK downloaded to: ${apkFile.path}');

      // Open APK using open_filex to trigger the Android package installer.
      // open_filex uses FileProvider to generate a content:// URI which Android
      // can properly handle for APK installation (unlike raw file:// URIs).
      final result = await OpenFilex.open(
        apkFile.path,
        type: 'application/vnd.android.package-archive',
      );

      AppLog.i('APK install result: ${result.message} (type: ${result.type})');
    } catch (e) {
      if (context.mounted) Navigator.pop(context);
      _showError(context, 'Download error: $e');
    }
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
}
