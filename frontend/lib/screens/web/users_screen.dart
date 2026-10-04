// lib/screens/web/users_screen.dart
// Web version of User Management screen (same functionality as Android).
import 'package:flutter/material.dart';
import '../../models.dart';
import '../../app_state.dart';
import '../../api_service.dart';

class UsersScreen extends StatefulWidget {
  final User currentUser;
  const UsersScreen({super.key, required this.currentUser});
  @override State<UsersScreen> createState() => _UsersScreenState();
}

class _UsersScreenState extends State<UsersScreen> {
  bool _loading = false;
  String _filter = '';

  List<User> get _filtered => AppData.users
      .where((u) => u.name.toLowerCase().contains(_filter.toLowerCase()) ||
                    u.email.toLowerCase().contains(_filter.toLowerCase()))
      .toList();

  Future<void> _refresh() async {
    setState(() => _loading = true);
    await AppData.loadDataFromServer(forceSync: true);
    setState(() => _loading = false);
  }

  Future<void> _showDialog(User? existing) async {
    final nameC  = TextEditingController(text: existing?.name ?? '');
    final emailC = TextEditingController(text: existing?.email ?? '');
    final passC  = TextEditingController();
    UserRole role = existing?.role ?? UserRole.operator;
    bool canModify = existing?.canModifyPO ?? false;
    bool inactive  = existing?.isInactive ?? false;

    final ok = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(builder: (ctx, setD) {
        bool _saving = false;
        return AlertDialog(
        title: Text(existing == null ? 'Add User' : 'Edit User'),
        content: SizedBox(width: 440, child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: nameC,
            decoration: const InputDecoration(labelText: 'Username *')),
          const SizedBox(height: 10),
          TextField(controller: emailC,
            decoration: const InputDecoration(labelText: 'Email')),
          const SizedBox(height: 10),
          TextField(
            controller: passC,
            obscureText: true,
            decoration: InputDecoration(
              labelText: 'Password',
              hintText: existing == null ? null : 'Leave blank to keep current')),
          const SizedBox(height: 10),
          DropdownButtonFormField<UserRole>(
            initialValue: role,
            decoration: const InputDecoration(labelText: 'Role'),
            items: UserRole.values.map((r) =>
              DropdownMenuItem(value: r, child: Text(r.name))).toList(),
            onChanged: (v) => setD(() => role = v!)),
          CheckboxListTile(
            title: const Text('Can Modify PO'),
            value: canModify,
            onChanged: (v) => setD(() => canModify = v!),
            contentPadding: EdgeInsets.zero),
          CheckboxListTile(
            title: const Text('Is Inactive'),
            value: inactive,
            onChanged: (v) => setD(() => inactive = v!),
            contentPadding: EdgeInsets.zero),
        ])),
        actions: [
          TextButton(
            onPressed: _saving ? null : () => Navigator.pop(ctx, false),
            child: const Text('CANCEL')),
          FilledButton(
            onPressed: _saving ? null : () async {
              if (nameC.text.trim().isEmpty) return;
              setD(() => _saving = true);
              try {
                final user = User(
                  id: existing?.id,
                  name: nameC.text.trim(),
                  email: emailC.text.trim(),
                  password: passC.text.isNotEmpty ? passC.text : (existing?.password ?? ''),
                  role: role,
                  canModifyPO: canModify,
                  isInactive: inactive,
                );

                bool success;
                if (existing == null) {
                  success = await ApiService.addUser(user);
                  if (success) await AppData.loadDataFromServer(forceSync: true);
                } else {
                  success = await ApiService.updateUser(user);
                  if (success) {
                    final idx = AppData.users.indexWhere((u) => u.id == existing.id);
                    if (idx != -1) AppData.users[idx] = user;
                  }
                }
                setState(() => _loading = false);
                if (ctx.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text(success ? 'Saved successfully' : 'Error saving user'),
                    backgroundColor: success ? Colors.green : Colors.red));
                  Navigator.pop(ctx, success);
                }
              } finally {
                if (ctx.mounted) setD(() => _saving = false);
              }
            },
            child: _saving
                ? const SizedBox(
                    width: 20, height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : Text(existing == null ? 'CREATE' : 'SAVE')),
        ],
      );
      }),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          SizedBox(width: 280,
            child: TextField(
              decoration: const InputDecoration(
                hintText: 'Filter by name or email...',
                prefixIcon: Icon(Icons.search), isDense: true),
              onChanged: (v) => setState(() => _filter = v))),
          const Spacer(),
          Text('${_filtered.length} users',
            style: const TextStyle(color: Colors.grey, fontSize: 13)),
          const SizedBox(width: 12),
          OutlinedButton.icon(
            icon: const Icon(Icons.person_add, size: 18),
            label: const Text('Add User'),
            onPressed: () => _showDialog(null)),
          const SizedBox(width: 8),
          FilledButton.icon(
            icon: _loading
              ? const SizedBox(width: 16, height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.refresh, size: 18),
            label: const Text('Refresh'),
            onPressed: _loading ? null : _refresh),
        ]),
        const SizedBox(height: 14),
        Expanded(
          child: _filtered.isEmpty
            ? const Center(child: Text('No users found'))
            : Card(
              margin: EdgeInsets.zero,
              child: SingleChildScrollView(
                child: SizedBox(
                  width: double.infinity,
                  child: DataTable(
                    showCheckboxColumn: false,
                    headingRowColor: WidgetStateProperty.all(const Color(0xFFF5F5F5)),
                    columnSpacing: 18,
                    columns: const [
                      DataColumn(label: Text('Username')),
                      DataColumn(label: Text('Email')),
                      DataColumn(label: Text('Role')),
                      DataColumn(label: Text('Can Modify PO')),
                      DataColumn(label: Text('Status')),
                      DataColumn(label: Text('Actions')),
                    ],
                    rows: _filtered.map((u) {
                      final roleColor = switch (u.role) {
                        UserRole.superAdmin => Colors.red,
                        UserRole.manager   => Colors.blue,
                        UserRole.operator  => Colors.green,
                      };
                      return DataRow(cells: [
                        DataCell(Text(u.name,
                          style: TextStyle(
                            fontWeight: FontWeight.w600,
                            color: u.isInactive ? Colors.grey : Colors.deepPurple))),
                        DataCell(Text(u.email,
                          style: const TextStyle(fontSize: 13))),
                        DataCell(Chip(
                          label: Text(u.role.name,
                            style: const TextStyle(fontSize: 11, color: Colors.white)),
                          backgroundColor: roleColor,
                          padding: EdgeInsets.zero,
                          materialTapTargetSize: MaterialTapTargetSize.shrinkWrap)),
                        DataCell(Icon(
                          u.canModifyPO ? Icons.check_circle : Icons.cancel,
                          size: 18,
                          color: u.canModifyPO ? Colors.green : Colors.grey)),
                        DataCell(Chip(
                          label: Text(u.isInactive ? 'Inactive' : 'Active',
                            style: const TextStyle(fontSize: 11, color: Colors.white)),
                          backgroundColor: u.isInactive ? Colors.grey : Colors.green,
                          padding: EdgeInsets.zero,
                          materialTapTargetSize: MaterialTapTargetSize.shrinkWrap)),
                        DataCell(IconButton(
                          icon: const Icon(Icons.edit, size: 18, color: Colors.orange),
                          tooltip: 'Edit',
                          onPressed: () => _showDialog(u),
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(minWidth: 32, minHeight: 32))),
                      ]);
                    }).toList(),
                  ),
                ),
              ),
            ),
        ),
      ]),
    );
  }
}