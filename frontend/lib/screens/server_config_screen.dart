// server_config_screen.dart
//
// First-Launch / Offline Setup screen.
// Shown only when username='superadmin', password is empty, and no server URL
// has been saved in SharedPreferences yet.
// Once the user saves a valid IP + Port, the bypass is permanently disabled.

import 'package:flutter/material.dart';
import '../api_service.dart';
import 'auth_screen.dart';

class ServerConfigScreen extends StatefulWidget {
  const ServerConfigScreen({super.key});

  @override
  State<ServerConfigScreen> createState() => _ServerConfigScreenState();
}

class _ServerConfigScreenState extends State<ServerConfigScreen> {
  final _formKey = GlobalKey<FormState>();
  final _ipController = TextEditingController();
  final _portController = TextEditingController(text: '8000');

  bool _isSaving = false;
  String _preview = '—';

  @override
  void initState() {
    super.initState();
    _ipController.addListener(_updatePreview);
    _portController.addListener(_updatePreview);
  }

  void _updatePreview() {
    final ip = _ipController.text.trim();
    final port = _portController.text.trim();
    setState(() {
      _preview = (ip.isNotEmpty && port.isNotEmpty)
          ? 'http://$ip:$port/api'
          : '—';
    });
  }

  @override
  void dispose() {
    _ipController.dispose();
    _portController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;

    final ip = _ipController.text.trim();
    final port = _portController.text.trim();
    final baseUrl = 'http://$ip:$port/api';

    setState(() => _isSaving = true);

    // Persist and re-initialize ApiService with the new URL.
    await ApiService.reinitialize(baseUrl);

    if (!mounted) return;
    setState(() => _isSaving = false);

    // Show confirmation snackbar.
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Server configured: $baseUrl'),
        backgroundColor: Colors.green,
        duration: const Duration(seconds: 2),
      ),
    );

    await Future.delayed(const Duration(milliseconds: 1500));
    if (!mounted) return;

    // Replace the entire navigation stack with a fresh LoginScreen.
    Navigator.pushAndRemoveUntil(
      context,
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF0EBF8),
      appBar: AppBar(
        title: const Text('Server Setup'),
        backgroundColor: Colors.deepPurple,
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Card(
            margin: const EdgeInsets.all(24),
            elevation: 4,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
            ),
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: _isSaving ? _buildSavingState() : _buildForm(),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildSavingState() {
    return const Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        CircularProgressIndicator(color: Colors.deepPurple),
        SizedBox(height: 24),
        Text(
          'Saving configuration...',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w500),
        ),
      ],
    );
  }

  Widget _buildForm() {
    return Form(
      key: _formKey,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          const Center(
            child: Icon(Icons.dns_rounded, size: 64, color: Colors.deepPurple),
          ),
          const SizedBox(height: 16),
          const Center(
            child: Text(
              'First-Launch Setup',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
            ),
          ),
          const SizedBox(height: 8),
          const Center(
            child: Text(
              'Enter the address of your production server.\n'
              'This only needs to be done once.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey, fontSize: 13),
            ),
          ),
          const SizedBox(height: 32),

          // Server IP field
          TextFormField(
            controller: _ipController,
            keyboardType: TextInputType.url,
            decoration: const InputDecoration(
              labelText: 'Server IP',
              hintText: 'e.g. 192.168.1.100',
              prefixIcon: Icon(Icons.computer),
            ),
            validator: (value) {
              if (value == null || value.trim().isEmpty) {
                return 'Please enter the server IP address.';
              }
              return null;
            },
          ),
          const SizedBox(height: 16),

          // Port field
          TextFormField(
            controller: _portController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Port',
              hintText: '8000',
              prefixIcon: Icon(Icons.settings_ethernet),
            ),
            validator: (value) {
              if (value == null || value.trim().isEmpty) {
                return 'Please enter a port number.';
              }
              final port = int.tryParse(value.trim());
              if (port == null || port < 1 || port > 65535) {
                return 'Port must be a number between 1 and 65535.';
              }
              return null;
            },
          ),
          const SizedBox(height: 12),

          // Live URL preview
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: Colors.deepPurple.withOpacity(0.06),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                const Icon(Icons.link, size: 16, color: Colors.deepPurple),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _preview,
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 13,
                      color: Colors.deepPurple,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 28),

          // Save button
          SizedBox(
            width: double.infinity,
            height: 50,
            child: ElevatedButton.icon(
              icon: const Icon(Icons.save_rounded),
              label: const Text(
                'SAVE & CONTINUE',
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.deepPurple,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
              onPressed: _save,
            ),
          ),
        ],
      ),
    );
  }
}
