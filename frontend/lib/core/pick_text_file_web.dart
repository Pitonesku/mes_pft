// lib/core/pick_text_file_web.dart
// Web implementation: open a file input and read the selected file as text.
// ignore_for_file: deprecated_member_use, avoid_web_libraries_in_flutter
import 'dart:async';
import 'dart:html' as html;

Future<String?> pickTextFile({String accept = '.csv,text/csv'}) {
  final input = html.FileUploadInputElement()..accept = accept;
  input.click();
  final completer = Completer<String?>();
  input.onChange.first.then((_) {
    final file = input.files?.first;
    if (file == null) {
      completer.complete(null);
      return;
    }
    final reader = html.FileReader();
    reader.onLoadEnd.first.then((_) => completer.complete(reader.result as String?));
    reader.onError.first.then((_) => completer.complete(null));
    reader.readAsText(file);
  });
  return completer.future;
}
