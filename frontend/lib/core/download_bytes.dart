// lib/core/download_bytes.dart
//
// Conditional export hub for triggering a browser file download from bytes.
// Keeps dart:html out of non-web builds (mirrors the open_new_tab pattern).

export 'download_bytes_stub.dart'
    if (dart.library.html) 'download_bytes_web.dart';
