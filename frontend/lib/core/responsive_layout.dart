// lib/core/responsive_layout.dart
//
// THE single switch point between mobile and desktop/web UI.
// Nothing outside this file should check kIsWeb or screen width
// for layout decisions — import this and use isDesktopLayout() or
// ResponsiveLayout widget instead.

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import '../models.dart';

/// Screens wider than this get the desktop/web shell.
/// 900 dp: comfortably above any phone portrait, below any laptop.
const double kDesktopBreakpoint = 900.0;

/// Returns true when the current context should render the desktop/web UI.
/// Rule: kIsWeb == true  OR  screen width >= 900 dp.
bool isDesktopLayout(BuildContext context) {
  if (kIsWeb) return true;
  return MediaQuery.sizeOf(context).width >= kDesktopBreakpoint;
}

/// Drop-in wrapper used at every top-level navigation point.
/// Passes [currentUser] through to whichever builder is chosen.
class ResponsiveLayout extends StatelessWidget {
  final User currentUser;
  final Widget Function(BuildContext context, User user) mobileBuilder;
  final Widget Function(BuildContext context, User user) desktopBuilder;

  const ResponsiveLayout({
    super.key,
    required this.currentUser,
    required this.mobileBuilder,
    required this.desktopBuilder,
  });

  @override
  Widget build(BuildContext context) {
    return isDesktopLayout(context)
        ? desktopBuilder(context, currentUser)
        : mobileBuilder(context, currentUser);
  }
}
