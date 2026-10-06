// lib/screens/web/web_shell.dart
import 'package:flutter/material.dart';
import '../../models.dart';
import '../../api_service.dart';
import '../../core/app_navigation.dart';
import '../../core/hash_navigation.dart';
import '../../widgets/dev_banner.dart';
import 'dashboard_screen.dart';
import 'orders_screen.dart';
import 'reports_screen.dart';
import 'report_full_screen.dart';
import 'materials_screen.dart';
import 'quality_control_screen.dart';
import 'users_screen.dart';
import 'machines_shifts_screen.dart';
import 'settings_screen.dart';
import 'profile_screen.dart';
import 'ai_analysis_screen.dart';
import '../auth_screen.dart';

enum _Section {
  dashboard,
  orders,
  reports,
  materials,
  quality,
  users,
  machinesShifts,
  settings,
  aiAnalysis,
  profile,
}

class WebShell extends StatefulWidget {
  final User currentUser;
  const WebShell({super.key, required this.currentUser});
  @override
  State<WebShell> createState() => _WebShellState();
}

class _WebShellState extends State<WebShell> {
  _Section _active = _Section.dashboard;
  QualityRequest? _qualityRequest;
  int? _reportId;
  _Section? _reportReturnSection;

  @override
  void initState() {
    super.initState();
    AppNavigation.qualityRequest.addListener(_onQualityRequest);
    AppNavigation.reportRequest.addListener(_onReportRequest);
    _applyInitialFragment();
  }

  @override
  void dispose() {
    AppNavigation.qualityRequest.removeListener(_onQualityRequest);
    AppNavigation.reportRequest.removeListener(_onReportRequest);
    super.dispose();
  }

  void _onQualityRequest() {
    final req = AppNavigation.qualityRequest.value;
    if (req == null) return;
    AppNavigation.qualityRequest.value = null;
    setState(() {
      _qualityRequest = req;
      _active = _Section.quality;
    });
  }

  void _onReportRequest() {
    final id = AppNavigation.reportRequest.value;
    if (id == null) return;
    AppNavigation.reportRequest.value = null;
    setState(() {
      _reportReturnSection = _active;
      _reportId = id;
      _active = _Section.reports;
    });
  }

  void _applyInitialFragment() {
    final frag = Uri.base.fragment;
    if (frag.isEmpty) {
      setHash('#/dashboard');
      _setFromFragment('/dashboard');
    } else {
      _setFromFragment(frag);
    }
  }

  void _setFromFragment(String frag) {
    final q = frag.indexOf('?');
    final path = q == -1 ? frag : frag.substring(0, q);
    final query = q == -1 ? '' : frag.substring(q + 1);
    final params = Uri.splitQueryString(query);
    _reportId = null;
    _qualityRequest = null;
    if (path == '/quality') {
      _qualityRequest = QualityRequest(
        machine: params['machine'],
        shiftId: int.tryParse(params['shift_id'] ?? ''),
        poId: int.tryParse(params['po_id'] ?? ''),
        po: params['po'],
      );
      _active = _Section.quality;
      return;
    }
    final reportMatch = RegExp(r'^/reports/(\d+)$').firstMatch(path);
    if (reportMatch != null) {
      _reportReturnSection = _active;
      _reportId = int.tryParse(reportMatch.group(1)!);
      _active = _Section.reports;
      return;
    }
    final section = _sectionFromPath(path);
    if (section != null && _isSectionAllowed(section)) _active = section;
    else _active = _Section.dashboard;
  }

  String? _sectionPath(_Section s) => switch (s) {
        _Section.dashboard => '#/dashboard',
        _Section.orders => '#/orders',
        _Section.reports => '#/reports',
        _Section.materials => '#/materials',
        _Section.quality => '#/quality',
        _Section.users => '#/users',
        _Section.machinesShifts => '#/machines',
        _Section.settings => '#/settings',
        _Section.aiAnalysis => '#/ai',
        _Section.profile => '#/profile',
      };

  _Section? _sectionFromPath(String path) => switch (path) {
        '/dashboard' => _Section.dashboard,
        '/orders' => _Section.orders,
        '/reports' => _Section.reports,
        '/materials' => _Section.materials,
        '/quality' => _Section.quality,
        '/users' => _Section.users,
        '/machines' => _Section.machinesShifts,
        '/settings' => _Section.settings,
        '/ai' => _Section.aiAnalysis,
        '/profile' => _Section.profile,
        _ => null,
      };


  // Only superAdmin sees Users and Machines & Shifts
  bool get _isSuperAdmin =>
      widget.currentUser.role == UserRole.superAdmin;

  // AI Analysis is visible to superAdmin and manager
  bool get _canUseAI =>
      widget.currentUser.role == UserRole.superAdmin ||
      widget.currentUser.role == UserRole.manager;

  bool _isSectionAllowed(_Section s) => switch (s) {
        _Section.users => _isSuperAdmin,
        _Section.machinesShifts => _isSuperAdmin,
        _Section.settings => _isSuperAdmin,
        _Section.aiAnalysis => _canUseAI,
        _ => true,
      };

  List<(_Section, IconData, IconData, String)> get _navItems => [
    (_Section.dashboard,      Icons.dashboard_outlined,         Icons.dashboard,              'Dashboard'),
    (_Section.orders,         Icons.receipt_long_outlined,      Icons.receipt_long,           'Orders'),
    (_Section.reports,        Icons.bar_chart_outlined,         Icons.bar_chart,              'Reports'),
    (_Section.materials,      Icons.inventory_2_outlined,       Icons.inventory_2,            'Materials'),
    (_Section.quality,        Icons.biotech_outlined,           Icons.biotech,                'Quality Control'),
    if (_isSuperAdmin) ...[
      (_Section.users,        Icons.people_outline,             Icons.people,                 'Users'),
      (_Section.machinesShifts, Icons.precision_manufacturing_outlined, Icons.precision_manufacturing, 'Machines & Shifts'),
      (_Section.settings, Icons.settings_outlined, Icons.settings, 'Settings'),
    ],
    if (_canUseAI)
      (_Section.aiAnalysis,   Icons.psychology_outlined,        Icons.psychology,             'AI Analysis'),
    (_Section.profile,        Icons.person_outline,             Icons.person,                 'My Profile'),
  ];

  Widget _buildBody() => switch (_active) {
    _Section.dashboard      => DashboardScreen(user: widget.currentUser),
    _Section.orders         => OrdersScreen(user: widget.currentUser),
    _Section.reports        => ReportsScreen(user: widget.currentUser),
    _Section.materials      => MaterialsScreen(user: widget.currentUser),
    _Section.quality       => QualityControlScreen(initial: _qualityRequest),
    _Section.users          => UsersScreen(currentUser: widget.currentUser),
    _Section.machinesShifts => MachinesShiftsScreen(user: widget.currentUser),
    _Section.settings      => const SettingsScreen(),
    _Section.aiAnalysis     => AiAnalysisScreen(currentUser: widget.currentUser),
    _Section.profile        => ProfileScreen(user: widget.currentUser),
  };

  Widget _sidebar(bool wide) => Container(
        width: wide ? 200 : 56,
        color: const Color(0xFF1E1E2E),
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 20),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.factory, color: Colors.deepPurpleAccent, size: 30),
              if (wide) ...[
                const SizedBox(height: 4),
                const Text('ProdLog', style: TextStyle(color: Colors.deepPurpleAccent, fontWeight: FontWeight.bold, fontSize: 14)),
              ],
            ]),
          ),
          Expanded(child: ListView(padding: EdgeInsets.zero, children: [for (final item in _navItems) _navItem(item, wide)])),
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: IconButton(
              icon: const Icon(Icons.logout, color: Colors.white54),
              tooltip: 'Logout',
              onPressed: () async {
                await ApiService.clearSession();
                if (!mounted) return;
                Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => const LoginScreen()), (_) => false);
              },
            ),
          ),
        ]),
      );

  Widget _navItem((_Section, IconData, IconData, String) item, bool wide) {
    final selected = _active == item.$1;
    final path = _sectionPath(item.$1);
    return InkWell(
      onTap: () {
        setState(() {
          _active = item.$1;
          _reportId = null;
          _qualityRequest = null;
          _reportReturnSection = null;
        });
        if (path != null) setHash(path);
      },
      child: Container(
        height: 48,
        color: selected ? Colors.white.withValues(alpha: 0.12) : Colors.transparent,
        padding: EdgeInsets.symmetric(horizontal: wide ? 16 : 0),
        child: Row(
          mainAxisAlignment: wide ? MainAxisAlignment.start : MainAxisAlignment.center,
          children: [
            Icon(selected ? item.$3 : item.$2, color: selected ? Colors.white : Colors.white54, size: 22),
            if (wide) ...[
              const SizedBox(width: 12),
              Expanded(child: Text(item.$4, style: TextStyle(color: selected ? Colors.white : Colors.white54, fontWeight: selected ? FontWeight.w600 : FontWeight.normal, fontSize: 13))),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final items = _navItems;

    final wide = MediaQuery.sizeOf(context).width > 1200;
    return Scaffold(
      body: Row(
        children: [
          _sidebar(wide),
          const VerticalDivider(width: 1, thickness: 1),
          Expanded(
            child: Column(children: [
              Container(
                height: 56, color: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Row(children: [
                  Text(items.firstWhere((n) => n.$1 == _active,
                    orElse: () => items.first).$4,
                    style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
                  const Spacer(),
                  CircleAvatar(radius: 16, backgroundColor: Colors.deepPurple,
                    child: Text(widget.currentUser.name[0].toUpperCase(),
                      style: const TextStyle(color: Colors.white, fontSize: 13))),
                  const SizedBox(width: 8),
                  Text(widget.currentUser.name, style: const TextStyle(fontSize: 14)),
                ]),
              ),
              const Divider(height: 1, thickness: 1),
              const DevBannerBar(),
              Expanded(child: _reportId == null
                  ? _buildBody()
                  : ReportFullScreen(
                      reportId: _reportId!,
                      onBack: () => setState(() {
                        _active = _reportReturnSection ?? _Section.reports;
                        _reportId = null;
                        _reportReturnSection = null;
                      }),
                    )),
            ]),
          ),
        ],
      ),
    );
  }
}
