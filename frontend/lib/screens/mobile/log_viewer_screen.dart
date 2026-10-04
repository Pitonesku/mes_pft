import 'package:flutter/material.dart';
import '../../file_logger.dart';

/// Screen to view and manage logs on the tablet
class LogViewerScreen extends StatefulWidget {
  const LogViewerScreen({super.key});

  @override
  State<LogViewerScreen> createState() => _LogViewerScreenState();
}

class _LogViewerScreenState extends State<LogViewerScreen> {
  late Future<String> _logContentFuture;
  final ScrollController _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    _refreshLogs();
  }

  void _refreshLogs() {
    setState(() {
      _logContentFuture = fileLogger.getLogContent();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('📋 Connection Logs'),
        backgroundColor: Colors.blueGrey[800],
        actions: [
          // Refresh button
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _refreshLogs,
            tooltip: 'Refresh logs',
          ),
          // Clear button
          IconButton(
            icon: const Icon(Icons.delete),
            onPressed: () => _showClearConfirmation(),
            tooltip: 'Clear logs',
          ),
        ],
      ),
      body: FutureBuilder<String>(
        future: _logContentFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(
              child: CircularProgressIndicator(),
            );
          }

          if (snapshot.hasError) {
            return Center(
              child: Text('❌ Error loading logs: ${snapshot.error}'),
            );
          }

          final logContent = snapshot.data ?? 'No logs available';

          return Column(
            children: [
              // Log info header
              Container(
                color: Colors.blueGrey[100],
                padding: const EdgeInsets.all(12),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      '📁 Logs: ${logContent.split('\n').length} lines',
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    FutureBuilder<String>(
                      future: fileLogger.getLogFilePath(),
                      builder: (context, snapshot) {
                        if (snapshot.hasData) {
                          return Text(
                            '📍 ${snapshot.data!.split('/').last}',
                            style: const TextStyle(fontSize: 12),
                          );
                        }
                        return const SizedBox.shrink();
                      },
                    ),
                  ],
                ),
              ),
              // Log content
              Expanded(
                child: SingleChildScrollView(
                  controller: _scrollController,
                  child: Container(
                    color: Colors.grey[900],
                    padding: const EdgeInsets.all(12),
                    child: SelectableText(
                      logContent,
                      style: const TextStyle(
                        fontFamily: 'Courier',
                        fontSize: 12,
                        color: Colors.greenAccent,
                        height: 1.5,
                      ),
                    ),
                  ),
                ),
              ),
              // Action buttons
              Container(
                color: Colors.blueGrey[100],
                padding: const EdgeInsets.all(12),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  children: [
                    ElevatedButton.icon(
                      onPressed: _refreshLogs,
                      icon: const Icon(Icons.refresh),
                      label: const Text('Refresh'),
                    ),
                    ElevatedButton.icon(
                      onPressed: _scrollToBottom,
                      icon: const Icon(Icons.arrow_downward),
                      label: const Text('Scroll Down'),
                    ),
                    ElevatedButton.icon(
                      onPressed: _showClearConfirmation,
                      icon: const Icon(Icons.delete),
                      label: const Text('Clear'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.red,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  void _scrollToBottom() {
    _scrollController.animateTo(
      _scrollController.position.maxScrollExtent,
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOut,
    );
  }

  void _showClearConfirmation() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear Logs?'),
        content: const Text('This will delete all stored logs. This action cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () {
              fileLogger.clearLogs();
              Navigator.pop(context);
              _refreshLogs();
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('✅ Logs cleared')),
              );
            },
            child: const Text('Clear', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }
}
