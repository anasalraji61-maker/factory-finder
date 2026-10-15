import 'dart:async';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/messages/data/chat_logic.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:factory_finder/features/my_products/media/media_logic.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

String contextLabelKey(String type) {
  switch (type) {
    case 'request':
      return 'messages.ctx.request';
    case 'deal':
      return 'messages.ctx.deal';
    default:
      return 'messages.ctx.listing';
  }
}

IconData contextIcon(String type) {
  switch (type) {
    case 'request':
      return Icons.request_quote_outlined;
    case 'deal':
      return Icons.handshake_outlined;
    default:
      return Icons.inventory_2_outlined;
  }
}

class ConversationAvatar extends StatelessWidget {
  const ConversationAvatar({super.key, required this.title, this.radius = 24});
  final String title;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final t = title.trim();
    final letter = t.isEmpty ? '?' : String.fromCharCode(t.runes.first);
    return CircleAvatar(
      radius: radius,
      backgroundColor: AppColors.primary.withOpacity(0.12),
      child: Text(
        letter,
        style: const TextStyle(
          color: AppColors.primary,
          fontWeight: FontWeight.w800,
          fontSize: 18,
        ),
      ),
    );
  }
}

class ConversationsScreen extends ConsumerStatefulWidget {
  const ConversationsScreen({super.key});

  @override
  ConsumerState<ConversationsScreen> createState() => _ConversationsScreenState();
}

class _ConversationsScreenState extends ConsumerState<ConversationsScreen>
    with WidgetsBindingObserver {
  Timer? _poll;
  bool _foreground = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _poll = Timer.periodic(const Duration(seconds: 8), (_) {
      // The tab stays mounted (indexed stack) while hidden; only poll when
      // it is the visible branch (hidden branches have tickers disabled).
      if (mounted && _foreground && TickerMode.of(context)) ref.invalidate(conversationsProvider);
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Paused/hidden app: no polling (battery, 401 spam after a token expiry).
    final fg = state == AppLifecycleState.resumed || state == AppLifecycleState.inactive;
    if (fg == _foreground) return;
    _foreground = fg;
    if (fg && mounted) ref.invalidate(conversationsProvider);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _poll?.cancel();
    super.dispose();
  }

  String _time(BuildContext context, DateTime d) {
    final now = DateTime.now();
    if (isSameDay(d, now)) return hhmm(d);
    if (isSameDay(d, now.subtract(const Duration(days: 1)))) {
      return context.tr('messages.yesterday');
    }
    return ymd(d);
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(conversationsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('messages.title'))),
      body: async.when(
        // Background polling reloads the provider; keep the list on screen.
        skipLoadingOnReload: true,
        loading: () => const LoadingList(),
        error: (e, _) => ErrorState(
          error: e,
          onRetry: () => ref.invalidate(conversationsProvider),
        ),
        data: (list) {
          if (list.isEmpty) {
            return EmptyState(
              icon: Icons.chat_bubble_outline,
              title: context.tr('messages.empty_title'),
              message: context.tr('messages.empty_msg'),
            );
          }
          return RefreshIndicator(
            onRefresh: () async => ref.refresh(conversationsProvider.future),
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
              itemCount: list.length,
              separatorBuilder: (_, __) => const Divider(height: 1, indent: 76),
              itemBuilder: (context, i) => _tile(context, list[i]),
            ),
          );
        },
      ),
    );
  }

  Widget _tile(BuildContext context, Conversation c) {
    final theme = Theme.of(context);
    final unread = c.unread > 0;
    final ctx = c.context;
    MessageAttachment? firstImage;
    for (final a in c.lastAttachments) {
      if (a.isImage) {
        firstImage = a;
        break;
      }
    }
    return InkWell(
      onTap: () => context.push('/chat/${c.id}'),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.md,
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ConversationAvatar(title: c.title),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          c.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.titleSmall?.copyWith(
                            fontWeight: unread ? FontWeight.w800 : FontWeight.w600,
                          ),
                        ),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Text(
                        _time(context, c.lastAt),
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: unread ? AppColors.primary : AppColors.textSecondary,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      if (firstImage != null) ...[
                        AppNetworkImage(
                          key: ValueKey('conv-thumb-${c.id}'),
                          url: mediaThumbUrl(ref.read(apiClientProvider).baseUrl, firstImage.url),
                          width: 24,
                          height: 24,
                          borderRadius: BorderRadius.circular(4),
                        ),
                        const SizedBox(width: 6),
                      ] else if (previewKeyOf(c.lastMessage) == null &&
                          c.lastAttachments.isNotEmpty) ...[
                        const Icon(Icons.attach_file, size: 16, color: AppColors.textSecondary),
                      ],
                      Expanded(
                        child: Text(
                          localizedPreview(c.lastMessage, (k) => context.tr(k)),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: unread ? null : AppColors.textSecondary,
                          ),
                        ),
                      ),
                      if (unread) ...[
                        const SizedBox(width: AppSpacing.sm),
                        Container(
                          constraints: const BoxConstraints(minWidth: 22),
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: AppColors.primary,
                            borderRadius: BorderRadius.circular(11),
                          ),
                          child: Text(
                            '${c.unread}',
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 12,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                  if (ctx != null) ...[
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Icon(contextIcon(ctx.type), size: 14, color: AppColors.textSecondary),
                        const SizedBox(width: 4),
                        Flexible(
                          child: Text(
                            '${context.tr(contextLabelKey(ctx.type))}'
                            '${ctx.title == null ? '' : ' · ${ctx.title}'}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.bodySmall
                                ?.copyWith(color: AppColors.textSecondary),
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
