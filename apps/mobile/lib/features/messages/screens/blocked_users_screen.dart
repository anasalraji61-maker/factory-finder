import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Settings -> Privacy -> Blocked users: list and unblock.
class BlockedUsersScreen extends ConsumerWidget {
  const BlockedUsersScreen({super.key});

  Future<void> _unblock(BuildContext context, WidgetRef ref, BlockedUser user) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(ctx.tr('messages.unblock.title')),
        content: Text(ctx.tr('messages.unblock.body', {'name': user.userId})),
        actions: [
          TextButton(
            key: const ValueKey<String>('blocked-cancel'),
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(ctx.tr('common.cancel')),
          ),
          FilledButton(
            key: const ValueKey<String>('blocked-confirm'),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(ctx.tr('messages.unblock.confirm')),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    final doneText = context.tr('messages.unblock.done');
    try {
      await ref.read(messagingRepositoryProvider).unblockUser(user.userId);
    } catch (e) {
      if (context.mounted) {
        messenger
          ..clearSnackBars()
          ..showSnackBar(SnackBar(content: Text(localizedError(context, e))));
      }
      return;
    }
    ref.invalidate(blockedUsersProvider);
    ref.invalidate(conversationsProvider);
    ref.invalidate(unreadTotalProvider);
    messenger
      ..clearSnackBars()
      ..showSnackBar(SnackBar(content: Text(doneText)));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(blockedUsersProvider);
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('messages.blocked.title'))),
      body: async.when(
        loading: () => const LoadingList(),
        error: (e, _) => ErrorState(
          error: e,
          onRetry: () => ref.invalidate(blockedUsersProvider),
        ),
        data: (list) {
          if (list.isEmpty) {
            return EmptyState(
              icon: Icons.block_outlined,
              title: context.tr('messages.blocked.empty'),
              message: context.tr('messages.blocked.empty_msg'),
            );
          }
          return ListView(
            padding: const EdgeInsets.all(AppSpacing.lg),
            children: [
              Text(
                context.tr('messages.blocked.intro'),
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: AppColors.textSecondary),
              ),
              const SizedBox(height: AppSpacing.md),
              for (final u in list)
                AppCard(
                  key: ValueKey<String>('blocked-${u.userId}'),
                  padding: EdgeInsets.zero,
                  child: ListTile(
                    leading: ConversationAvatarLetter(id: u.userId),
                    title: Text(u.userId, maxLines: 1, overflow: TextOverflow.ellipsis),
                    trailing: TextButton(
                      key: ValueKey<String>('unblock-${u.userId}'),
                      onPressed: () => _unblock(context, ref, u),
                      child: Text(context.tr('messages.unblock.menu')),
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

/// Circle with the first character of [id] (blocked users have no name).
class ConversationAvatarLetter extends StatelessWidget {
  const ConversationAvatarLetter({super.key, required this.id});
  final String id;

  @override
  Widget build(BuildContext context) {
    final t = id.trim();
    final letter = t.isEmpty ? '?' : String.fromCharCode(t.runes.first).toUpperCase();
    return CircleAvatar(
      backgroundColor: AppColors.textSecondary.withOpacity(0.15),
      child: Text(letter),
    );
  }
}
