import 'dart:async';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'screens/auth_screen.dart';
import 'sync_manager.dart';
import 'app_state.dart';
import 'utils/logger_integration.dart';
import 'api_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // File logger works on mobile/desktop; on web it degrades gracefully.
  await LoggerIntegration.initialize();

  // Load the saved server URL from SharedPreferences before any API calls.
  // On first launch (no URL saved), falls back to the compiled-in default.
  if (!kIsWeb) {
    await ApiService.loadSavedBaseUrl();
    await ApiService.loadSavedAuthToken();
  }

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

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Production System',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        primarySwatch: Colors.deepPurple,
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF673AB7)),
        scaffoldBackgroundColor: const Color(0xFFF0EBF8),
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
          focusedBorder: OutlineInputBorder(
            borderSide: BorderSide(color: Color(0xFF673AB7), width: 2.0),
          ),
          isDense: true,
        ),
        cardTheme: CardThemeData(
          elevation: 2,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
      home: const LoginScreen(),
    );
  }
}
