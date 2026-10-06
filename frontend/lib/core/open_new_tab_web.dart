// lib/core/open_new_tab_web.dart
// Web implementation: window.open(url, '_blank').
// ignore_for_file: deprecated_member_use
import 'dart:html' as html;

void openInNewTab(String url) {
  html.window.open(url, '_blank');
}

/// Builds an absolute app URL for a hash route (e.g. '/reports/5'), preserving
/// any base path the app is served under. Used by `openInNewTab` so the target
/// tab opens the exact view instead of landing back on the dashboard.
String absoluteAppUrl(String hashPath) {
  final p = hashPath.startsWith('/') ? hashPath : '/$hashPath';
  return Uri.base.replace(query: null, fragment: p).toString();
}
