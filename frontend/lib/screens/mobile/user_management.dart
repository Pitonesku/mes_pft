import 'package:flutter/material.dart';
import '../../models.dart';
import '../../app_state.dart';
import '../../api_service.dart'; // Добавлен импорт API

class UserManagementScreen extends StatefulWidget {
  const UserManagementScreen({super.key});
  @override State<UserManagementScreen> createState() => _UserManagementScreenState();
}

class _UserManagementScreenState extends State<UserManagementScreen> {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("User Management"), backgroundColor: Colors.red[800], foregroundColor: Colors.white),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: AppData.users.length,
        itemBuilder: (ctx, i) {
          final u = AppData.users[i];
          return Card(
            color: u.isInactive ? Colors.grey[200] : Colors.white,
            child: ListTile(
              title: Text(u.name, style: const TextStyle(fontWeight: FontWeight.bold)),
              subtitle: Text("${u.role.name.toUpperCase()} | ${u.email}"),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(icon: const Icon(Icons.edit, color: Colors.blue), onPressed: () => _showUserDialog(u)),
                IconButton(icon: const Icon(Icons.delete, color: Colors.red), onPressed: () => _deleteUser(u)),
              ]),
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _showUserDialog(null), 
        backgroundColor: Colors.red[800], 
        child: const Icon(Icons.add, color: Colors.white)
      ),
    );
  }

  void _showUserDialog(User? user) {
    final nameC = TextEditingController(text: user?.name ?? "");
    final emailC = TextEditingController(text: user?.email ?? "");
    final passC = TextEditingController(text: user?.password ?? "");
    UserRole role = user?.role ?? UserRole.operator;
    bool modify = user?.canModifyPO ?? false;
    bool inactive = user?.isInactive ?? false;

    showDialog(
      context: context, 
      barrierDismissible: false, // Чтобы не закрыли случайно во время отправки
      builder: (ctx) => StatefulBuilder(builder: (ctx, setStateD) {
        bool _saving = false;
        return AlertDialog(
        title: Text(user == null ? "Add User" : "Edit User"),
        content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: nameC, decoration: const InputDecoration(labelText: "Name")),
          TextField(controller: emailC, decoration: const InputDecoration(labelText: "Email")),
          TextField(
            controller: passC,
            decoration: InputDecoration(
              labelText: "Password",
              hintText: user == null ? null : "Leave blank to keep current password",
            ),
            obscureText: true,
          ),
          const SizedBox(height: 10),
          DropdownButtonFormField<UserRole>(
            initialValue: role, 
            decoration: const InputDecoration(labelText: "Role"),
            items: UserRole.values.map((r) => DropdownMenuItem(value: r, child: Text(r.name))).toList(), 
            onChanged: (v) => setStateD(() => role = v!)
          ),
          CheckboxListTile(title: const Text("Can Modify PO"), value: modify, onChanged: (v) => setStateD(() => modify = v!)),
          CheckboxListTile(title: const Text("Is Inactive"), value: inactive, onChanged: (v) => setStateD(() => inactive = v!)),
        ])),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text("CANCEL")),
          ElevatedButton(
            onPressed: _saving ? null : () async {
              if (nameC.text.isEmpty) return;
              setStateD(() => _saving = true);
              try {
                final updatedUser = User(
                  id: user?.id,
                  name: nameC.text,
                  password: passC.text,
                  email: emailC.text,
                  role: role,
                  canModifyPO: modify,
                  isInactive: inactive,
                );

                bool success;
                if (user == null) {
                  // Создаем нового пользователя
                  success = await ApiService.addUser(updatedUser);
                } else {
                  // Обновляем существующего пользователя
                  success = await ApiService.updateUser(updatedUser);
                }

                if (success) {
                  setState(() {
                    if (user == null) {
                      AppData.users.add(updatedUser);
                    } else {
                      user.name = nameC.text;
                      user.email = emailC.text;
                      user.password = passC.text;
                      user.role = role;
                      user.canModifyPO = modify;
                      user.isInactive = inactive;
                    }
                  });
                  if (ctx.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(user == null ? "User created successfully" : "User updated successfully"),
                        backgroundColor: Colors.green,
                      ),
                    );
                    Navigator.pop(ctx);
                  }
                } else {
                  if (ctx.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text("Server Error: User data not saved"), backgroundColor: Colors.red)
                    );
                  }
                }
              } finally {
                if (ctx.mounted) setStateD(() => _saving = false);
              }
            }, 
            child: _saving
                ? const SizedBox(
                    width: 20, height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Text("SAVE"),
          ),
        ],
      );
      }),
    );
  }

  void _deleteUser(User user) {
    if (user.role == UserRole.superAdmin) {
       ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Cannot delete SuperAdmin")));
       return;
    }
    // Здесь в идеале тоже должен быть ApiService.deleteUser, если он есть на сервере
    setState(() => AppData.users.remove(user));
  }
}