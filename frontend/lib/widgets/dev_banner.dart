// lib/widgets/dev_banner.dart
//
// Reusable "DEVELOPING" banner widget.
// Shown at the top of every screen when kIsDeveloping == true.
// To remove it for production: set kIsDeveloping = false in lib/config.dart.

import 'package:flutter/material.dart';
import '../config.dart';

/// Wraps [child] with a persistent red "DEVELOPING" banner at the top.
/// The banner is only rendered when [kIsDeveloping] is true.
///
/// Usage:
/// ```dart
/// DevBanner(child: MyScreen())
/// ```
class DevBanner extends StatelessWidget {
  final Widget child;
  const DevBanner({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    if (!kIsDeveloping) return child;
    return Column(
      children: [
        _DevBannerBar(),
        Expanded(child: child),
      ],
    );
  }
}

/// The actual red banner bar — can also be used standalone as a
/// PreferredSizeWidget inside an AppBar's bottom slot.
class DevBannerBar extends StatelessWidget implements PreferredSizeWidget {
  const DevBannerBar({super.key});

  @override
  Size get preferredSize => const Size.fromHeight(24);

  @override
  Widget build(BuildContext context) {
    if (!kIsDeveloping) return const SizedBox.shrink();
    return _DevBannerBar();
  }
}

class _DevBannerBar extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: Colors.red.shade700,
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: const Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.construction, color: Colors.white, size: 14),
          SizedBox(width: 6),
          Text(
            'DEVELOPING — TEST VERSION — NOT FOR PRODUCTION USE',
            style: TextStyle(
              color: Colors.white,
              fontSize: 11,
              fontWeight: FontWeight.bold,
              letterSpacing: 0.5,
            ),
          ),
          SizedBox(width: 6),
          Icon(Icons.construction, color: Colors.white, size: 14),
        ],
      ),
    );
  }
}
