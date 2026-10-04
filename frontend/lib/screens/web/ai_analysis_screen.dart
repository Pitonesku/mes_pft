// lib/screens/web/ai_analysis_screen.dart
//
// AI-powered production data analysis — chat-style interface.
// Accessible only to superAdmin and manager roles.
//
// Architecture:
//   Each screen mount creates a new session_id so the conversation history
//   is tracked server-side for multi-turn Q&A.
//   Session ID format: "uid_{userId}_{epochMs}" — simple and unique.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../models.dart';
import '../../api_service.dart';
import '../../utils/logger.dart';

class AiAnalysisScreen extends StatefulWidget {
  final User currentUser;

  const AiAnalysisScreen({super.key, required this.currentUser});

  @override
  State<AiAnalysisScreen> createState() => _AiAnalysisScreenState();
}

class _AiAnalysisScreenState extends State<AiAnalysisScreen> {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final List<_ChatMessage> _messages = [];
  bool _loading = false;
  late final String _sessionId;
  int _contextDays = 30;

  @override
  void initState() {
    super.initState();
    _sessionId =
        'uid_${widget.currentUser.id}_${DateTime.now().millisecondsSinceEpoch}';
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final question = _controller.text.trim();
    if (question.isEmpty || _loading) return;

    setState(() {
      _messages.add(_ChatMessage(role: _Role.user, text: question));
      _loading = true;
    });
    _controller.clear();
    _scrollToBottom();

    final userId = widget.currentUser.id;
    if (userId == null) {
      _appendError('User ID is missing — please log in again.');
      return;
    }

    final result = await ApiService.analyzeWithAI(
      userId: userId,
      question: question,
      sessionId: _sessionId,
      contextDays: _contextDays,
      source: 'web',
    );

    setState(() => _loading = false);

    if (result == null) {
      _appendError('Network error — could not reach the server.');
    } else if (result.containsKey('error')) {
      _appendError(result['error']?.toString() ?? 'Unknown error');
    } else {
      final answer = result['answer']?.toString() ?? '(empty response)';
      setState(() => _messages.add(_ChatMessage(role: _Role.ai, text: answer)));
      AppLog.i('AI response received (${answer.length} chars)');
    }

    _scrollToBottom();
  }

  void _appendError(String msg) {
    setState(
      () => _messages.add(_ChatMessage(role: _Role.error, text: msg)),
    );
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _clearChat() {
    setState(() => _messages.clear());
  }

  @override
  Widget build(BuildContext context) {
    final isAdmin = widget.currentUser.role == UserRole.superAdmin ||
        widget.currentUser.role == UserRole.manager;

    if (!isAdmin) {
      return const Center(
        child: Text(
          '⛔ Admin or Manager privileges required',
          style: TextStyle(fontSize: 18, color: Colors.red),
        ),
      );
    }

    return Column(
      children: [
        _buildToolbar(),
        const Divider(height: 1),
        Expanded(child: _buildMessageList()),
        const Divider(height: 1),
        _buildInputArea(),
      ],
    );
  }

  Widget _buildToolbar() {
    return Container(
      color: const Color(0xFFF5F5F5),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          const Icon(Icons.psychology, color: Colors.deepPurple),
          const SizedBox(width: 8),
          const Text(
            'Production AI Analyst',
            style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
          ),
          const Spacer(),
          // Context days selector
          const Text('Context: ', style: TextStyle(fontSize: 13)),
          DropdownButton<int>(
            value: _contextDays,
            underline: const SizedBox(),
            style: const TextStyle(fontSize: 13, color: Colors.black87),
            items: const [
              DropdownMenuItem(value: 7, child: Text('7 days')),
              DropdownMenuItem(value: 14, child: Text('14 days')),
              DropdownMenuItem(value: 30, child: Text('30 days')),
              DropdownMenuItem(value: 90, child: Text('90 days')),
            ],
            onChanged: (v) => setState(() => _contextDays = v ?? 30),
          ),
          const SizedBox(width: 8),
          TextButton.icon(
            onPressed: _messages.isEmpty ? null : _clearChat,
            icon: const Icon(Icons.clear_all, size: 18),
            label: const Text('Clear'),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageList() {
    if (_messages.isEmpty && !_loading) {
      return _buildWelcome();
    }
    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
      itemCount: _messages.length + (_loading ? 1 : 0),
      itemBuilder: (ctx, i) {
        if (i == _messages.length) return _buildTypingIndicator();
        return _ChatBubble(message: _messages[i]);
      },
    );
  }

  Widget _buildWelcome() {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 480),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.bar_chart_rounded,
                size: 64, color: Colors.deepPurple),
            const SizedBox(height: 16),
            const Text(
              'Ask anything about production data',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            const Text(
              'Examples:',
              style: TextStyle(color: Colors.grey, fontWeight: FontWeight.w500),
            ),
            const SizedBox(height: 8),
            ..._exampleQuestions.map(
              (q) => Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: InkWell(
                  onTap: () {
                    _controller.text = q;
                    _controller.selection = TextSelection.fromPosition(
                      TextPosition(offset: q.length),
                    );
                  },
                  borderRadius: BorderRadius.circular(8),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 10),
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.deepPurple.shade100),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(children: [
                      Icon(Icons.lightbulb_outline,
                          size: 16,
                          color: Colors.deepPurple.shade300),
                      const SizedBox(width: 8),
                      Expanded(
                          child: Text(q,
                              style: const TextStyle(fontSize: 13))),
                    ]),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTypingIndicator() {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Row(
        children: [
          const _AiAvatar(),
          const SizedBox(width: 8),
          Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(
              color: Colors.grey.shade100,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _Dot(delay: 0),
                _Dot(delay: 200),
                _Dot(delay: 400),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInputArea() {
    return Container(
      color: Colors.white,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: TextField(
              controller: _controller,
              maxLines: 4,
              minLines: 1,
              textInputAction: TextInputAction.newline,
              decoration: InputDecoration(
                hintText: 'Ask about production data…',
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12)),
                contentPadding: const EdgeInsets.symmetric(
                    horizontal: 16, vertical: 12),
              ),
              onSubmitted: (_) => _submit(),
              // Submit on Ctrl+Enter / Cmd+Enter
              onEditingComplete: () {},
            ),
          ),
          const SizedBox(width: 12),
          FilledButton.icon(
            onPressed: _loading ? null : _submit,
            icon: _loading
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.send_rounded),
            label: const Text('Send'),
            style: FilledButton.styleFrom(
              backgroundColor: Colors.deepPurple,
              padding: const EdgeInsets.symmetric(
                  horizontal: 20, vertical: 14),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12)),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Example questions shown on the welcome screen
// ---------------------------------------------------------------------------

const _exampleQuestions = [
  'Which machine had the highest efficiency last month?',
  'What is the total waste and how does it compare per shift?',
  'Which operator produced the most boxes this week?',
  'Show me the completion status of all active purchase orders.',
  'Are there any concerning trends in production output?',
];

// ---------------------------------------------------------------------------
// Chat message data model
// ---------------------------------------------------------------------------

enum _Role { user, ai, error }

class _ChatMessage {
  final _Role role;
  final String text;
  const _ChatMessage({required this.role, required this.text});
}

// ---------------------------------------------------------------------------
// Chat bubble widget
// ---------------------------------------------------------------------------

class _ChatBubble extends StatelessWidget {
  final _ChatMessage message;
  const _ChatBubble({super.key, required this.message});

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == _Role.user;
    final isError = message.role == _Role.error;

    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment:
            isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        children: [
          if (!isUser) ...[
            isError
                ? const Icon(Icons.error_outline, color: Colors.red, size: 32)
                : const _AiAvatar(),
            const SizedBox(width: 8),
          ],
          Flexible(
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxWidth: MediaQuery.sizeOf(context).width * 0.72,
              ),
              child: GestureDetector(
                onLongPress: () =>
                    Clipboard.setData(ClipboardData(text: message.text)),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 16, vertical: 12),
                  decoration: BoxDecoration(
                    color: isUser
                        ? Colors.deepPurple
                        : isError
                            ? Colors.red.shade50
                            : Colors.grey.shade100,
                    borderRadius: BorderRadius.only(
                      topLeft: const Radius.circular(16),
                      topRight: const Radius.circular(16),
                      bottomLeft:
                          Radius.circular(isUser ? 16 : 4),
                      bottomRight:
                          Radius.circular(isUser ? 4 : 16),
                    ),
                    border: isError
                        ? Border.all(color: Colors.red.shade200)
                        : null,
                  ),
                  child: SelectableText(
                    message.text,
                    style: TextStyle(
                      color: isUser
                          ? Colors.white
                          : isError
                              ? Colors.red.shade800
                              : Colors.black87,
                      fontSize: 14,
                      height: 1.5,
                    ),
                  ),
                ),
              ),
            ),
          ),
          if (isUser) ...[
            const SizedBox(width: 8),
            CircleAvatar(
              radius: 16,
              backgroundColor: Colors.deepPurple.shade100,
              child: Text(
                (context
                        .findAncestorWidgetOfExactType<AiAnalysisScreen>()
                        ?.currentUser
                        .name
                        .isNotEmpty ==
                    true)
                    ? context
                        .findAncestorWidgetOfExactType<AiAnalysisScreen>()!
                        .currentUser
                        .name[0]
                        .toUpperCase()
                    : 'U',
                style: const TextStyle(
                    color: Colors.deepPurple,
                    fontWeight: FontWeight.bold,
                    fontSize: 13),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _AiAvatar extends StatelessWidget {
  const _AiAvatar();

  @override
  Widget build(BuildContext context) {
    return CircleAvatar(
      radius: 16,
      backgroundColor: Colors.deepPurple.shade700,
      child: const Icon(Icons.psychology, color: Colors.white, size: 18),
    );
  }
}

// ---------------------------------------------------------------------------
// Animated typing dots
// ---------------------------------------------------------------------------

class _Dot extends StatefulWidget {
  final int delay;
  const _Dot({required this.delay});
  @override
  State<_Dot> createState() => _DotState();
}

class _DotState extends State<_Dot> with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final Animation<double> _anim;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    Future.delayed(Duration(milliseconds: widget.delay), () {
      if (mounted) _ctrl.repeat(reverse: true);
    });
    _anim = Tween<double>(begin: 0.3, end: 1.0).animate(_ctrl);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _anim,
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 3),
        width: 8,
        height: 8,
        decoration: BoxDecoration(
          color: Colors.grey.shade500,
          shape: BoxShape.circle,
        ),
      ),
    );
  }
}
