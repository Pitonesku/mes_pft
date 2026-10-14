// lib/core/download_bytes_web.dart
// Web implementation: create a Blob + object URL, then click an anchor.
// ignore_for_file: deprecated_member_use, avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:typed_data';

void downloadBytes(Uint8List bytes, String filename, {String mimeType = 'application/zip'}) {
  final blob = html.Blob([bytes], mimeType);
  final url = html.Url.createObjectUrlFromBlob(blob);
  final anchor = html.AnchorElement(href: url)
    ..download = filename
    ..style.display = 'none';
  html.document.body?.append(anchor);
  anchor.click();
  anchor.remove();
  // Revoke on a delay so the browser has time to start the download.
  Future.delayed(const Duration(seconds: 2), () => html.Url.revokeObjectUrl(url));
}
