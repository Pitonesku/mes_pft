// auth_screen.dart
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import '../models.dart';
import '../app_state.dart';
import '../api_service.dart';
import '../update_checker.dart';
import '../core/responsive_layout.dart';
import 'mobile/operator_screen.dart';
import 'mobile/admin_screen.dart';
import 'mobile/about_screen.dart';
import 'web/web_shell.dart';
import 'server_config_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override 
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _nameController = TextEditingController();
  final _passController = TextEditingController();
  bool _isLoadingData = false;

  @override
  void initState() {
    super.initState();
    // Check for app updates after the first frame is rendered
    if (!kIsWeb) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        UpdateChecker.checkForUpdate(context);
      });
    }
  }

  // Функция для входа
  Future<void> _login() async {
    try {
      String username = _nameController.text;
      String password = _passController.text;
      
      // ── First-Launch / Offline Setup Interceptor ──────────────────────────
      // If username is 'superadmin', password is empty, AND no server URL has
      // been saved yet → redirect to ServerConfigScreen so the admin can
      // configure the server before any network calls are made.
      // Once a server URL is saved this branch is permanently disabled,
      // forcing all subsequent logins through normal server authentication.
      if (username == "superadmin" && password.isEmpty) {
        final isConfigured = await ApiService.isServerConfigured();

        if (!isConfigured) {
          // No server configured yet → open the setup screen.
          if (mounted) {
            Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const ServerConfigScreen()),
            );
          }
          return;
        }

        // Server IS configured → fall through to normal login below.
        // The passwordless bypass is now disabled; superadmin must authenticate
        // against the server like any other user.
      }

      setState(() => _isLoadingData = true);

      // 1. Пробуем авторизоваться через сервер
      final loginResponse = await ApiService.login(username, password);
      
      if (loginResponse != null && loginResponse['status'] == 'success') {
        // Успешная авторизация на сервере
        await AppData.loadDataFromServer(forceSync: true);

        if (!mounted) return;
        setState(() => _isLoadingData = false);

        // Определяем роль и навигируем
        int? roleId = loginResponse['role_id'];
        UserRole role = _mapRoleIdToRole(roleId);

        final user = User(
          name: username,
          password: password,
          email: loginResponse['email'] ?? "",
          role: role,
          canModifyPO: role == UserRole.superAdmin || role == UserRole.manager,
        );

        await ApiService.saveUser(user);

        if (mounted) {
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(
              builder: (c) => ResponsiveLayout(
                currentUser: user,
                mobileBuilder: (ctx, u) => u.role == UserRole.operator
                    ? ReportPage(operator: u)
                    : AdminDashboard(currentUser: u),
                desktopBuilder: (ctx, u) => u.role == UserRole.operator
                    ? ReportPage(operator: u)
                    : WebShell(currentUser: u),
              ),
            ),
          );
        }
        return;
      }

      // 2. Server rejected the credentials (or is unreachable). There is no
      //    offline/local fallback login: a session can only be established by the
      //    server, so a forgotten or blanked password can never grant access to a
      //    cached superadmin or demo account.
      if (mounted) {
        setState(() => _isLoadingData = false);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Invalid Username or Password"),
            backgroundColor: Colors.redAccent,
          ),
        );
      }

    } catch (e) {
      if (mounted) {
        setState(() => _isLoadingData = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text("Error: $e"), 
            backgroundColor: Colors.redAccent
          )
        );
      }
    }
  }

  /// Конвертирует role_id с сервера в UserRole
  UserRole _mapRoleIdToRole(int? roleId) {
    switch (roleId) {
      case 1:
        return UserRole.superAdmin;
      case 2:
        return UserRole.manager;
      case 3:
        return UserRole.operator;
      default:
        return UserRole.operator;
    }
  }

  // Принудительная синхронизация по кнопке
  Future<void> _forceSync() async {
    setState(() => _isLoadingData = true);
    // Передаем forceSync: true, чтобы проигнорировать проверку версии
    bool success = await AppData.loadDataFromServer(forceSync: true);
    if (!mounted) return;
    setState(() => _isLoadingData = false);
    
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(success ? "Data fully updated!" : "Server unreachable, using local cache."),
        backgroundColor: success ? Colors.green : Colors.orange,
      )
    );
  }

  void _showResetPasswordDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Reset Password"),
        content: const TextField(
          decoration: InputDecoration(
            labelText: "Enter your registered Email",
            prefixIcon: Icon(Icons.email)
          )
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text("CANCEL")),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text("Reset link sent!"), backgroundColor: Colors.green)
              );
            }, 
            child: const Text("SEND")
          ),
        ],
      )
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 400),
          child: Stack( // Используем Stack, чтобы наложить кнопку синхронизации сверху
            alignment: Alignment.topRight,
            children: [
              Card(
                margin: const EdgeInsets.all(24),
                elevation: 4,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                child: Padding(
                  padding: const EdgeInsets.all(32),
                  child: _isLoadingData 
                    ? _buildLoadingState() 
                    : _buildLoginForm(),
                ),
              ),
               // Кнопка принудительного обновления (только когда нет загрузки)
               if (!_isLoadingData)
                 Positioned(
                   top: 35,
                   right: 35,
                   child: Row(
                     mainAxisSize: MainAxisSize.min,
                     children: [
                       IconButton(
                         icon: const Icon(Icons.info_outline, color: Colors.deepPurple),
                         tooltip: "About App",
                         onPressed: () {
                           Navigator.push(
                             context,
                             MaterialPageRoute(builder: (context) => const AboutScreen()),
                           );
                         },
                       ),
                       IconButton(
                         icon: const Icon(Icons.sync, color: Colors.deepPurple),
                         tooltip: "Force Update Data",
                         onPressed: _forceSync,
                       ),
                     ],
                   ),
                 ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildLoadingState() {
    return const Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        CircularProgressIndicator(color: Colors.deepPurple),
        SizedBox(height: 24),
        Text("Syncing with Server...", style: TextStyle(fontSize: 16, fontWeight: FontWeight.w500)),
        SizedBox(height: 8),
        Text("Checking data versions", textAlign: TextAlign.center, style: TextStyle(color: Colors.grey, fontSize: 12)),
      ],
    );
  }

  Widget _buildLoginForm() {
    return Column(
      mainAxisSize: MainAxisSize.min, 
      children: [
        const Icon(Icons.account_circle, size: 80, color: Colors.deepPurple),
        const SizedBox(height: 16),
        const Text("System Login", style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
        const SizedBox(height: 32),
        TextField(
          controller: _nameController, 
          decoration: const InputDecoration(labelText: "Username", prefixIcon: Icon(Icons.person))
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _passController, 
          obscureText: true, 
          decoration: const InputDecoration(labelText: "Password", prefixIcon: Icon(Icons.lock)),
          onSubmitted: (_) => _login(),
        ),
        const SizedBox(height: 24),
        ElevatedButton(
          onPressed: _login, 
          style: ElevatedButton.styleFrom(
            minimumSize: const Size(double.infinity, 50),
            backgroundColor: Colors.deepPurple,
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))
          ),
          child: const Text("LOGIN", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold))
        ),
        const SizedBox(height: 16),
        TextButton(
          onPressed: _showResetPasswordDialog, 
          child: const Text("Forgot Password?", style: TextStyle(color: Colors.deepPurple))
        )
      ]
    );
  }
}

/// Bootstraps the app: restores a persisted session (token + user) before
/// deciding whether to show the login screen or the main shell.
class SessionGate extends StatefulWidget {
  const SessionGate({super.key});
  @override
  State<SessionGate> createState() => _SessionGateState();
}

class _SessionGateState extends State<SessionGate> {
  bool _loading = true;
  User? _user;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    final token = ApiService.authToken;
    final user = await ApiService.loadSavedUser();
    final hasSession = token != null && token.isNotEmpty && user != null;
    if (!mounted) return;
    if (hasSession) {
      // Sync real data on restore (also re-validates the token against the
      // server). A 401 is handled by ApiService._fail -> onUnauthorized, which
      // clears the token; in that case we fall through to the login screen.
      await AppData.loadDataFromServer();
    }
    if (!mounted) return;
    final stillAuthed =
        ApiService.authToken != null && ApiService.authToken!.isNotEmpty;
    setState(() {
      _user = (hasSession && stillAuthed) ? user : null;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final user = _user;
    if (user == null) return const LoginScreen();
    return ResponsiveLayout(
      currentUser: user,
      mobileBuilder: (ctx, u) => u.role == UserRole.operator
          ? ReportPage(operator: u)
          : AdminDashboard(currentUser: u),
      desktopBuilder: (ctx, u) => u.role == UserRole.operator
          ? ReportPage(operator: u)
          : WebShell(currentUser: u),
    );
  }
}