// lib/widgets/report_bug_dialog.dart
// Shared "Report a bug / suggestion" dialog (web console + tablet).
// Text is limited to 2000 characters; up to 3 image attachments (<= 4 MB each).
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api_service.dart';

class _Picked {
  final String name;
  final String mime;
  final Uint8List bytes;
  _Picked(this.name, this.mime, this.bytes);
}

class ReportBugDialog extends StatefulWidget {
  final String source; // web | tablet
  const ReportBugDialog({super.key, this.source = 'web'});

  @override
  State<ReportBugDialog> createState() => _ReportBugDialogState();
}

class _ReportBugDialogState extends State<ReportBugDialog> {
  final TextEditingController _textC = TextEditingController();
  final ImagePicker _picker = ImagePicker();
  final List<_Picked> _attachments = [];
  bool _busy = false;

  static const int _maxText = 2000;
  static const int _maxAttachments = 3;
  static const int _maxBytes = 4 * 1024 * 1024;

  @override
  void dispose() {
    _textC.dispose();
    super.dispose();
  }

  void _snack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _pick() async {
    if (_attachments.length >= _maxAttachments) {
      _snack('Maximum $_maxAttachments attachments allowed');
      return;
    }
    try {
      final x = await _picker.pickImage(
        source: ImageSource.gallery,
        imageQuality: 70,
        maxWidth: 1600,
      );
      if (x == null) return;
      final bytes = await x.readAsBytes();
      if (bytes.length > _maxBytes) {
        _snack('Image too large (max 4 MB)');
        return;
      }
      final name = x.name.isNotEmpty ? x.name : 'attachment_${_attachments.length + 1}.jpg';
      final mime = name.toLowerCase().endsWith('.png') ? 'image/png' : 'image/jpeg';
      setState(() => _attachments.add(_Picked(name, mime, bytes)));
    } catch (e) {
      _snack('Could not pick image: $e');
    }
  }

  Future<void> _submit() async {
    final text = _textC.text.trim();
    if (text.isEmpty) {
      _snack('Please describe the issue first');
      return;
    }
    if (text.length > _maxText) {
      _snack('Text is limited to $_maxText characters');
      return;
    }
    setState(() => _busy = true);
    final ok = await ApiService.submitBugReport(
      text: text,
      source: widget.source,
      attachments: [
        for (final a in _attachments)
          {
            'filename': a.name,
            'mime': a.mime,
            'data_base64': base64Encode(a.bytes),
          }
      ],
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) {
      Navigator.pop(context, true);
      _snack('Bug report submitted. Thank you!');
    } else {
      _snack('Failed to submit: ${ApiService.lastApiDetail ?? 'unknown error'}');
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Row(children: [
        Icon(Icons.bug_report, color: Colors.deepPurple),
        SizedBox(width: 8),
        Text('Report a bug / suggestion'),
      ]),
      content: SizedBox(
        width: 480,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          TextField(
            controller: _textC,
            maxLines: 6,
            maxLength: _maxText,
            decoration: const InputDecoration(
              hintText: 'Describe what happened, what you expected, and where you saw it...',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 4),
          Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            OutlinedButton.icon(
              onPressed: _busy ? null : _pick,
              icon: const Icon(Icons.attach_file),
              label: Text('Attach (${_attachments.length}/$_maxAttachments)'),
            ),
            for (final a in _attachments)
              Chip(
                label: Text(a.name, overflow: TextOverflow.ellipsis),
                onDeleted: _busy ? null : () => setState(() => _attachments.remove(a)),
              ),
          ]),
        ]),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context, false), child: const Text('Cancel')),
        FilledButton.icon(
          onPressed: _busy ? null : _submit,
          icon: _busy
              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.send),
          label: const Text('Submit'),
        ),
      ],
    );
  }
}
