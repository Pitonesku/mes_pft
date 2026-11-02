// lib/core/reload_app.dart
// Platform-conditional full-page reload (web) / no-op (others).
export 'reload_app_stub.dart' if (dart.library.html) 'reload_app_web.dart';
