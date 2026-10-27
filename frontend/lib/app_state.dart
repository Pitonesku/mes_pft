// app_state.dart
import 'models.dart';
import 'api_service.dart';
import 'local_db.dart';
import 'sync_manager.dart';
import 'utils/logger.dart';
import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

class AppData {
  // --- LOCAL / TEST DATA (Fallback) ---
  
  // NOTE: no hardcoded superadmin here. Demo users are for offline *data* only;
  // authentication is always performed by the server (see auth_screen.dart), so
  // these rows can never establish a session.
  static List<User> users = [
    User(name: "Maximus", password: "123", email: "max@factory.com", role: UserRole.manager, canModifyPO: true),
    User(name: "Operator J.", password: "456", email: "worker@factory.com", role: UserRole.operator),
  ];
  
  static List<Shift> shifts = [
    Shift(name: "Shift 1", start: "06:00", end: "14:00"),
    Shift(name: "Shift 2", start: "14:00", end: "22:00"),
    Shift(name: "Shift 3", start: "22:00", end: "06:00"),
  ];

  static List<Machine> machines = [
    Machine(name: "Machine #1", remarks: "Main line"),
    Machine(name: "Machine #2"),
    Machine(name: "Machine #3", isInactive: true, remarks: "Under maintenance"),
  ];

  static List<RawMaterial> materialDictionary = [
    RawMaterial(category: MaterialCategory.acetate, type: "Standard 3.0Y/32k", batch: "ACT-001"),
    RawMaterial(category: MaterialCategory.paper, type: "Porous 6000CU"),
    RawMaterial(category: MaterialCategory.hotMelt, type: "HM-801"),
    RawMaterial(category: MaterialCategory.coldGlue, type: "PVA-White"),
    RawMaterial(category: MaterialCategory.triacetin, type: "T-99"),
  ];

  static List<PurchaseOrder> activePOs = [
    PurchaseOrder(
      poNumber: "PO-2026-001", createdAt: DateTime(2026, 5, 1),
      diameter: 7.72, length: 108, pd: 325, cu: 6000, weight: 0.85, boxType: 6000,
      acetateType: "Standard 3.0Y/32k", paperType: "Porous 6000CU", 
      hmGlueType: "HM-801", pvaGlueType: "PVA-White", triacetinType: "T-99",
      targetQty: 5000000, producedQty: 1200000,
    ),
  ];

  static Set<String> submittedReports = {}; 
  static const String _pendingSetupKey = 'pending_setup_changes';

  /// True when the app is showing the built-in fallback/demo data because the
  /// server is unreachable and no cached data exists. Drives the
  /// "Offline - limited data" banner.
  static bool usingFallbackData = true;


  static Future<void> saveMachinesCache() async {
    final prefs = await SharedPreferences.getInstance();
    prefs.setString('cache_machines', jsonEncode(machines.map((m) => m.toJson()).toList()));
  }

  static Future<void> saveShiftsCache() async {
    final prefs = await SharedPreferences.getInstance();
    prefs.setString('cache_shifts', jsonEncode(shifts.map((s) => s.toJson()).toList()));
  }

  static Future<void> enqueueSetupChange(
    String type,
    String action,
    Map<String, dynamic> data, {
    String? oldName,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    final currentQueue = prefs.getStringList(_pendingSetupKey) ?? [];
    final payload = jsonEncode({
      'type': type,
      'action': action,
      'old_name': oldName,
      'data': data,
    });
    currentQueue.add(payload);
    await prefs.setStringList(_pendingSetupKey, currentQueue);
  }

  static Future<bool> syncPendingSetupChanges() async {
    final prefs = await SharedPreferences.getInstance();
    final pending = prefs.getStringList(_pendingSetupKey) ?? [];
    if (pending.isEmpty) return true;

    AppLog.i("🔄 Syncing ${pending.length} pending machine/shift changes...");

    final List<String> remaining = [];
    for (final raw in pending) {
      final item = jsonDecode(raw) as Map<String, dynamic>;
      final type = item['type'] as String;
      final action = item['action'] as String;
      final oldName = item['old_name'] as String?;
      final data = item['data'] as Map<String, dynamic>;

      bool success = false;

      if (type == 'machine') {
        final machine = Machine.fromJson(data);
        if (action == 'add') {
          success = await ApiService.addMachine(machine);
        } else if (action == 'update') {
          success = await ApiService.updateMachine(oldName ?? machine.name, machine);
        } else if (action == 'delete') {
          success = await ApiService.deleteMachine(oldName ?? machine.name);
        }
      } else if (type == 'shift') {
        final shift = Shift.fromJson(data);
        if (action == 'add') {
          success = await ApiService.addShift(shift);
        } else if (action == 'update') {
          success = await ApiService.updateShift(oldName ?? shift.name, shift);
        } else if (action == 'delete') {
          success = await ApiService.deleteShift(oldName ?? shift.name);
        }
      }

      if (!success) {
        AppLog.w("⚠️ Failed to sync pending $type ($action): ${oldName ?? data['name']}");
        remaining.add(raw);
        break;
      }
    }

    await prefs.setStringList(_pendingSetupKey, remaining);
    return remaining.isEmpty;
  }

  // --- УМНАЯ СИНХРОНИЗАЦИЯ С КЭШЕМ ---
  static Future<bool> loadDataFromServer({bool forceSync = false}) async {
    final prefs = await SharedPreferences.getInstance();

    // 1. QUICK LOAD FROM CACHE
    if (!forceSync) {
      String? cachedMachines = prefs.getString('cache_machines');
      String? cachedPOs = prefs.getString('cache_pos');
      String? cachedUsers = prefs.getString('cache_users');
      String? cachedMaterials = prefs.getString('cache_materials');
      String? cachedShifts = prefs.getString('cache_shifts');

      if (cachedMachines != null) {
        Iterable l = jsonDecode(cachedMachines);
        machines = l.map((m) => Machine.fromJson(m)).toList();
      }
      if (cachedPOs != null) {
        Iterable l = jsonDecode(cachedPOs);
        activePOs = l.map((po) => PurchaseOrder.fromJson(po)).toList();
      }
      if (cachedUsers != null) {
        Iterable l = jsonDecode(cachedUsers);
        users = l.map((u) => User.fromJson(u)).toList();
      }
      if (cachedMaterials != null) {
        Iterable l = jsonDecode(cachedMaterials);
        // Исправлено: используем RawMaterial
        materialDictionary = l.map((m) => RawMaterial.fromJson(m)).toList();
      }
      if (cachedShifts != null) {
        Iterable l = jsonDecode(cachedShifts);
        shifts = l.map((s) => Shift.fromJson(s)).toList();
      }
      
      AppLog.d("📦 Local cache loaded.");
      await syncPendingSetupChanges();

      if (cachedMachines != null ||
          cachedPOs != null ||
          cachedUsers != null ||
          cachedMaterials != null ||
          cachedShifts != null) {
        usingFallbackData = false;
      }
    }

    // 2. CHECK SERVER VERSION
    String localVersion = prefs.getString('data_version') ?? "none";
    String? serverVersion = await ApiService.fetchServerVersion();

    if (serverVersion == null) {
      AppLog.d("🌐 Server unavailable. Using local cache.");
      return false;
    }

    if (serverVersion == localVersion && !forceSync) {
      AppLog.d("✅ Data up-to-date (Version: $localVersion).");
      return true;
    }

    AppLog.i("🔄 New version found ($serverVersion). Downloading updates...");

    // 3. DOWNLOAD NEW DATA
    try {
      final machinesJson = await ApiService.fetchMachines();
      if (machinesJson != null) {
        machines = machinesJson.map((m) => Machine.fromJson(m)).toList();
        machines.sort((a, b) => a.name.compareTo(b.name));
        prefs.setString('cache_machines', jsonEncode(machinesJson));
      }

      final poJson = await ApiService.fetchPurchaseOrders();
      if (poJson != null) {
        activePOs = poJson.map((po) => PurchaseOrder.fromJson(po)).toList();
        prefs.setString('cache_pos', jsonEncode(poJson));
      }

      // Используем новый endpoint для синхронизации пользователей
      final usersJson = await ApiService.fetchUsersSync();
      if (usersJson != null) {
        // If server returned an empty list, DO NOT overwrite local admins
        if (usersJson.isEmpty) {
          AppLog.d("⚠️ Server returned empty user list; keeping local admins.");
        } else {
          users = usersJson.map((u) => User.fromJson(u)).toList();
          prefs.setString('cache_users', jsonEncode(usersJson));
        }
      }

      final materialsJson = await ApiService.fetchMaterials();
      if (materialsJson != null) {
        // Исправлено: используем RawMaterial
        materialDictionary = materialsJson.map((m) => RawMaterial.fromJson(m)).toList();
        prefs.setString('cache_materials', jsonEncode(materialsJson));
      }

      final shiftsJson = await ApiService.fetchShifts();
      if (shiftsJson != null) {
        shifts = shiftsJson.map((s) => Shift.fromJson(s)).toList();
        prefs.setString('cache_shifts', jsonEncode(shiftsJson));
      }

      prefs.setString('data_version', serverVersion);
      usingFallbackData = false;
      AppLog.i("🎉 Cache successfully updated to version $serverVersion!");

      // Cleanup local DB: remove synced/cached reports older than 5 days
      try {
        await LocalDB.instance.cleanupReportsOlderThan(5);
        AppLog.d("🧹 Local DB cleaned: removed reports older than 5 days.");
      } catch (e) {
        AppLog.w("⚠️ Local DB cleanup failed: $e");
      }

      // Trigger sync of pending reports when network is available
      try {
        await SyncManager.syncReports();
      } catch (e) {
        AppLog.d("Sync trigger after data load skipped: $e");
      }

      return true;
    } catch (e) {
      AppLog.i("❌ Download error: $e");
      return false;
    }
  }
}
