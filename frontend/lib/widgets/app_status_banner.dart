// lib/widgets/app_status_banner.dart
//
// Stacks the DEV banner and the OFFLINE banner as an AppBar `bottom`,
// reporting a dynamic height so no blank space is reserved when both are
// inactive.

import 'package:flutter/material.dart';
import '../app_state.dart';
import '../config.dart';
import 'dev_banner.dart';
import 'offline_banner.dart';

class AppStatusBanner extends StatelessWidget implements PreferredSizeWidget {
  const AppStatusBanner({super.key});

  @override
  Size get preferredSize => Size.fromHeight(
        (kIsDeveloping ? 24.0 : 0.0) +
            (AppData.usingFallbackData ? 24.0 : 0.0),
      );

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: const [DevBannerBar(), OfflineBannerBar()],
    );
  }
}
