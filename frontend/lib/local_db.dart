import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import 'dart:convert';

class LocalDB {
  static final LocalDB instance = LocalDB._init();
  static Database? _database;

  LocalDB._init();

  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDB('reports.db');
    return _database!;
  }

  Future<Database> _initDB(String filePath) async {
    final dbPath = await getDatabasesPath();
    final path = join(dbPath, filePath);

    return await openDatabase(
      path,
      version: 3, // v3: add pdf_data, sync_attempts, last_sync_error columns to reports
      onCreate: (db, version) async {
        // Reports table (app data)
        await db.execute('''
          CREATE TABLE reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            report_data TEXT NOT NULL,
            pdf_data TEXT,
            sync_attempts INTEGER DEFAULT 0,
            last_sync_error TEXT,
            created_at TEXT NOT NULL
          )
        ''');

        // NEW TABLE: store Machines, POs, Shifts (AppData)
        await db.execute('''
          CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER DEFAULT 1,
            data TEXT
          )
        ''');
      },
      // If an older DB exists, run migration steps
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              version INTEGER DEFAULT 1,
              data TEXT
            )
          ''');
        }
        if (oldVersion < 3) {
          // Add new columns for offline PDF storage and sync tracking
          await db.execute('ALTER TABLE reports ADD COLUMN pdf_data TEXT');
          await db.execute('ALTER TABLE reports ADD COLUMN sync_attempts INTEGER DEFAULT 0');
          await db.execute('ALTER TABLE reports ADD COLUMN last_sync_error TEXT');
        }
      },
    );
  }

  // ==========================================
  // 1. METHODS FOR SYNCING MASTER DATA (AppData)
  // ==========================================

  Future<void> saveMasterData(int version, String jsonPayload) async {
    final db = await instance.database;
    await db.insert('settings', {
      'id': 1,
      'version': version,
      'data': jsonPayload,
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<Map<String, dynamic>?> getMasterData() async {
    final db = await instance.database;
    final result = await db.query('settings', where: 'id = 1');
    if (result.isNotEmpty) return result.first;
    return null;
  }

  // ==========================================
  // 2. METHODS FOR REPORTS
  // ==========================================

  // Delete all reports older than [days] days (keeps pending/draft reports regardless of age)
  Future<void> cleanupReportsOlderThan(int days) async {
    final db = await instance.database;
    final cutoff = DateTime.now().subtract(Duration(days: days)).toIso8601String();
    // Remove synced and cached_history reports older than cutoff
    await db.execute('''
      DELETE FROM reports 
      WHERE (status = 'synced' OR status = 'cached_history')
        AND created_at < ?
    ''', [cutoff]);
  }

  // IMPORTANT: keep only the last 30 synced reports (legacy, kept for compatibility)
  Future<void> cleanupOldReports() async {
    final db = await instance.database;
    await db.execute('''
      DELETE FROM reports 
      WHERE status = 'synced' AND id NOT IN (
        SELECT id FROM reports WHERE status = 'synced' ORDER BY id DESC LIMIT 30
      )
    ''');
  }

  // Get all reports for history
  Future<List<Map<String, dynamic>>> getAllReports() async {
    final db = await instance.database;
    return await db.query('reports', orderBy: 'created_at DESC');
  }

  // Get reports for a specific PO number
  Future<List<Map<String, dynamic>>> getReportsByPoNumber(
    String poNumber,
  ) async {
    final normalizedPo = poNumber.trim();
    final allReports = await getAllReports();
    return allReports.where((row) {
      try {
        final data =
            jsonDecode(row['report_data'] as String) as Map<String, dynamic>;
        final rowPo = data['po_number']?.toString().trim() ?? '';
        return rowPo == normalizedPo;
      } catch (_) {
        return false;
      }
    }).toList();
  }

  // Get reports pending submission
  Future<List<Map<String, dynamic>>> getPendingReports() async {
    final db = await instance.database;
    return await db.query(
      'reports',
      where: 'status = ?',
      whereArgs: ['pending'],
      orderBy: 'created_at ASC', // Send oldest first
    );
  }

  // Get reports by status (useful to find drafts)
  Future<List<Map<String, dynamic>>> getReportsByStatus(String status) async {
    final db = await instance.database;
    return await db.query(
      'reports',
      where: 'status = ?',
      whereArgs: [status],
      orderBy: 'created_at DESC',
    );
  }

  // Save report (with auto-cleanup)
  Future<int> saveReport(
    String status,
    Map<String, dynamic> reportData, {
    int? existingId,
  }) async {
    final db = await instance.database;
    final dataStr = jsonEncode(reportData);
    final now = DateTime.now().toIso8601String();
    int id;

    if (existingId != null) {
      await db.update(
        'reports',
        {'status': status, 'report_data': dataStr, 'created_at': now},
        where: 'id = ?',
        whereArgs: [existingId],
      );
      id = existingId;
    } else {
      id = await db.insert('reports', {
        'status': status,
        'report_data': dataStr,
        'created_at': now,
      });
    }

    // If we saved a synced report, enforce the 30-item limit
    if (status == 'synced') {
      await cleanupOldReports();
    }

    return id;
  }

  // Update status (e.g. 'pending' -> 'synced')
  Future<int> updateStatus(int id, String newStatus) async {
    final db = await instance.database;
    final result = await db.update(
      'reports',
      {'status': newStatus},
      where: 'id = ?',
      whereArgs: [id],
    );

    // If report just became 'synced', cleanup old synced reports
    if (newStatus == 'synced') {
      await cleanupOldReports();
    }

    return result;
  }

  // Delete report (for History)
  Future<int> deleteReport(int id) async {
    final db = await instance.database;
    return await db.delete('reports', where: 'id = ?', whereArgs: [id]);
  }

  // Save report with PDF data (for offline submissions)
  Future<int> saveReportWithPdf(
    String status,
    Map<String, dynamic> reportData, {
    String? pdfBase64,
    int? existingId,
  }) async {
    final db = await instance.database;
    final dataStr = jsonEncode(reportData);
    final now = DateTime.now().toIso8601String();
    int id;

    if (existingId != null) {
      await db.update(
        'reports',
        {
          'status': status,
          'report_data': dataStr,
          'pdf_data': pdfBase64,
          'created_at': now,
        },
        where: 'id = ?',
        whereArgs: [existingId],
      );
      id = existingId;
    } else {
      id = await db.insert('reports', {
        'status': status,
        'report_data': dataStr,
        'pdf_data': pdfBase64,
        'created_at': now,
      });
    }

    if (status == 'synced') {
      await cleanupOldReports();
    }

    return id;
  }

  // Get report with its PDF data
  Future<Map<String, dynamic>?> getReportWithPdf(int id) async {
    final db = await instance.database;
    final results = await db.query('reports', where: 'id = ?', whereArgs: [id]);
    if (results.isNotEmpty) return results.first;
    return null;
  }

  // Increment sync attempts and record error
  Future<void> incrementSyncAttempts(int id, String error) async {
    final db = await instance.database;
    await db.rawUpdate(
      'UPDATE reports SET sync_attempts = sync_attempts + 1, last_sync_error = ? WHERE id = ?',
      [error, id],
    );
  }

  // Mark report as synced and optionally clear PDF data
  Future<void> markReportSynced(int id) async {
    final db = await instance.database;
    await db.update(
      'reports',
      {
        'status': 'synced',
        'sync_attempts': 0,
        'last_sync_error': null,
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    await cleanupOldReports();
  }
}
