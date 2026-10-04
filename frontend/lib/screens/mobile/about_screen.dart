import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import '../../models.dart';

class AboutScreen extends StatefulWidget {
  final User? currentUser;
  const AboutScreen({super.key, this.currentUser});

  @override
  State<AboutScreen> createState() => _AboutScreenState();
}

class _AboutScreenState extends State<AboutScreen> {
  late PackageInfo _packageInfo;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadPackageInfo();
  }

  Future<void> _loadPackageInfo() async {
    final info = await PackageInfo.fromPlatform();
    setState(() {
      _packageInfo = info;
      _isLoading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('About Production Log'),
        backgroundColor: Colors.deepPurple,
        foregroundColor: Colors.white,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Header with logo and version
                  Center(
                    child: Column(
                      children: [
                        const Icon(
                          Icons.factory,
                          size: 80,
                          color: Colors.deepPurple,
                        ),
                        const SizedBox(height: 16),
                        const Text(
                          'Production Log',
                          style: TextStyle(
                            fontSize: 28,
                            fontWeight: FontWeight.bold,
                            color: Colors.deepPurple,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'v${_packageInfo.version} (Build ${_packageInfo.buildNumber})',
                          style: const TextStyle(
                            fontSize: 16,
                            color: Colors.grey,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 32),

                  // Overview section
                  _buildSection(
                    'Overview',
                    'A mobile-first production tracking system for factory operators and managers to submit, track, and analyze production reports in real-time.',
                  ),
                  const SizedBox(height: 24),

                  // Key Features
                  _buildSectionTitle('Key Features'),
                  const SizedBox(height: 12),
                  _buildFeatureItem('📱', 'Production Report Submission', 'Operators fill out shift reports with materials, counts, and quality metrics'),
                  _buildFeatureItem('🔄', 'Offline-First Architecture', 'Works without internet; automatically syncs when connection is restored'),
                  _buildFeatureItem('📊', 'Real-Time Sync', 'Data syncs across all tablets/devices on the same network'),
                  _buildFeatureItem('📋', 'Material Tracking', 'Track acetate, paper, glues, and other materials per shift'),
                  _buildFeatureItem('📄', 'PDF Reports', 'Auto-generate professional PDF reports with all details'),
                  _buildFeatureItem('🔔', 'Telegram Notifications', 'Receive shift report summaries via Telegram'),
                  _buildFeatureItem('🔄', 'Auto-Update', 'App checks for updates on startup and installs them automatically'),
                  const SizedBox(height: 24),

                  // System Requirements
                  _buildSectionTitle('System Requirements'),
                  const SizedBox(height: 12),
                  _buildRequirement('Android 5.0+ (API level 21+)'),
                  _buildRequirement('Internet connection (for sync; works offline)'),
                  _buildRequirement('~50 MB storage for app + database'),
                  const SizedBox(height: 24),

                  // App Info Card
                  Card(
                    elevation: 2,
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'App Information',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                              color: Colors.deepPurple,
                            ),
                          ),
                          const SizedBox(height: 12),
                          _buildInfoRow('App Name', _packageInfo.appName),
                          _buildInfoRow('Package', _packageInfo.packageName),
                          _buildInfoRow('Version', _packageInfo.version),
                          _buildInfoRow('Build Number', _packageInfo.buildNumber),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),

                  // Changelog button
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      icon: const Icon(Icons.history),
                      label: const Text('View Changelog'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.deepPurple,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                      onPressed: () => _showChangelog(context),
                    ),
                  ),
                  const SizedBox(height: 16),

                  // Support section
                  _buildSection(
                    'Support',
                    'For issues, feature requests, or support:\n\n'
                    '• Check the Info screen (ℹ️ button) in the app\n'
                    '• Review the Changelog for recent fixes\n'
                    '• Contact your system administrator',
                  ),
                  const SizedBox(height: 32),

                  // Footer
                   Center(
                     child: Text(
                       'Last Updated: June 28, 2026',
                       style: TextStyle(
                         fontSize: 12,
                         color: Colors.grey[600],
                       ),
                     ),
                   ),
                  const SizedBox(height: 16),
                ],
              ),
            ),
    );
  }

  Widget _buildSectionTitle(String title) {
    return Text(
      title,
      style: const TextStyle(
        fontSize: 18,
        fontWeight: FontWeight.bold,
        color: Colors.deepPurple,
      ),
    );
  }

  Widget _buildSection(String title, String content) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildSectionTitle(title),
        const SizedBox(height: 12),
        Text(
          content,
          style: const TextStyle(
            fontSize: 14,
            height: 1.6,
            color: Colors.black87,
          ),
        ),
      ],
    );
  }

  Widget _buildFeatureItem(String icon, String title, String description) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(icon, style: const TextStyle(fontSize: 20)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 14,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  description,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Colors.grey,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRequirement(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          const Icon(Icons.check_circle, size: 18, color: Colors.green),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(fontSize: 14),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: const TextStyle(
              color: Colors.grey,
              fontSize: 13,
            ),
          ),
          Text(
            value,
            style: const TextStyle(
              fontWeight: FontWeight.bold,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }

  void _showChangelog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Changelog'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _buildChangelogSection(
                'v2.0.0 (Build 1)',
                [
                  'Full web interface with 7 new screens (Dashboard, Orders, Reports, Materials, Users, Machines & Shifts, My Profile)',
                  'SQLAdmin web admin panel for database management',
                  'File logger refactored for web compatibility',
                  'PDF export refactored into platform-conditional files',
                  'Dev banner removed from production builds',
                  'itsdangerous added to backend requirements',
                  'Report detail panel with resizable side-panel layout',
                  'Audit panel improvements with better table layouts',
                  'Web-safe file logging (no dart:io on browser)',
                  'Role-based menu visibility in web navigation',
                ],
              ),
              const SizedBox(height: 12),
              _buildChangelogSection(
                'v1.0.0 (Build 1)',
                [
                  'Initial production release',
                  'Operator report submission',
                  'Admin dashboard with PO management',
                  'Production history with date filtering',
                  'PDF report generation',
                  'Google Drive integration',
                  'Telegram notifications',
                  'Offline-first architecture',
                  'Auto-update system',
                  'Cross-device data sync',
                ],
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Close'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('📋 See CHANGELOG.md for detailed version history'),
                  duration: Duration(seconds: 3),
                ),
              );
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.deepPurple,
              foregroundColor: Colors.white,
            ),
            child: const Text('View Full Changelog'),
          ),
        ],
      ),
    );
  }

  Widget _buildChangelogSection(String version, List<String> items) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          version,
          style: const TextStyle(
            fontWeight: FontWeight.bold,
            fontSize: 14,
            color: Colors.deepPurple,
          ),
        ),
        const SizedBox(height: 8),
        ...items.map((item) => Padding(
          padding: const EdgeInsets.only(bottom: 6, left: 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('• ', style: TextStyle(fontSize: 12)),
              Expanded(
                child: Text(
                  item,
                  style: const TextStyle(fontSize: 12),
                ),
              ),
            ],
          ),
        )),
        const SizedBox(height: 16),
      ],
    );
  }
}
