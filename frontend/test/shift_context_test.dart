import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:production_app/models.dart';
import 'package:production_app/shift_context.dart';

void main() {
  final night = Shift(name: 'Night', start: '22:00', end: '06:00');
  final day = Shift(name: 'Day', start: '06:00', end: '14:00');

  group('scheduledEndForShift', () {
    test('day shift ends the same day', () {
      final end = scheduledEndForShift(DateTime(2026, 10, 10, 7, 30), day);
      expect(end, DateTime(2026, 10, 10, 14, 0));
    });

    test('overnight shift opened 15 min early ends TOMORROW morning', () {
      // Regression: this used to return today 06:00 (already in the past), so the
      // auto-close sweep closed the brand-new shift within a minute.
      final end = scheduledEndForShift(DateTime(2026, 10, 10, 21, 50), night);
      expect(end, DateTime(2026, 10, 11, 6, 0));
    });

    test('overnight shift opened at its start ends tomorrow morning', () {
      final end = scheduledEndForShift(DateTime(2026, 10, 10, 22, 5), night);
      expect(end, DateTime(2026, 10, 11, 6, 0));
    });

    test('overnight shift opened after midnight ends the same morning', () {
      final end = scheduledEndForShift(DateTime(2026, 10, 11, 2, 0), night);
      expect(end, DateTime(2026, 10, 11, 6, 0));
    });

    test('the end is always in the future for any open time inside the window', () {
      for (var minute = 0; minute < 24 * 60; minute += 5) {
        final now = DateTime(2026, 10, 10, minute ~/ 60, minute % 60);
        final shift = resolveShiftForTime(now, [day, night]);
        if (shift == null) continue;
        expect(scheduledEndForShift(now, shift).isAfter(now), isTrue,
            reason: 'open at $now on ${shift.name}');
      }
    });
  });

  group('ShiftContext.copyWith', () {
    test('machine change keeps shift identity and updates machine + MO', () {
      final ctx = ShiftContext(
          shiftId: 7, machineId: 1, machineName: 'M1', runId: 10, moRef: 'A');
      final moved = ctx.copyWith(
          runId: 11, moRef: 'A', machineId: 2, machineName: 'M2');
      expect(moved.shiftId, 7);
      expect((moved.machineId, moved.machineName, moved.runId), (2, 'M2', 11));
    });

    test('survives a JSON round trip', () {
      final ctx = ShiftContext(
          shiftId: 7, machineId: 1, machineName: 'M1', runId: 10, moRef: 'A');
      final back = ShiftContext.fromString(jsonEncode(ctx.toJson()));
      expect(back?.shiftId, 7);
      expect(back?.runId, 10);
      expect(back?.machineName, 'M1');
    });
  });
}
