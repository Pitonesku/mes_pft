// lib/core/pick_text_file.dart
//
// Conditional export hub for opening a text-file picker and reading its content.
// Keeps dart:html out of non-web builds (mirrors the open_new_tab pattern).

export 'pick_text_file_stub.dart'
    if (dart.library.html) 'pick_text_file_web.dart';
