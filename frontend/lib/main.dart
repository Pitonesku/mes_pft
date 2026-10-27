import 'dart:async';
import 'dart:ui' show PlatformDispatcher;
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'screens/auth_screen.dart';
import 'screens/web/kiosk_quality_screen.dart';
import 'sync_manager.dart';
import 'app_state.dart';
import 'utils/logger_integration.dart';
import 'utils/logger.dart';
import 'api_service.dart';
import 'dead_man_switch.dart';
import 'theme/theme_controller.dart';
import 'widgets/dead_man_alert.dart';

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // File logger works on mobile/desktop; on web it degrades gracefully.
  await LoggerIntegration.initialize();

  // Route uncaught framework/platform errors into the on-device log so crashes
  // are diagnosable from the Connection Logs screen.
  FlutterError.onError = (FlutterErrorDetails details) {
    AppLog.e('Flutter error: ${details.exceptionAsString()}',
        error: details.exception, stackTrace: details.stack);
  };
  PlatformDispatcher.instance.onError = (Object error, StackTrace stack) {
    AppLog.e('Uncaught error: $error', error: error, stackTrace: stack);
    return true;
  };

  // Load the saved server URL from SharedPreferences before any API calls.
  // On first launch (no URL saved), falls back to the compiled-in default.
  if (!kIsWeb) {
    await ApiService.loadSavedBaseUrl();
    final info = await PackageInfo.fromPlatform();
    AppLog.i('App started v${info.version}+${info.buildNumber} server=${ApiService.baseUrl}');
  }
  await ApiService.loadSavedAuthToken();

  // Load the persisted UI theme (preset + mode) before first frame.
  await ThemeController.instance.init();

  // Any 401 from a protected endpoint (stale/expired token) kicks the user back
  // to the login screen with a clean session instead of showing raw errors.
  ApiService.onUnauthorized = () {
    ApiService.clearSession();
    DeadManSwitch.instance.disarm();
    final nav = navigatorKey.currentState;
    if (nav != null && nav.mounted) {
      nav.pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (_) => false,
      );
    }
  };

  // SQLite offline queue is mobile/desktop only -- sqflite crashes on web.
  if (!kIsWeb) {
    SyncManager.syncReports();
    AppData.syncPendingSetupChanges();

    // Periodic background sync: every 60 seconds try to send pending reports
    // and pending machine/shift changes. The sync managers are guarded against
    // parallel execution so this is safe and lightweight.
    Timer.periodic(const Duration(seconds: 60), (_) {
      SyncManager.syncReports();
      AppData.syncPendingSetupChanges();
    });
  }

  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  Widget _home() {
    if (kIsWeb) {
      final frag = Uri.base.fragment;
      if (frag.startsWith('/kiosk')) {
        final q = frag.indexOf('?');
        final path = q == -1 ? frag : frag.substring(0, q);
        if (path == '/kiosk/quality' || path == '/kiosk') {
          final query = q == -1 ? '' : frag.substring(q + 1);
          final params = Uri.splitQueryString(query);
          return KioskQualityScreen(initialMachine: params['machine'] ?? 'M1');
        }
      }
    }
    return const SessionGate();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: ThemeController.instance,
      builder: (context, _) {
        final controller = ThemeController.instance;
        return MaterialApp(
          title: 'Production System',
          navigatorKey: navigatorKey,
          debugShowCheckedModeBanner: false,
          builder: (context, child) => DeadManAlert(child: SelectionArea(child: child!)),
          theme: controller.lightTheme,
          darkTheme: controller.darkTheme,
          themeMode: controller.mode,
          home: _home(),
        );
      },
    );
  }
}
