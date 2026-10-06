// lib/core/hash_navigation.dart
//
// Conditional export hub for browser hash (fragment) change notifications.
// Keeps dart:html out of non-web builds, mirroring the file_logger pattern.

export 'hash_navigation_stub.dart'
    if (dart.library.html) 'hash_navigation_web.dart';
