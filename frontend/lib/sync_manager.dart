import 'dart:convert';
import 'local_db.dart';
import 'api_service.dart';
import 'utils/logger.dart'; // <--- Make sure to import our logger

class SyncManager {
  static bool _isSyncing = false;

  static Future<void> syncReports() async {
    // If a sync is already running, don't start another in parallel
    if (_isSyncing) return;
    _isSyncing = true;

    try {
      AppLog.d("🔄 Checking for pending reports in SQLite..."); // d - Debug
      final pending = await LocalDB.instance.getPendingReports();

      if (pending.isEmpty) {
        AppLog.i("✅ No pending reports."); // i - Info (Информация)
        _isSyncing = false;
        return;
      }

      AppLog.i("📤 Found ${pending.length} reports. Starting upload...");

      for (var row in pending) {
        final int id = row['id'];
        final String? payloadStr = row['report_data'];
        final String? pdfBase64 = row['pdf_data'] as String?;
        
        if (payloadStr == null || payloadStr.isEmpty) {
          AppLog.e("⚠️ Report $id has empty report_data. Deleting.");
          await LocalDB.instance.deleteReport(id);
          continue;
        }
        
        final Map<String, dynamic> payload = jsonDecode(payloadStr);

        // Build PDF filename
        final dateStr = payload['report_date']?.toString() ?? '';
        final po = (payload['po_number'] ?? 'PO').toString().replaceAll(RegExp(r'[^\w]'), '_');
        final machine = (payload['machine_name'] ?? 'Machine').toString().replaceAll(RegExp(r'[^\w]'), '_');
        final shift = (payload['shift_name'] ?? 'Shift').toString().replaceAll(RegExp(r'[^\w]'), '_');
        final fileName = '${dateStr}_${po}_${machine}_$shift.pdf';

        // Try to sync report + PDF to server
        final result = await ApiService.syncReport(
          reportData: payload,
          pdfBase64: pdfBase64,
          pdfFilename: fileName,
        );

        if (result != null) {
          // Successfully synced to server
          await LocalDB.instance.markReportSynced(id);
          AppLog.i("✅ Report $id synced (data + PDF) and marked as synced locally.");
        } else {
          // If server is still unreachable — stop and try later
          AppLog.w("🛑 Server still unreachable. Stopping sync.");
          await LocalDB.instance.incrementSyncAttempts(id, "Server unreachable");
          break;
        }
      }
    } catch (e, stackTrace) {
      // e - Error. Pass the error and stackTrace for diagnostics
      AppLog.e("⚠️ Sync error occurred", error: e, stackTrace: stackTrace); 
    } finally {
      _isSyncing = false;
    }
  }

  /// Sync users from server
  static Future<List<dynamic>?> syncUsers() async {
    try {
      AppLog.i("👥 Syncing users from server...");
      final users = await ApiService.fetchUsers();
      
      if (users == null) {
        AppLog.w("⚠️ Could not fetch users from server");
        return null;
      }

      AppLog.i("✅ Successfully synced ${users.length} users from server");
      return users;
    } catch (e, stackTrace) {
      AppLog.e("❌ Error syncing users", error: e, stackTrace: stackTrace);
      return null;
    }
  }
}
