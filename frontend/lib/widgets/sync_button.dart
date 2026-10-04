import 'package:flutter/material.dart';

class ActionSyncButton extends StatefulWidget {
  final Widget child;
  final bool isIcon;
  final Color? color;

  final Future<bool> Function() onSync;
  final VoidCallback onSuccess;

  final String? confirmTitle;
  final String? confirmText;
  final String successMsg;
  final String errorMsg;

  const ActionSyncButton({
    super.key,
    required this.child,
    required this.onSync,
    required this.onSuccess,
    this.isIcon = false,
    this.color,
    this.confirmTitle,
    this.confirmText,
    this.successMsg = "Success!",
    this.errorMsg = "Server error!",
  });

  @override
  State<ActionSyncButton> createState() => _ActionSyncButtonState();
}

class _ActionSyncButtonState extends State<ActionSyncButton> {
  bool _busy = false;

  Future<void> _handlePress(BuildContext context) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      if (widget.confirmTitle != null && widget.confirmText != null) {
        bool? confirm = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: Text(widget.confirmTitle!),
            content: Text(widget.confirmText!),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text("CANCEL")),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text("CONFIRM",
                    style: TextStyle(color: Colors.white)),
              ),
            ],
          ),
        );
        if (confirm != true) return;
      }

      bool success = await widget.onSync();

      if (!context.mounted) return;

      if (success) {
        widget.onSuccess();
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(widget.successMsg), backgroundColor: Colors.green));
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(widget.errorMsg), backgroundColor: Colors.red));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.isIcon) {
      return IconButton(
        icon: widget.child,
        color: widget.color,
        onPressed: _busy ? null : () => _handlePress(context),
      );
    } else {
      return ElevatedButton(
        style: ElevatedButton.styleFrom(
          backgroundColor: widget.color,
          foregroundColor: Colors.white,
        ),
        onPressed: _busy ? null : () => _handlePress(context),
        child: widget.child,
      );
    }
  }
}