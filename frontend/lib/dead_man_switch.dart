// lib/dead_man_switch.dart
// In-app "dead man's switch" reminder for manual QC tests.
//
// - Foreground: a 1s ticker fires at the target time, raises the full-screen
//   overlay, loops a loud alarm sound and pulses haptic.
// - Background / killed: an exact OS-scheduled notification (AlarmManager via
//   flutter_local_notifications) fires at the same target time, so the operator
//   is alerted even when the app is minimised.
import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import 'utils/logger.dart';

class DeadManSwitch extends ChangeNotifier {
  DeadManSwitch._();
  static final DeadManSwitch instance = DeadManSwitch._();

  static const int _notificationId = 1001;
  static const String _channelId = 'dead_man_switch';
  static const String _channelName = 'Manual test reminders';
  static const String _channelDescription =
      'Loud alerts when a manual quality test is due.';

  final FlutterLocalNotificationsPlugin _notifications =
      FlutterLocalNotificationsPlugin();
  final AudioPlayer _audio = AudioPlayer();

  Timer? _ticker;
  Timer? _alarmTimer;
  int? _intervalSeconds; // null = disabled
  DateTime? _target;
  bool _alerting = false;
  bool _configured = false;

  /// Invoked when the operator taps "Start Test" (overlay or notification).
  VoidCallback? onStartTest;

  bool get isArmed => _intervalSeconds != null && _intervalSeconds! > 0;
  bool get alerting => _alerting;

  /// One-time setup (timezone + notification channel). Called from main().
  Future<void> configure() async {
    if (_configured) return;
    _configured = true;
    try {
      tzdata.initializeTimeZones();
      await _notifications.initialize(
        const InitializationSettings(
          android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        ),
        onDidReceiveNotificationResponse: (_) => _onNotificationTap(),
      );
      await _requestPermission();
      AppLog.i('[DeadManSwitch] configured');
    } catch (e) {
      AppLog.w('[DeadManSwitch] configure failed: $e');
    }
  }

  Future<void> _requestPermission() async {
    try {
      await _notifications
          .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin>()
          ?.requestNotificationsPermission();
    } catch (_) {}
  }

  void _onNotificationTap() {
    onStartTest?.call();
  }

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
      _cancelNotification();
      AppLog.i('[DeadManSwitch] disarmed');
      notifyListeners();
      return;
    }
    _intervalSeconds = mins * 60;
    _resetTarget();
    _scheduleNotification(_target!);
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
    AppLog.i('[DeadManSwitch] armed interval=$_intervalSeconds s target=$_target');
    notifyListeners();
  }

  /// Reset the countdown back to the full interval (manual test submitted).
  void reset() {
    if (!isArmed) return;
    _resetTarget();
    _scheduleNotification(_target!);
    AppLog.i('[DeadManSwitch] reset -> target=$_target');
  }

  /// Stop the reminder entirely (shift closed / logout).
  void disarm() => arm(null);

  /// "Start Test" — stop the alarm and hand off to the owner's callback.
  void startTest() {
    _stopAlarm();
    _alerting = false;
    if (isArmed) {
      _resetTarget();
      _scheduleNotification(_target!);
    }
    AppLog.i('[DeadManSwitch] startTest -> target=$_target');
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
    AppLog.i('[DeadManSwitch] ALARM FIRED at ${DateTime.now()}');
    notifyListeners();
    try {
      _startAlarm();
    } catch (e) {
      AppLog.w('[DeadManSwitch] _startAlarm failed: $e');
    }
  }

  void _startAlarm() {
    _stopAlarm();
    _playSound();
    // Aggressive pulsing alert: audio loop + haptic every 1.5s.
    _alarmTimer =
        Timer.periodic(const Duration(milliseconds: 1500), (_) => _pulse());
  }

  Future<void> _playSound() async {
    try {
      await _audio.setReleaseMode(ReleaseMode.loop);
      await _audio.play(AssetSource('sounds/alarm_beep.wav'), volume: 1.0);
    } catch (e) {
      AppLog.w('[DeadManSwitch] audio failed: $e');
    }
  }

  void _pulse() {
    SystemSound.play(SystemSoundType.alert);
    HapticFeedback.vibrate();
  }

  void _stopAlarm() {
    _alarmTimer?.cancel();
    _alarmTimer = null;
    try {
      _audio.stop();
    } catch (_) {}
  }

  Future<void> _scheduleNotification(DateTime target) async {
    await _cancelNotification();
    try {
      final scheduledAt = tz.TZDateTime.from(target.toUtc(), tz.UTC);
      await _notifications.zonedSchedule(
        _notificationId,
        'Manual test due',
        'Time to run a manual quality check.',
        scheduledAt,
        const NotificationDetails(
          android: AndroidNotificationDetails(
            _channelId,
            _channelName,
            channelDescription: _channelDescription,
            importance: Importance.max,
            priority: Priority.max,
            playSound: true,
            enableVibration: true,
            fullScreenIntent: true,
            category: AndroidNotificationCategory.alarm,
          ),
        ),
        uiLocalNotificationDateInterpretation:
            UILocalNotificationDateInterpretation.absoluteTime,
        androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
      );
      AppLog.i('[DeadManSwitch] notification scheduled for $target');
    } catch (e) {
      AppLog.w('[DeadManSwitch] notification schedule failed: $e');
    }
  }

  Future<void> _cancelNotification() async {
    try {
      await _notifications.cancel(_notificationId);
    } catch (_) {}
  }
}
