import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/assistant/assistant_models.dart';
import 'package:factory_finder/features/assistant/assistant_repository.dart';
import 'package:factory_finder/features/assistant/assistant_strings.dart';
import 'package:factory_finder/features/assistant/widgets/assistant_card_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

class _Msg {
  const _Msg.user(this.text)
      : fromUser = true,
        answer = null,
        isError = false;
  const _Msg.bot(this.text, this.answer)
      : fromUser = false,
        isError = false;
  const _Msg.error(this.text)
      : fromUser = false,
        answer = null,
        isError = true;

  final bool fromUser;
  final String text;
  final AssistantAnswer? answer;
  final bool isError;
}

class AssistantScreen extends ConsumerStatefulWidget {
  const AssistantScreen({super.key});

  @override
  ConsumerState<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends ConsumerState<AssistantScreen> {
  final _controller = TextEditingController();
  final _scroll = ScrollController();
  final List<_Msg> _messages = [];
  bool _busy = false;

  @override
  void dispose() {
    _controller.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _busy) return;
    final lang = Localizations.localeOf(context).languageCode;
    final destination = ref.read(destinationProvider);
    final repo = ref.read(assistantRepositoryProvider);
    setState(() {
      _messages.add(_Msg.user(text));
      _busy = true;
      _controller.clear();
    });
    _scrollToEnd();
    _Msg reply;
    try {
      final a = await repo.ask(text, lang: lang, destination: destination);
      reply = _Msg.bot(a.text, a);
    } catch (e) {
      reply = _Msg.error(assistantErrorText(e, lang));
    }
    if (!mounted) return;
    setState(() {
      _messages.add(reply);
      _busy = false;
    });
    _scrollToEnd();
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('assistant.title'))),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: _messages.isEmpty
                  ? EmptyState(
                      icon: Icons.smart_toy_outlined,
                      title: context.tr('assistant.empty_title'),
                      message: context.tr('assistant.empty_msg'),
                    )
                  : ListView.builder(
                      controller: _scroll,
                      padding: const EdgeInsets.all(AppSpacing.lg),
                      itemCount: _messages.length + (_busy ? 1 : 0),
                      itemBuilder: (context, i) {
                        if (i >= _messages.length) {
                          return Padding(
                            padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                            child: Text(
                              context.tr('assistant.thinking'),
                              style: const TextStyle(color: AppColors.textSecondary),
                            ),
                          );
                        }
                        return _MessageView(
                          msg: _messages[i],
                          onNavigate: (route) => context.push(route),
                        );
                      },
                    ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.md, AppSpacing.xs, AppSpacing.md, AppSpacing.md),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      enabled: !_busy,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _send(),
                      inputFormatters: [LengthLimitingTextInputFormatter(1000)],
                      decoration: InputDecoration(hintText: context.tr('assistant.hint')),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  IconButton.filled(
                    tooltip: context.tr('assistant.send'),
                    onPressed: _busy ? null : _send,
                    icon: const Icon(Icons.send_rounded),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _MessageView extends StatelessWidget {
  const _MessageView({required this.msg, required this.onNavigate});

  final _Msg msg;
  final void Function(String route) onNavigate;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final user = msg.fromUser;
    final answer = msg.answer;
    final bubbleColor = user
        ? scheme.primary
        : (msg.isError ? AppColors.danger.withOpacity(0.10) : scheme.surfaceContainerHighest);
    final textColor = user ? scheme.onPrimary : null;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Align(
        alignment: user ? AlignmentDirectional.centerEnd : AlignmentDirectional.centerStart,
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.9),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (msg.text.isNotEmpty)
                Container(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  decoration: BoxDecoration(
                    color: bubbleColor,
                    borderRadius: BorderRadius.circular(AppRadius.md),
                  ),
                  child: Text(msg.text, style: TextStyle(color: textColor, height: 1.4)),
                ),
              if (answer != null) ...[
                for (final c in answer.cards)
                  Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.sm),
                    child: AssistantCardView(card: c, onNavigate: onNavigate),
                  ),
                if (answer.textFiltered)
                  Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.xs),
                    child: Text(
                      context.tr('assistant.filtered'),
                      style: Theme.of(context)
                          .textTheme
                          .bodySmall
                          ?.copyWith(color: AppColors.textSecondary),
                    ),
                  ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
