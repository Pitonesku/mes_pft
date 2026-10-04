// lib/screens/web/web_shell.dart
import 'package:flutter/material.dart';
import '../../models.dart';
import '../../widgets/dev_banner.dart';
import 'dashboard_screen.dart';
import 'orders_screen.dart';
import 'reports_screen.dart';
import 'materials_screen.dart';
import 'users_screen.dart';
import 'machines_shifts_screen.dart';
import 'profile_screen.dart';
import 'ai_analysis_screen.dart';
import '../auth_screen.dart';

enum _Section {
  dashboard,
  orders,
  reports,
  materials,
  users,
  machinesShifts,
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

  // Only superAdmin sees Users and Machines & Shifts
  bool get _isSuperAdmin =>
      widget.currentUser.role == UserRole.superAdmin;

  // AI Analysis is visible to superAdmin and manager
  bool get _canUseAI =>
      widget.currentUser.role == UserRole.superAdmin ||
      widget.currentUser.role == UserRole.manager;

  List<(_Section, IconData, IconData, String)> get _navItems => [
    (_Section.dashboard,      Icons.dashboard_outlined,         Icons.dashboard,              'Dashboard'),
    (_Section.orders,         Icons.receipt_long_outlined,      Icons.receipt_long,           'Orders'),
    (_Section.reports,        Icons.bar_chart_outlined,         Icons.bar_chart,              'Reports'),
    (_Section.materials,      Icons.inventory_2_outlined,       Icons.inventory_2,            'Materials'),
    if (_isSuperAdmin) ...[
      (_Section.users,        Icons.people_outline,             Icons.people,                 'Users'),
      (_Section.machinesShifts, Icons.precision_manufacturing_outlined, Icons.precision_manufacturing, 'Machines & Shifts'),
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
    _Section.users          => UsersScreen(currentUser: widget.currentUser),
    _Section.machinesShifts => MachinesShiftsScreen(user: widget.currentUser),
    _Section.aiAnalysis     => AiAnalysisScreen(currentUser: widget.currentUser),
    _Section.profile        => ProfileScreen(user: widget.currentUser),
  };

  @override
  Widget build(BuildContext context) {
    final items = _navItems;
    // Clamp active index in case section is no longer visible
    final activeIdx = items.indexWhere((i) => i.$1 == _active);
    if (activeIdx == -1) _active = _Section.dashboard;

    final wide = MediaQuery.sizeOf(context).width > 1200;
    return Scaffold(
      body: Row(
        children: [
          NavigationRail(
            extended: wide,
            minWidth: 56,
            minExtendedWidth: 200,
            backgroundColor: const Color(0xFF1E1E2E),
            selectedIconTheme:   const IconThemeData(color: Colors.white, size: 22),
            unselectedIconTheme: const IconThemeData(color: Colors.white54, size: 22),
            selectedLabelTextStyle:   const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
            unselectedLabelTextStyle: const TextStyle(color: Colors.white54),
            selectedIndex: items.indexWhere((i) => i.$1 == _active).clamp(0, items.length - 1),
            onDestinationSelected: (i) => setState(() => _active = items[i].$1),
            leading: Padding(
              padding: const EdgeInsets.symmetric(vertical: 20),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.factory, color: Colors.deepPurpleAccent, size: 30),
                if (wide) ...[
                  const SizedBox(height: 4),
                  const Text('ProdLog',
                    style: TextStyle(color: Colors.deepPurpleAccent,
                      fontWeight: FontWeight.bold, fontSize: 14)),
                ],
              ]),
            ),
            trailing: Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: IconButton(
                icon: const Icon(Icons.logout, color: Colors.white54),
                tooltip: 'Logout',
                onPressed: () => Navigator.pushAndRemoveUntil(context,
                  MaterialPageRoute(builder: (_) => const LoginScreen()),
                  (_) => false),
              ),
            ),
            destinations: items.map((item) => NavigationRailDestination(
              icon: Icon(item.$2), selectedIcon: Icon(item.$3), label: Text(item.$4),
            )).toList(),
          ),
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
              Expanded(child: _buildBody()),
            ]),
          ),
        ],
      ),
    );
  }
}
