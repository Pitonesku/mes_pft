// shift_context.dart
// Persisted "active shift" context shared by the main report form and the
// Quality Checks screen, plus pure shift-schedule helpers.
import 'dart:convert';
import 'models.dart';

class ShiftContext {
  final int shiftId;
  final int? machineId;
  final String? machineName;
  final int? runId; // active ProductionRun id (== mo_id for QC checks)
  final String? moRef; // Manufacturing Order number
  final String? shiftName;
  final DateTime? startedAt;
  final DateTime? scheduledEndAt;

  ShiftContext({
    required this.shiftId,
    this.machineId,
    this.machineName,
    this.runId,
    this.moRef,
    this.shiftName,
    this.startedAt,
    this.scheduledEndAt,
  });

  Map<String, dynamic> toJson() => {
    'shift_id': shiftId,
    'machine_id': machineId,
    'machine_name': machineName,
    'run_id': runId,
    'mo_ref': moRef,
    'shift_name': shiftName,
    'started_at': startedAt?.toIso8601String(),
    'scheduled_end_at': scheduledEndAt?.toIso8601String(),
  };

  factory ShiftContext.fromJson(Map<String, dynamic> json) => ShiftContext(
    shiftId: json['shift_id'] as int,
    machineId: json['machine_id'] as int?,
    machineName: json['machine_name'] as String?,
    runId: json['run_id'] as int?,
    moRef: json['mo_ref'] as String?,
    shiftName: json['shift_name'] as String?,
    startedAt: json['started_at'] != null ? DateTime.tryParse(json['started_at']) : null,
    scheduledEndAt: json['scheduled_end_at'] != null ? DateTime.tryParse(json['scheduled_end_at']) : null,
  );

  static ShiftContext? fromString(String? raw) {
    if (raw == null || raw.isEmpty) return null;
    try {
      return ShiftContext.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  ShiftContext copyWith({int? runId, String? moRef, int? machineId, String? machineName}) =>
      ShiftContext(
    shiftId: shiftId,
    machineId: machineId ?? this.machineId,
    machineName: machineName ?? this.machineName,
    runId: runId ?? this.runId,
    moRef: moRef ?? this.moRef,
    shiftName: shiftName,
    startedAt: startedAt,
    scheduledEndAt: scheduledEndAt,
  );
}

int _hhmmToMin(String hhmm) {
  final parts = (hhmm.trim()).split(':');
  final h = int.tryParse(parts.isNotEmpty ? parts[0] : '') ?? 0;
  final m = int.tryParse(parts.length > 1 ? parts[1] : '') ?? 0;
  return h * 60 + m;
}

/// Resolve the shift template covering [now], allowing an early open up to 15
/// minutes before the scheduled start. Returns null outside any window.
Shift? resolveShiftForTime(DateTime now, List<Shift> shifts) {
  final nowMin = now.hour * 60 + now.minute;
  for (final s in shifts) {
    final startMin = _hhmmToMin(s.start);
    final endMin = _hhmmToMin(s.end);
    final earlyStart = startMin - 15;
    if (startMin < endMin) {
      if (nowMin >= earlyStart && nowMin < endMin) return s;
    } else {
      // Overnight shift (e.g. 22:00 -> 06:00).
      if (nowMin >= earlyStart || nowMin < endMin) return s;
    }
  }
  return null;
}

/// Scheduled end datetime of [shift], relative to [now] (handles overnight).
DateTime scheduledEndForShift(DateTime now, Shift shift) {
  final startMin = _hhmmToMin(shift.start);
  final endMin = _hhmmToMin(shift.end);
  if (startMin < endMin) {
    return DateTime(now.year, now.month, now.day, endMin ~/ 60, endMin % 60);
  }
  // Overnight shift (e.g. 22:00 -> 06:00). The end is the NEXT occurrence of the
  // end time: after the start time (or in the 15-minute early-open window before
  // it) that is tomorrow morning, otherwise (past midnight) it is today.
  // Early open at 21:50 must therefore give tomorrow 06:00, not today 06:00.
  final nowMin = now.hour * 60 + now.minute;
  final nextDay = nowMin >= endMin;
  final day = nextDay ? now.add(const Duration(days: 1)) : now;
  return DateTime(day.year, day.month, day.day, endMin ~/ 60, endMin % 60);
}

/// All shifts the operator may open *right now*: the current scheduled shift,
/// plus the next shift only once we're within its 15-minute early-open window.
List<Shift> availableShiftsForTime(DateTime now, List<Shift> shifts) {
  final nowMin = now.hour * 60 + now.minute;
  final result = <Shift>[];
  for (final s in shifts) {
    final startMin = _hhmmToMin(s.start);
    final endMin = _hhmmToMin(s.end);
    final earlyStart = startMin - 15;
    final bool inWindow;
    if (startMin < endMin) {
      inWindow = nowMin >= earlyStart && nowMin < endMin;
    } else {
      inWindow = nowMin >= earlyStart || nowMin < endMin;
    }
    if (inWindow) result.add(s);
  }
  return result;
}
