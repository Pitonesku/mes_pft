// lib/core/hash_navigation_web.dart
// Web implementation using the browser's hashchange event.
// ignore_for_file: deprecated_member_use
import 'dart:html' as html;

void listenToHashChange(void Function(String fragment) callback) {
  html.window.onHashChange.listen((_) => callback(currentHash()));
}

String currentHash() {
  var h = html.window.location.hash ?? '';
  if (h.startsWith('#')) h = h.substring(1);
  return h;
}

/// Sets the URL hash to [fragment] (leading '#' optional) so the address bar
/// reflects the active view and deep links stay shareable/refreshable.
///
/// Uses history.replaceState (not window.location.hash) so the URL is updated
/// without firing 'hashchange'; navigation is driven by setState, and this
/// only keeps the address bar in sync.
void setHash(String fragment) {
  var h = fragment;
  if (!h.startsWith('#')) h = '#$h';
  html.window.history.replaceState(null, '', h);
}

/// Navigates to an in-app route such as '/reports/5' or '/quality'.
void navigateTo(String path) {
  setHash(path);
}
