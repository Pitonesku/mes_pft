// lib/widgets/report_verification_card.dart
// Shared verification controls for production reports (used by the side drawer
// and the full-page report view).
import 'package:flutter/material.dart';

import '../api_service.dart';

/// Chip showing the report's version status: original / edited / obsolete.
class ReportStatusChip extends StatelessWidget {
  final String status;
  const ReportStatusChip(this.status, {super.key});
  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      'edited' => Colors.orange,
      'obsolete' => Colors.red,
      _ => Colors.green,
    };
    return Chip(
      label: Text(status, style: const TextStyle(fontSize: 11, color: Colors.white)),
      backgroundColor: color,
      padding: EdgeInsets.zero,
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );
  }
}

/// Dot showing the human-in-the-loop verification status.
class ReportVerificationDot extends StatelessWidget {
  final String status;
  const ReportVerificationDot(this.status, {super.key});
  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      'approved' => Colors.green,
      'rejected' => Colors.red,
      _ => Colors.amber,
    };
    final label = switch (status) {
      'approved' => 'Approved',
      'rejected' => 'Rejected',
      _ => 'Pending verification',
    };
    return Tooltip(
      message: label,
      child: Container(
        width: 10,
        height: 10,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
    );
  }
}

/// Full verification block: status chip + verification dot + (optionally)
/// Approve / Reject actions. Shows the editor when the report was edited.
class ReportVerificationCard extends StatefulWidget {
  final Map<String, dynamic> report;
  final bool canVerify;
  final VoidCallback? onVerified;
  const ReportVerificationCard({
    super.key,
    required this.report,
    required this.canVerify,
    this.onVerified,
  });
  @override
  State<ReportVerificationCard> createState() => _ReportVerificationCardState();
}

class _ReportVerificationCardState extends State<ReportVerificationCard> {
  bool _busy = false;

  Future<void> _act(String action) async {
    final rawId = widget.report['id'];
    if (rawId == null) return;
    final id = rawId is int ? rawId : int.tryParse(rawId.toString());
    if (id == null) return;

    setState(() => _busy = true);
    final ok = await ApiService.verifyReport(id, action);
    if (!mounted) return;
    setState(() => _busy = false);

    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(ok
          ? 'Report ${action == 'approve' ? 'approved' : 'rejected'}.'
          : 'Verification failed.'),
      backgroundColor: ok ? Colors.green : Colors.red,
    ));
    if (ok) widget.onVerified?.call();
  }

  @override
  Widget build(BuildContext context) {
    final report = widget.report;
    final status = (report['status'] ?? 'original').toString();
    final vStatus = (report['verification_status'] ?? 'pending').toString();
    final isApproved = vStatus == 'approved';
    final isRejected = vStatus == 'rejected';

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        ReportStatusChip(status),
        const SizedBox(width: 8),
        ReportVerificationDot(vStatus),
        const SizedBox(width: 8),
        if (report['verified_by'] != null)
          Text('by ${report['verified_by']}',
              style: const TextStyle(fontSize: 11, color: Colors.grey)),
      ]),
      if (status == 'edited' && report['edited_by'] != null) ...[
        const SizedBox(height: 6),
        Text(
          'Edited by ${report['edited_by']}'
          '${report['edited_at'] != null ? ' on ${report['edited_at']}' : ''}',
          style: const TextStyle(fontSize: 11, color: Colors.grey),
        ),
      ],
      if (widget.canVerify) ...[
        const SizedBox(height: 10),
        Row(children: [
          if (!isApproved)
            FilledButton.icon(
              onPressed: _busy ? null : () => _act('approve'),
              icon: const Icon(Icons.check, size: 16),
              label: const Text('Approve'),
              style: FilledButton.styleFrom(backgroundColor: Colors.green),
            ),
          const SizedBox(width: 8),
          if (!isRejected)
            OutlinedButton.icon(
              onPressed: _busy ? null : () => _act('reject'),
              icon: const Icon(Icons.close, size: 16),
              label: const Text('Reject'),
              style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
            ),
        ]),
      ],
    ]);
  }
}
