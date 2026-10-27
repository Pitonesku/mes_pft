// lib/widgets/offline_banner.dart
//
// Reusable "OFFLINE - limited data" banner widget.
// Shown at the top of a screen when AppData.usingFallbackData is true,
// i.e. the app could not reach the server and has no cached data, so it is
// only showing the built-in fallback/demo data.

import 'package:flutter/material.dart';
import '../app_state.dart';

/// A PreferredSizeWidget that renders an orange "OFFLINE" banner when the app
/// is showing fallback data, and collapses to zero height otherwise.
class OfflineBannerBar extends StatelessWidget implements PreferredSizeWidget {
  const OfflineBannerBar({super.key});

  @override
  Size get preferredSize =>
      Size.fromHeight(AppData.usingFallbackData ? 24 : 0);

  @override
  Widget build(BuildContext context) {
    if (!AppData.usingFallbackData) return const SizedBox.shrink();
    return Container(
      width: double.infinity,
      color: Colors.orange.shade800,
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: const Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.cloud_off, color: Colors.white, size: 14),
          SizedBox(width: 6),
          Text(
            'OFFLINE - limited data shown (no server connection)',
            style: TextStyle(
              color: Colors.white,
              fontSize: 11,
              fontWeight: FontWeight.bold,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}
