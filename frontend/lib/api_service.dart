import 'dart:convert';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'utils/logger.dart';
import 'models.dart';
import 'http_client_wrapper.dart';

class ApiService {
  /// SharedPreferences key where the configured server base URL is stored.
  static const String _baseUrlPrefKey = 'server_base_url';

  /// Default fallback URL used when no URL has been saved yet.
  static const String _defaultBaseUrl = "http://10.10.0.202:8000/api";

  /// Android/desktop: absolute URL to the backend server.
  /// This is mutable so it can be updated at runtime via [reinitialize].
  static String baseUrl = _defaultBaseUrl;

  /// Web: relative path so the browser hits the same origin
  /// the Flutter web app is served from (the FastAPI server).
  static String get effectiveBaseUrl => kIsWeb ? '/api' : baseUrl;

  static final http.Client _httpClient = createLoggingHttpClient();

  /// In-memory bearer token obtained from a successful login.
  static String? authToken;

  static const String _authTokenPrefKey = 'auth_token';

  /// Load the cached bearer token (if any) on app startup.
  static Future<void> loadSavedAuthToken() async {
    final prefs = await SharedPreferences.getInstance();
    authToken = prefs.getString(_authTokenPrefKey);
  }

  /// Persist the bearer token after a successful login.
  static Future<void> _saveAuthToken(String token) async {
    authToken = token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_authTokenPrefKey, token);
  }

  static const String _userPrefKey = 'auth_user';

  /// Persist the authenticated user so the session can be restored on reload.
  static Future<void> saveUser(User user) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_userPrefKey, jsonEncode({
      'username': user.name,
      'email': user.email,
      'role_id': _roleIdFor(user.role),
      'is_inactive': user.isInactive,
    }));
  }

  /// Load the persisted user (or null when no session was saved).
  static Future<User?> loadSavedUser() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_userPrefKey);
      if (raw != null && raw.isNotEmpty) {
        return User.fromJson(jsonDecode(raw) as Map<String, dynamic>);
      }
    } catch (_) {}
    return null;
  }

  /// Wipe the stored session (token + user) — used by logout.
  static Future<void> clearSession() async {
    authToken = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_authTokenPrefKey);
    await prefs.remove(_userPrefKey);
  }

  static int _roleIdFor(UserRole role) => switch (role) {
        UserRole.superAdmin => 1,
        UserRole.manager => 2,
        UserRole.operator => 3,
      };

  /// Build the standard headers for authenticated JSON requests.
  static Map<String, String> _authHeaders() => {
    'Content-Type': 'application/json',
    if (authToken != null && authToken!.isNotEmpty)
      'Authorization': 'Bearer $authToken',
  };

  /// Load the saved server URL from SharedPreferences on app startup.
  /// Falls back to [_defaultBaseUrl] if nothing has been saved yet.
  static Future<void> loadSavedBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_baseUrlPrefKey);
    if (saved != null && saved.isNotEmpty) {
      baseUrl = saved;
      AppLog.i("🌐 Loaded saved server URL: $baseUrl");
    } else {
      AppLog.i("🌐 No saved server URL found. Using default: $baseUrl");
    }
  }

  /// Update the base URL at runtime and persist it to SharedPreferences.
  static Future<void> reinitialize(String newBaseUrl) async {
    baseUrl = newBaseUrl;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_baseUrlPrefKey, newBaseUrl);
    AppLog.i("🔧 ApiService re-initialized with new URL: $baseUrl");
  }

  /// Returns true if a server URL has already been saved in SharedPreferences.
  static Future<bool> isServerConfigured() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_baseUrlPrefKey);
    return saved != null && saved.isNotEmpty;
  }

  // --- REPORT SUBMISSION ---
  static Future<bool> submitProductionReport(
    Map<String, dynamic> reportData,
  ) async {
    try {
      final response = await _httpClient.post(
        Uri.parse('$effectiveBaseUrl/reports'),
        headers: _authHeaders(),
        body: jsonEncode(reportData),
      );

      if (response.statusCode == 200 || response.statusCode == 201) {
        AppLog.i("Report successfully sent to server!");
        return true;
      } else {
        AppLog.e(
          "Server error sending report: ${response.statusCode} - ${response.body}",
        );
        return false;
      }
    } catch (e) {
      AppLog.w("No connection to server (offline). Report not sent.");
      return false;
    }
  }

  // --- VERSION SYNC ---
  static Future<String?> fetchServerVersion() async {
    try {
      AppLog.i("🔄 Checking server version at $effectiveBaseUrl/version");
      final response = await _httpClient
          .get(Uri.parse('$effectiveBaseUrl/version'))
          .timeout(const Duration(seconds: 3));
      if (response.statusCode == 200) {
        return jsonDecode(response.body)['version'];
      }
    } catch (e) {
      return null;
    }
    return null;
  }

  // --- AUTHENTICATION & LOGIN ---
  static Future<Map<String, dynamic>?> login(
    String username,
    String password,
  ) async {
    try {
      AppLog.i("🔐 Attempting login for user: $username at $effectiveBaseUrl/auth/login");
      final response = await _httpClient
          .post(
            Uri.parse('$effectiveBaseUrl/auth/login'),
            headers: _authHeaders(),
            body: jsonEncode({'username': username, 'password': password}),
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final token = data['access_token'];
        if (token is String && token.isNotEmpty) {
          await _saveAuthToken(token);
        }
        AppLog.i("✅ Login successful for $username");
        return data;
      } else {
        AppLog.e("❌ Login failed: ${response.statusCode} - ${response.body}");
        return null;
      }
    } catch (e) {
      AppLog.e("❌ Login error", error: e);
      return null;
    }
  }

  // --- USERS SYNC ---
  static Future<List<dynamic>?> fetchUsersSync() async {
    try {
      AppLog.i("👥 Fetching users for sync from $effectiveBaseUrl/users-sync");
      final response = await _httpClient
          .get(Uri.parse('$effectiveBaseUrl/users-sync'), headers: _authHeaders())
          .timeout(const Duration(seconds: 5));
      if (response.statusCode == 200) {
        final users = jsonDecode(response.body) as List<dynamic>;
        AppLog.i("✅ Fetched ${users.length} users");
        return users;
      }
      AppLog.w("⚠️ Failed to fetch users: ${response.statusCode}");
      return null;
    } catch (e) {
      AppLog.e("❌ Error fetching users", error: e);
      return null;
    }
  }

  // --- DATA RETRIEVAL (GET) ---

  static Future<Map<String, dynamic>?> getPoAudit(int poId) async {
    try {
      final response = await _httpClient.get(
        Uri.parse('$effectiveBaseUrl/stats/po-audit/$poId'),
      );
      if (response.statusCode == 200) {
        // Return parsed JSON (Map)
        return jsonDecode(response.body);
      }
      return null;
    } catch (e) {
      AppLog.e("Error fetching PO audit: $e");
      return null;
    }
  }

  static Future<List<dynamic>?> fetchMachines() async {
    try {
      final response = await _httpClient.get(Uri.parse('$effectiveBaseUrl/machines'));
      if (response.statusCode == 200) return jsonDecode(response.body);
      return null;
    } catch (e) {
      AppLog.e("Error fetching machines: $e");
      return null;
    }
  }

  static Future<List<dynamic>?> fetchPurchaseOrders() async {
    try {
      final response = await _httpClient.get(Uri.parse('$effectiveBaseUrl/purchase-orders'));
      if (response.statusCode == 200) return jsonDecode(response.body);
      return null;
    } catch (e) {
      AppLog.e("Error fetching purchase orders: $e");
      return null;
    }
  }

  /// Fetch the most recent report for a given machine from the server.
  /// Used by the "copy from previous report" feature to work across all devices.
  /// Uses a query parameter to safely handle machine names with special chars (#, /, spaces).
  static Future<Map<String, dynamic>?> fetchLastReportByMachine(String machineName) async {
    try {
      final uri = Uri.parse('$effectiveBaseUrl/reports/last-by-machine')
          .replace(queryParameters: {'machine_name': machineName});
      final response = await _httpClient
          .get(uri)
          .timeout(const Duration(seconds: 5));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.w("Could not fetch last report for machine $machineName: $e");
      return null;
    }
  }

  /// Fetch a single production report by id (full detail with material lists).
  static Future<Map<String, dynamic>?> fetchReport(int id) async {
    try {
      final response = await _httpClient
          .get(Uri.parse('$effectiveBaseUrl/reports/$id'), headers: _authHeaders())
          .timeout(const Duration(seconds: 20));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.e("Error fetching report $id: $e");
      return null;
    }
  }

  static Future<List<dynamic>?> fetchReports({
    required DateTime startDate,
    required DateTime endDate,
  }) async {
    try {
      final start = startDate.toIso8601String().split('T').first;
      final end = endDate.toIso8601String().split('T').first;
      final response = await _httpClient.get(
        Uri.parse('$effectiveBaseUrl/reports?start_date=$start&end_date=$end'),
      );
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as List<dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.e("Error fetching reports: $e");
      return null;
    }
  }

  static Future<List<dynamic>?> fetchMaterials() async {
    try {
      final response = await _httpClient.get(Uri.parse('$effectiveBaseUrl/materials'));
      if (response.statusCode == 200) return jsonDecode(response.body);
      return null;
    } catch (e) {
      AppLog.e("Error fetching materials: $e");
      return null;
    }
  }

  static Future<List<dynamic>?> fetchUsers() async {
    try {
      final response = await _httpClient.get(
        Uri.parse('$effectiveBaseUrl/users'),
        headers: _authHeaders(),
      );
      if (response.statusCode == 200) return jsonDecode(response.body);
      return null;
    } catch (e) {
      AppLog.e("Error fetching users: $e");
      return null;
    }
  }

  static Future<List<dynamic>?> fetchShifts() async {
    try {
      final response = await _httpClient.get(Uri.parse('$effectiveBaseUrl/shifts'));
      if (response.statusCode == 200) return jsonDecode(response.body);
      return null;
    } catch (e) {
      AppLog.e("Error fetching shifts: $e");
      return null;
    }
  }

  // --- ОТПРАВКА ДАННЫХ НА СЕРВЕР (POST/CREATE) ---

  // 1. Добавить станок
  static Future<bool> addMachine(Machine machine) async {
    try {
      final response = await http.post(
        Uri.parse('$effectiveBaseUrl/machines'),
        headers: _authHeaders(),
        body: jsonEncode(machine.toJson()),
      );
      return response.statusCode == 200 || response.statusCode == 201;
    } catch (e) {
      AppLog.e("Error adding machine: $e");
      return false;
    }
  }

  static Future<bool> updateMachine(String oldName, Machine machine) async {
    try {
      final response = await http.put(
        Uri.parse('$effectiveBaseUrl/machines/${Uri.encodeComponent(oldName)}'),
        headers: _authHeaders(),
        body: jsonEncode(machine.toJson()),
      );
      return response.statusCode == 200;
    } catch (e) {
      AppLog.e("Error updating machine: $e");
      return false;
    }
  }

  static Future<bool> deleteMachine(String name) async {
    try {
      final response = await http.delete(
        Uri.parse('$effectiveBaseUrl/machines/${Uri.encodeComponent(name)}'),
      );
      return response.statusCode == 200 || response.statusCode == 204;
    } catch (e) {
      AppLog.e("Error deleting machine: $e");
      return false;
    }
  }

  // --- ЗАКАЗЫ (PO) ---

  static Future<PurchaseOrder?> addPurchaseOrder(PurchaseOrder po) async {
    try {
      final response = await http.post(
        Uri.parse('$effectiveBaseUrl/purchase-orders'),
        headers: _authHeaders(),
        body: jsonEncode(po.toJson()),
      );

      // If server created the PO successfully
      if (response.statusCode == 200 || response.statusCode == 201) {
        // Read server response (our PO with new ID)
        final Map<String, dynamic> responseData = jsonDecode(response.body);
        // Convert JSON back into Dart object and return it
        return PurchaseOrder.fromJson(responseData);
      } else {
        return null; // Server returned an error
      }
    } catch (e) {
      return null; // Network error (no internet, etc.)
    }
  }

  static Future<bool> updatePurchaseOrder(int id, PurchaseOrder po) async {
    try {
      final response = await http.put(
        Uri.parse('$effectiveBaseUrl/purchase-orders/$id'),
        headers: _authHeaders(),
        body: jsonEncode(po.toJson()),
      );
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  static Future<bool> deletePurchaseOrder(int id) async {
    try {
      final response = await http.delete(
        Uri.parse('$effectiveBaseUrl/purchase-orders/$id'),
        headers: _authHeaders(),
      );
      return response.statusCode == 200 || response.statusCode == 204;
    } catch (e) {
      return false;
    }
  }

  // 3. Добавить Материал
  static Future<bool> addMaterial(RawMaterial material) async {
    try {
      final body = jsonEncode(material.toJson());
      // print("SENDING: $body"); // Check payload

      final response = await http.post(
        Uri.parse('$effectiveBaseUrl/materials'),
        headers: _authHeaders(),
        body: body,
      );

      if (response.statusCode == 422) {
        // This will show the validation error in the IDE/console
        AppLog.e("SERVER VALIDATION ERROR: ${response.body}");
      }

      return response.statusCode == 200 || response.statusCode == 201;
    } catch (e) {
      AppLog.e("NETWORK ERROR: $e");
      return false;
    }
  }

  // ---- Edit Material ----
  static Future<bool> updateMaterial(
    String oldName,
    RawMaterial material,
  ) async {
    try {
      final response = await http.put(
        Uri.parse('$effectiveBaseUrl/materials/${Uri.encodeComponent(oldName)}'),
        headers: _authHeaders(),
        body: jsonEncode(material.toJson()),
      );
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  // --- УДАЛЕНИЕ МАТЕРИАЛА ---
  static Future<bool> deleteMaterial(String typeName) async {
    try {
      // Encode the name to handle special characters like / , . etc.
      final encoded = Uri.encodeComponent(typeName);
      final response = await http.delete(
        Uri.parse('$effectiveBaseUrl/materials/$encoded'),
      );
      return response.statusCode == 200 || response.statusCode == 204;
    } catch (e) {
      AppLog.e("Error deleting material: $e");
      return false;
    }
  }

  // 4. Добавить Пользователя
  static Future<bool> addUser(User user) async {
    try {
      final jsonBody = user.toJson();
      AppLog.d("📤 Sending user data: $jsonBody");

      final response = await http.post(
        Uri.parse('$effectiveBaseUrl/users'),
        headers: _authHeaders(),
        body: jsonEncode(jsonBody),
      );

      if (response.statusCode == 200 || response.statusCode == 201) {
        AppLog.i("✅ User created successfully");
        return true;
      } else if (response.statusCode == 422) {
        AppLog.e("❌ Validation error (422): ${response.body}");
        return false;
      } else {
        AppLog.e("❌ Server error (${response.statusCode}): ${response.body}");
        return false;
      }
    } catch (e) {
      AppLog.e("❌ Error adding user", error: e);
      return false;
    }
  }

  // 5. Update User
  static Future<bool> updateUser(User user) async {
    if (user.id == null) {
      AppLog.w("updateUser called without user id. Cannot update.");
      return false;
    }

    try {
      final jsonBody = user.toUpdateJson();
      AppLog.d("🔧 Updating user ${user.id}: $jsonBody");

      final response = await http.put(
        Uri.parse('$effectiveBaseUrl/users/${user.id}'),
        headers: _authHeaders(),
        body: jsonEncode(jsonBody),
      );

      if (response.statusCode == 200) {
        AppLog.i("✅ User updated successfully");
        return true;
      } else {
        AppLog.e(
          "❌ User update failed (${response.statusCode}): ${response.body}",
        );
        return false;
      }
    } catch (e) {
      AppLog.e("❌ Error updating user", error: e);
      return false;
    }
  }

  // 5. Add Shift
  static Future<bool> addShift(Shift shift) async {
    try {
      final response = await http.post(
        Uri.parse('$effectiveBaseUrl/shifts'),
        headers: _authHeaders(),
        body: jsonEncode(shift.toJson()),
      );
      return response.statusCode == 200 || response.statusCode == 201;
    } catch (e) {
      AppLog.e("Error adding shift: $e");
      return false;
    }
  }

  static Future<bool> updateShift(String oldName, Shift shift) async {
    try {
      final response = await http.put(
        Uri.parse('$effectiveBaseUrl/shifts/${Uri.encodeComponent(oldName)}'),
        headers: _authHeaders(),
        body: jsonEncode(shift.toJson()),
      );
      return response.statusCode == 200;
    } catch (e) {
      AppLog.e("Error updating shift: $e");
      return false;
    }
  }

  static Future<bool> deleteShift(String name) async {
    try {
      final response = await http.delete(
        Uri.parse('$effectiveBaseUrl/shifts/${Uri.encodeComponent(name)}'),
      );
      return response.statusCode == 200 || response.statusCode == 204;
    } catch (e) {
      AppLog.e("Error deleting shift: $e");
      return false;
    }
  }

  /// Toggle archive status for a production report.
  static Future<bool> archiveReport(int reportId, bool isArchived) async {
    try {
      final response = await _httpClient.put(
        Uri.parse('$effectiveBaseUrl/reports/$reportId'),
        headers: _authHeaders(),
        body: jsonEncode({'is_archived': isArchived}),
      );
      return response.statusCode == 200;
    } catch (e) {
      AppLog.e("Error archiving report: $e");
      return false;
    }
  }

  /// Sync a report with optional PDF data in a single call.
  /// Used when re-submitting locally-stored pending reports after network is restored.
  static Future<Map<String, dynamic>?> syncReport({
    required Map<String, dynamic> reportData,
    String? pdfBase64,
    String? pdfFilename,
  }) async {
    try {
      final payload = Map<String, dynamic>.from(reportData);
      if (pdfBase64 != null && pdfBase64.isNotEmpty) {
        payload['pdf_base64'] = pdfBase64;
        payload['pdf_filename'] = pdfFilename ?? 'report.pdf';
      }
      final response = await _httpClient
          .post(
            Uri.parse('$effectiveBaseUrl/reports/sync'),
            headers: _authHeaders(),
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 30));
      if (response.statusCode == 200) {
        AppLog.i("Report synced to server (report+PDF)");
        return jsonDecode(response.body) as Map<String, dynamic>;
      } else {
        AppLog.e("Sync failed: ${response.statusCode} - ${response.body}");
        return null;
      }
    } catch (e) {
      AppLog.e("Sync error", error: e);
      return null;
    }
  }

  /// Upload a pre-generated PDF (as base64) to the server.
  /// Server saves it to LOCAL_PDF_ARCHIVE_PATH and uploads to Google Drive.
  static Future<Map<String, dynamic>> uploadPdf({
    required List<int> pdfBytes,
    required String filename,
    required String reportDate,
  }) async {
    try {
      final base64Pdf = base64Encode(pdfBytes);
      final response = await http.post(
        Uri.parse('$effectiveBaseUrl/reports/upload-pdf'),
        headers: _authHeaders(),
        body: jsonEncode({
          'pdf_base64': base64Pdf,
          'filename': filename,
          'report_date': reportDate,
        }),
      ).timeout(const Duration(seconds: 60));

      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      } else {
        return {'status': 'error', 'error': 'Server returned ${response.statusCode}'};
      }
    } catch (e) {
      AppLog.e("Error uploading PDF: $e");
      return {'status': 'error', 'error': e.toString()};
    }
  }

  // --- AI ANALYSIS ---

  /// Build the authenticated header map for admin requests.
  ///
  /// The server now authenticates via the bearer token obtained at login, so
  /// the legacy X-User-Id header is no longer used.
  static Map<String, String> _adminHeaders(int userId) => _authHeaders();

  /// Send a natural-language question to the AI analysis endpoint.
  ///
  /// [userId]      — ID of the logged-in admin user (kept for compatibility; the
  ///                 bearer token is now used for authentication).
  /// [question]    — The question about production data.
  /// [sessionId]   — Optional session identifier for multi-turn conversation.
  /// [contextDays] — How many days of DB history to include as context (default 30).
  ///
  /// Returns the response map with keys: id, question, answer, session_id, created_at.
  /// Returns null on network error; throws [HttpException] on auth errors.
  static Future<Map<String, dynamic>?> analyzeWithAI({
    required int userId,
    required String question,
    String? sessionId,
    int contextDays = 30,
    String source = 'mobile',
  }) async {
    try {
      final response = await _httpClient.post(
        Uri.parse('$effectiveBaseUrl/ai/analyze'),
        headers: _adminHeaders(userId),
        body: jsonEncode({
          'question': question,
          if (sessionId != null) 'session_id': sessionId,
          'context_days': contextDays,
          'source': source,
        }),
      ).timeout(const Duration(seconds: 90));

      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      } else if (response.statusCode == 403 || response.statusCode == 401) {
        AppLog.e("AI analyze: access denied (${response.statusCode})");
        return {'error': 'Access denied', 'status': response.statusCode};
      } else {
        AppLog.e("AI analyze error ${response.statusCode}: ${response.body}");
        return {'error': 'Server error ${response.statusCode}'};
      }
    } catch (e) {
      AppLog.e("AI analyze network error: $e");
      return null;
    }
  }

  /// Fetch AI analysis history (admin only).
  ///
  /// Returns a list of past Q&A entries, newest first.
  static Future<List<dynamic>?> fetchAIHistory({
    required int userId,
    int limit = 50,
    String? sessionId,
  }) async {
    try {
      final uri = Uri.parse('$effectiveBaseUrl/ai/history').replace(
        queryParameters: {
          'limit': '$limit',
          if (sessionId != null) 'session_id': sessionId,
        },
      );
      final response = await _httpClient
          .get(uri, headers: _adminHeaders(userId))
          .timeout(const Duration(seconds: 15));

      if (response.statusCode == 200) {
        return jsonDecode(response.body) as List<dynamic>;
      }
      AppLog.w("fetchAIHistory: ${response.statusCode}");
      return null;
    } catch (e) {
      AppLog.e("fetchAIHistory error: $e");
      return null;
    }
  }

  // --- QUALITY (v2) ---

  /// Fetch the pre-computed internal quality summary for a production report.
  /// The server resolves report -> shift -> run; the frontend never computes stats.
  static Future<Map<String, dynamic>?> fetchReportQuality(int reportId) async {
    try {
      final response = await _httpClient
          .get(Uri.parse('$effectiveBaseUrl/v2/reports/$reportId/quality'),
              headers: _authHeaders())
          .timeout(const Duration(seconds: 15));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.e("fetchReportQuality error: $e");
      return null;
    }
  }

  /// Fetch raw rod-level measurements for a shift (JSON). Each rod carries a
  /// `rejected` boolean computed server-side (3x-tolerance outlier rule).
  static Future<Map<String, dynamic>?> fetchShiftMeasurements(int shiftId) async {
    try {
      final response = await _httpClient
          .get(Uri.parse('$effectiveBaseUrl/v2/shifts/$shiftId/measurements'),
              headers: _authHeaders())
          .timeout(const Duration(seconds: 30));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.e("fetchShiftMeasurements error: $e");
      return null;
    }
  }

  /// Live quality telemetry for the shop-floor kiosk / TV display (no auth).
  static Future<Map<String, dynamic>?> fetchLiveQuality(
    String machine, {
    String windowType = 'rods',
    int windowValue = 50,
    String? anchor,
  }) async {
    try {
      final qp = <String, String>{'window_type': windowType, 'window_value': '$windowValue'};
      if (anchor != null) qp['anchor'] = anchor;
      final uri = Uri.parse('$effectiveBaseUrl/v2/machines/${Uri.encodeComponent(machine)}/live-quality')
          .replace(queryParameters: qp);
      final response = await _httpClient.get(uri).timeout(const Duration(seconds: 15));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.e("fetchLiveQuality error: $e");
      return null;
    }
  }

  /// Quality Control module: filter options (machines, POs, shifts).
  static Future<Map<String, dynamic>?> fetchQualityFilters() async {
    try {
      final response = await _httpClient
          .get(Uri.parse('$effectiveBaseUrl/v2/quality/filters'))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.e("fetchQualityFilters error: $e");
      return null;
    }
  }

  /// Quality Control module: KPIs + specs + per-machine series + paginated rods.
  static Future<Map<String, dynamic>?> fetchQualityData({
    String? machine,
    int? poId,
    int? shiftId,
    int? reportId,
    String? date,
    String? shiftName,
    String window = 'rods',
    int windowValue = 50,
    int page = 1,
    int pageSize = 50,
    bool includeRaw = false,
  }) async {
    try {
      final qp = <String, String>{
        'window': window,
        'window_value': '$windowValue',
        'page': '$page',
        'page_size': '$pageSize',
      };
      if (machine != null && machine != 'all') qp['machine'] = machine;
      if (poId != null) qp['po_id'] = '$poId';
      if (shiftId != null) qp['shift_id'] = '$shiftId';
      if (reportId != null) qp['report_id'] = '$reportId';
      if (date != null) qp['date'] = date;
      if (shiftName != null) qp['shift_name'] = shiftName;
      if (includeRaw) qp['include_raw'] = '1';
      final uri = Uri.parse('$effectiveBaseUrl/v2/quality').replace(queryParameters: qp);
      final response = await _httpClient.get(uri).timeout(const Duration(seconds: 30));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.e("fetchQualityData error: $e");
      return null;
    }
  }

  /// URL for a shift's internal quality summary PDF.
  static String certificatePdfUrl(int shiftId) =>
      '$effectiveBaseUrl/v2/shifts/$shiftId/certificate.pdf';

  /// URL for a shift's measurements as CSV.
  static String measurementsCsvUrl(int shiftId) =>
      '$effectiveBaseUrl/v2/shifts/$shiftId/measurements?fmt=csv';

  /// Factory-wide quality defaults (tolerances & SD thresholds) for Settings.
  static Future<Map<String, dynamic>?> fetchQualitySettings() async {
    try {
      final response = await _httpClient
          .get(Uri.parse('$effectiveBaseUrl/v2/quality/settings'))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.e("fetchQualitySettings error: $e");
      return null;
    }
  }

  static Future<Map<String, dynamic>?> updateQualitySettings(Map<String, dynamic> payload) async {
    try {
      final response = await _httpClient
          .put(Uri.parse('$effectiveBaseUrl/v2/quality/settings'),
              headers: _authHeaders(), body: jsonEncode(payload))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.e("updateQualitySettings error: $e");
      return null;
    }
  }

  /// Consolidated dashboard summary (machines, orders, KPIs, ingestion heartbeat).
  static Future<Map<String, dynamic>?> fetchDashboardSummary() async {
    try {
      final response = await _httpClient
          .get(Uri.parse('$effectiveBaseUrl/v2/dashboard/summary'))
          .timeout(const Duration(seconds: 20));
      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      return null;
    } catch (e) {
      AppLog.e("fetchDashboardSummary error: $e");
      return null;
    }
  }
}
