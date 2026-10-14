// lib/theme/theme_presets.dart
// Three UI style presets, each with a light and dark ThemeData.
import 'package:flutter/material.dart';

enum ThemePreset { cupertino, material3, industrial }

ThemeData buildTheme(ThemePreset preset, Brightness brightness) {
  switch (preset) {
    case ThemePreset.cupertino:
      return _cupertino(brightness == Brightness.dark);
    case ThemePreset.material3:
      return _material3(brightness == Brightness.dark);
    case ThemePreset.industrial:
      return _industrial(brightness == Brightness.dark);
  }
}

// ---------------------------------------------------------------------------
// Preset 1 — Modern Cupertino / macOS
// ---------------------------------------------------------------------------

ThemeData _cupertino(bool dark) {
  final scheme = ColorScheme.fromSeed(
    seedColor: const Color(0xFF0A84FF),
    brightness: dark ? Brightness.dark : Brightness.light,
  ).copyWith(
    surface: dark ? const Color(0xFF1E222C) : Colors.white,
    surfaceContainerHighest: dark ? const Color(0xFF232833) : const Color(0xFFF0F2F5),
  );
  final radius = BorderRadius.circular(12);
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: dark ? const Color(0xFF161922) : const Color(0xFFF4F5F9),
    cardTheme: CardThemeData(
      color: scheme.surface,
      elevation: 1,
      shadowColor: const Color(0x0D000000),
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: radius),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: dark ? const Color(0xFF232833) : const Color(0xFFF0F2F5),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(borderRadius: radius, borderSide: BorderSide.none),
      enabledBorder: OutlineInputBorder(borderRadius: radius, borderSide: BorderSide.none),
      focusedBorder: OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: scheme.primary, width: 1.5),
      ),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? Colors.white : const Color(0xFFB0B6C4),
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? const Color(0xFF34C759) : const Color(0xFFE3E6EC),
      ),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        shape: WidgetStatePropertyAll(RoundedRectangleBorder(borderRadius: BorderRadius.circular(24))),
        side: WidgetStatePropertyAll(BorderSide(color: scheme.outlineVariant)),
      ),
    ),
    dividerTheme: DividerThemeData(color: scheme.outlineVariant, thickness: 1),
  );
}

// ---------------------------------------------------------------------------
// Preset 2 — Material You / M3 Expressive
// ---------------------------------------------------------------------------

ThemeData _material3(bool dark) {
  final scheme = ColorScheme.fromSeed(
    seedColor: const Color(0xFF6750A4),
    brightness: dark ? Brightness.dark : Brightness.light,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: dark ? const Color(0xFF141218) : const Color(0xFFFFFBFE),
    cardTheme: CardThemeData(
      color: scheme.surfaceContainer,
      elevation: 1,
      surfaceTintColor: scheme.surfaceTint,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: scheme.surfaceContainerHighest,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(color: scheme.outlineVariant),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(color: scheme.outlineVariant),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(color: scheme.primary, width: 2),
      ),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        shape: WidgetStatePropertyAll(RoundedRectangleBorder(borderRadius: BorderRadius.circular(16))),
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// Preset 3 — Industrial Dark (Control Room)
// ---------------------------------------------------------------------------

ThemeData _industrial(bool dark) {
  const bg = Color(0xFF11141A);
  const surface = Color(0xFF1A1E26);
  const border = Color(0xFF2A303C);
  const mint = Color(0xFF10B981);
  const coral = Color(0xFFEF4444);
  const cyan = Color(0xFF22D3EE);
  const purple = Color(0xFF8B5CF6);

  final scheme = ColorScheme(
    brightness: dark ? Brightness.dark : Brightness.light,
    primary: cyan,
    onPrimary: const Color(0xFF001F24),
    secondary: purple,
    onSecondary: Colors.white,
    error: coral,
    onError: Colors.white,
    surface: dark ? surface : Colors.white,
    onSurface: dark ? const Color(0xFFE6E8EC) : const Color(0xFF1A1E26),
    tertiary: mint,
    onTertiary: const Color(0xFF001F14),
    outline: border,
    outlineVariant: const Color(0xFF3A4150),
    surfaceContainer: dark ? const Color(0xFF1A1E26) : const Color(0xFFF1F3F7),
    surfaceContainerHighest: dark ? const Color(0xFF232833) : const Color(0xFFE8EAEE),
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: dark ? bg : const Color(0xFFE9EBEF),
    cardTheme: CardThemeData(
      color: dark ? surface : Colors.white,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: const BorderSide(color: border),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: dark ? const Color(0xFF141820) : Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6), borderSide: const BorderSide(color: border)),
      enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6), borderSide: const BorderSide(color: border)),
      focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6), borderSide: const BorderSide(color: cyan, width: 1.5)),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? const Color(0xFF001F14) : const Color(0xFFE6E8EC),
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? mint : const Color(0xFF3A4150),
      ),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        shape: WidgetStatePropertyAll(RoundedRectangleBorder(borderRadius: BorderRadius.circular(6))),
        side: WidgetStatePropertyAll(const BorderSide(color: border)),
      ),
    ),
    dividerTheme: const DividerThemeData(color: border, thickness: 1),
  );
}

