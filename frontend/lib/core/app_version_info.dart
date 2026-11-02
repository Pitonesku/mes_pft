// lib/core/app_version_info.dart
// Version facts shown in the web console: running web build, backend
// software/data version and whether the server offers a newer APK build.

import 'package:package_info_plus/package_info_plus.dart';

import '../api_service.dart';

class AppVersionInfo {
  static String webVersion = '';
  static String webBuild = '';
  static String backendVersion = '';
  static String dataVersion = '';
  static int latestBuild = 0;
  static bool updateAvailable = false;

  /// Web version string for UI display, e.g. "2.2.0+53".
  static String get webVersionLabel =>
      webVersion.isEmpty ? '?' : webBuild.isEmpty ? webVersion : '$webVersion+$webBuild';

  static Future<void> load() async {
    try {
      final info = await PackageInfo.fromPlatform();
      webVersion = info.version;
      webBuild = info.buildNumber;
    } catch (_) {
      webVersion = '';
      webBuild = '';
    }
    try {
      final v = await ApiService.fetchVersionInfo();
      backendVersion = (v?['app_version'] ?? '').toString();
      dataVersion = (v?['data_version'] ?? v?['version'] ?? '').toString();
    } catch (_) {
      backendVersion = '';
      dataVersion = '';
    }
    try {
      final latest = await ApiService.fetchLatestAppVersion();
      latestBuild = int.tryParse('${latest?['build_number'] ?? ''}') ?? 0;
    } catch (_) {
      latestBuild = 0;
    }
    // The "reload to update" banner must only appear when the WEB bundle
    // served by this server is newer than the one currently running -
    // reloading a page can never install an APK. Compare the served
    // version.json build number against the local web build.
    try {
      final served = await ApiService.fetchServedWebVersion();
      final servedBuild = int.tryParse('${served?['build_number'] ?? ''}') ?? 0;
      final localBuild = int.tryParse(webBuild) ?? 0;
      updateAvailable = servedBuild > 0 && localBuild > 0 && servedBuild > localBuild;
    } catch (_) {
      updateAvailable = false;
    }
  }
}
