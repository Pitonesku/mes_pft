// lib/screens/web/profile_screen.dart
// Web version of My Profile screen (same as Android ProfileScreen).
import 'package:flutter/material.dart';
import '../../models.dart';
import '../../api_service.dart';

class ProfileScreen extends StatefulWidget {
  final User user;
  const ProfileScreen({super.key, required this.user});
  @override State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _formKey = GlobalKey<FormState>();
  late TextEditingController _nameC;
  late TextEditingController _emailC;
  final _oldPassC = TextEditingController();
  final _newPassC = TextEditingController();
  final _confPassC = TextEditingController();
  bool _saving = false;
  bool _obscureOld = true, _obscureNew = true, _obscureConf = true;

  @override
  void initState() {
    super.initState();
    _nameC  = TextEditingController(text: widget.user.name);
    _emailC = TextEditingController(text: widget.user.email);
  }

  @override
  void dispose() {
    _nameC.dispose(); _emailC.dispose();
    _oldPassC.dispose(); _newPassC.dispose(); _confPassC.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;

    // Validate password change if any field is filled
    final changingPass = _oldPassC.text.isNotEmpty ||
                         _newPassC.text.isNotEmpty ||
                         _confPassC.text.isNotEmpty;
    if (changingPass) {
      if (_oldPassC.text.isEmpty) {
        _showError('Please enter your current password');
        return;
      }
      if (_newPassC.text.length < 4) {
        _showError('New password must be at least 4 characters');
        return;
      }
      if (_newPassC.text != _confPassC.text) {
        _showError('New passwords do not match');
        return;
      }
    }

    setState(() => _saving = true);

    final updated = User(
      id: widget.user.id,
      name: _nameC.text.trim(),
      email: _emailC.text.trim(),
      password: changingPass ? _newPassC.text : widget.user.password,
      role: widget.user.role,
      canModifyPO: widget.user.canModifyPO,
      isInactive: widget.user.isInactive,
    );

    final success = await ApiService.updateUser(updated);
    setState(() => _saving = false);

    if (!mounted) return;
    if (success) {
      _oldPassC.clear(); _newPassC.clear(); _confPassC.clear();
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Profile updated successfully'),
        backgroundColor: Colors.green));
    } else {
      _showError('Failed to update profile. Check your current password.');
    }
  }

  void _showError(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg), backgroundColor: Colors.red));
  }

  @override
  Widget build(BuildContext context) {
    final roleColor = switch (widget.user.role) {
      UserRole.superAdmin => Colors.red,
      UserRole.manager    => Colors.blue,
      UserRole.operator   => Colors.green,
    };

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(32),
          child: Form(
            key: _formKey,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              // ── Avatar + role ──────────────────────────────────────────
              Center(child: Column(children: [
                CircleAvatar(
                  radius: 40,
                  backgroundColor: Colors.deepPurple,
                  child: Text(widget.user.name[0].toUpperCase(),
                    style: const TextStyle(fontSize: 32, color: Colors.white,
                      fontWeight: FontWeight.bold))),
                const SizedBox(height: 12),
                Chip(
                  label: Text(widget.user.role.name.toUpperCase(),
                    style: const TextStyle(color: Colors.white,
                      fontWeight: FontWeight.bold, fontSize: 12)),
                  backgroundColor: roleColor),
              ])),
              const SizedBox(height: 32),

              // ── Basic info ─────────────────────────────────────────────
              const Text('Basic Information',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold,
                  color: Colors.deepPurple)),
              const Divider(),
              const SizedBox(height: 8),
              TextFormField(
                controller: _nameC,
                decoration: const InputDecoration(
                  labelText: 'Display Name',
                  prefixIcon: Icon(Icons.person)),
                validator: (v) => (v == null || v.trim().isEmpty) ? 'Required' : null),
              const SizedBox(height: 12),
              TextFormField(
                controller: _emailC,
                decoration: const InputDecoration(
                  labelText: 'Email',
                  prefixIcon: Icon(Icons.email))),
              const SizedBox(height: 32),

              // ── Change password ────────────────────────────────────────
              const Text('Change Password',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold,
                  color: Colors.deepPurple)),
              const Divider(),
              const SizedBox(height: 4),
              Text('Leave all password fields blank to keep your current password.',
                style: TextStyle(fontSize: 12, color: Colors.grey[600])),
              const SizedBox(height: 12),
              TextFormField(
                controller: _oldPassC,
                obscureText: _obscureOld,
                decoration: InputDecoration(
                  labelText: 'Current Password',
                  prefixIcon: const Icon(Icons.lock_outline),
                  suffixIcon: IconButton(
                    icon: Icon(_obscureOld ? Icons.visibility : Icons.visibility_off),
                    onPressed: () => setState(() => _obscureOld = !_obscureOld)))),
              const SizedBox(height: 12),
              TextFormField(
                controller: _newPassC,
                obscureText: _obscureNew,
                decoration: InputDecoration(
                  labelText: 'New Password',
                  prefixIcon: const Icon(Icons.lock),
                  suffixIcon: IconButton(
                    icon: Icon(_obscureNew ? Icons.visibility : Icons.visibility_off),
                    onPressed: () => setState(() => _obscureNew = !_obscureNew)))),
              const SizedBox(height: 12),
              TextFormField(
                controller: _confPassC,
                obscureText: _obscureConf,
                decoration: InputDecoration(
                  labelText: 'Confirm New Password',
                  prefixIcon: const Icon(Icons.lock),
                  suffixIcon: IconButton(
                    icon: Icon(_obscureConf ? Icons.visibility : Icons.visibility_off),
                    onPressed: () => setState(() => _obscureConf = !_obscureConf)))),
              const SizedBox(height: 32),

              // ── Save button ────────────────────────────────────────────
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  icon: _saving
                    ? const SizedBox(width: 18, height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                    : const Icon(Icons.save),
                  label: const Text('Save Changes'),
                  style: FilledButton.styleFrom(
                    backgroundColor: Colors.deepPurple,
                    padding: const EdgeInsets.symmetric(vertical: 14)),
                  onPressed: _saving ? null : _save)),
            ]),
          ),
        ),
      ),
    );
  }
}
