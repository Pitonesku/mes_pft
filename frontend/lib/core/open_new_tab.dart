// lib/core/open_new_tab.dart
//
// Conditional export hub for opening a URL in a new browser tab.
// Keeps dart:html out of non-web builds (mirrors the hash_navigation pattern).

export 'open_new_tab_stub.dart'
    if (dart.library.html) 'open_new_tab_web.dart';
