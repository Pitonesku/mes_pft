// lib/core/reload_app_web.dart
// Web implementation: hard reload of the SPA (picks up the new build).
// ignore_for_file: deprecated_member_use, avoid_web_libraries_in_flutter
import 'dart:html' as html;

void reloadApp() {
  html.window.location.reload();
}
