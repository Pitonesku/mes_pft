// lib/widgets/dead_man_alert.dart
// Full-screen, non-dismissible reminder overlay shown above the whole app when
// the DeadManSwitch fires. Only "Start Test" clears it.
import 'package:flutter/material.dart';

import '../dead_man_switch.dart';

/// Wraps the app and shows the reminder overlay whenever it fires.
class DeadManAlert extends StatelessWidget {
  final Widget child;
  const DeadManAlert({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: DeadManSwitch.instance,
      builder: (context, _) {
        return Stack(children: [
          child,
          if (DeadManSwitch.instance.alerting)
            const Positioned.fill(child: _ReminderOverlay()),
        ]);
      },
    );
  }
}

class _ReminderOverlay extends StatelessWidget {
  const _ReminderOverlay();

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.red.shade600.withValues(alpha: 0.96),
      child: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(32),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.alarm, color: Colors.white, size: 96),
              const SizedBox(height: 24),
              const Text('TIME FOR A MANUAL TEST',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                      color: Colors.white,
                      fontSize: 34,
                      fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              const Text('Please record a manual quality check now.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.white, fontSize: 18)),
              const SizedBox(height: 32),
              FilledButton.icon(
                style: FilledButton.styleFrom(
                  backgroundColor: Colors.white,
                  foregroundColor: Colors.red.shade700,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 40, vertical: 20),
                ),
                onPressed: DeadManSwitch.instance.startTest,
                icon: const Icon(Icons.fact_check_outlined, size: 28),
                label: const Text('Start Test',
                    style:
                        TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
