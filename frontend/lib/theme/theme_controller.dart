// lib/theme/theme_controller.dart
// Reactive theme controller: holds the active preset + mode, persisted locally.
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'theme_presets.dart';

class ThemeController extends ChangeNotifier {
  ThemeController._();
  static final ThemeController instance = ThemeController._();

  static const _modeKey = 'theme_mode';
  static const _presetKey = 'theme_preset';

  ThemeMode _mode = ThemeMode.system;
  ThemePreset _preset = ThemePreset.material3;

  ThemeMode get mode => _mode;
  ThemePreset get preset => _preset;

  ThemeData get lightTheme => buildTheme(_preset, Brightness.light);
  ThemeData get darkTheme => buildTheme(_preset, Brightness.dark);

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    _mode = _modeFrom(prefs.getString(_modeKey));
    _preset = _presetFrom(prefs.getString(_presetKey));
    notifyListeners();
  }

  Future<void> setMode(ThemeMode mode) async {
    if (_mode == mode) return;
    _mode = mode;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_modeKey, mode.name);
  }

  Future<void> setPreset(ThemePreset preset) async {
    if (_preset == preset) return;
    _preset = preset;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_presetKey, preset.name);
  }

  static ThemeMode _modeFrom(String? raw) =>
      ThemeMode.values.firstWhere((m) => m.name == raw, orElse: () => ThemeMode.system);

  static ThemePreset _presetFrom(String? raw) =>
      ThemePreset.values.firstWhere((p) => p.name == raw, orElse: () => ThemePreset.material3);
}
