// lib/dead_man_switch.dart
// In-app "dead man's switch" reminder for manual QC tests. A foreground
// countdown that resets on every manual-test submission and raises an
// aggressive alert overlay when the operator forgets to test. Runs entirely
// inside the Flutter app (never the native Android Clock app).
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class DeadManSwitch extends ChangeNotifier {
  DeadManSwitch._();
  static final DeadManSwitch instance = DeadManSwitch._();

  Timer? _ticker;
  Timer? _alarmTimer;
  int? _intervalSeconds; // null = disabled
  DateTime? _target;
  bool _alerting = false;

  /// Invoked when the operator taps "Start Test" on the alert overlay.
  VoidCallback? onStartTest;

  bool get isArmed => _intervalSeconds != null && _intervalSeconds! > 0;
  bool get alerting => _alerting;

  /// Arm / re-arm the countdown. Pass null or <= 0 to fully disable.
  void arm(int? intervalMinutes) {
    _stopAlarm();
    _ticker?.cancel();
    _ticker = null;
    _alerting = false;
    final mins = intervalMinutes;
    if (mins == null || mins <= 0) {
      _intervalSeconds = null;
      _target = null;
      notifyListeners();
      return;
    }
    _intervalSeconds = mins * 60;
    _resetTarget();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
    notifyListeners();
  }

  /// Reset the countdown back to the full interval (manual test submitted).
  void reset() {
    if (!isArmed) return;
    _resetTarget();
  }

  /// Stop the reminder entirely (shift closed / logout).
  void disarm() => arm(null);

  /// "Start Test" — stop the alarm and hand off to the owner's callback.
  void startTest() {
    _stopAlarm();
    _alerting = false;
    notifyListeners();
    onStartTest?.call();
  }

  void _resetTarget() {
    _target = DateTime.now().add(Duration(seconds: _intervalSeconds!));
  }

  void _tick() {
    if (!isArmed || _target == null || _alerting) return;
    if (DateTime.now().isBefore(_target!)) return;
    _alerting = true;
    notifyListeners();
    _startAlarm();
  }

  void _startAlarm() {
    _stopAlarm();
    _pulse();
    // Aggressive pulsing alert: system alert tone + haptic every 1.5s.
    _alarmTimer =
        Timer.periodic(const Duration(milliseconds: 1500), (_) => _pulse());
  }

  void _pulse() {
    SystemSound.play(SystemSoundType.alert);
    HapticFeedback.vibrate();
  }

  void _stopAlarm() {
    _alarmTimer?.cancel();
    _alarmTimer = null;
  }
}
