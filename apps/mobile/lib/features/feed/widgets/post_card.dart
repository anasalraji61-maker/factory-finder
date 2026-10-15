import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/feed/feed_controller.dart';
import 'package:factory_finder/features/feed/feed_logic.dart';
import 'package:factory_finder/features/feed/widgets/feed_common.dart';
import 'package:factory_finder/features/feed/widgets/follow_button.dart';
import 'package:factory_finder/features/feed/widgets/media_grid.dart';
import 'package:factory_finder/features/feed/widgets/report_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Reports a post through the shared sheet; shows the outcome as a snackbar.
Future<void> reportPostFlow(BuildContext context, WidgetRef ref, String postId) async {
  final sent = await showFeedReportSheet(
    context,
    onSubmit: (reason, details) =>
        ref.read(feedActionsProvider).reportPost(postId, reason, details),
  );
  if (sent && context.mounted) showFeedSnack(context, context.tr('feed.report.done'));
}

/// Mutes / unmutes the supplier (optimistic, rolled back on error).
Future<void> toggleMuteFlow(BuildContext context, WidgetRef ref, String supplierId) async {
  final wasMuted = ref.read(mutedSuppliersProvider).contains(supplierId);
  try {
    await ref.read(feedActionsProvider).toggleMute(supplierId);
    if (context.mounted) {
      showFeedSnack(context, context.tr(wasMuted ? 'feed.unmuted' : 'feed.muted'));
    }
  } catch (e) {
    if (context.mounted) showFeedError(context, e);
  }
}

/// Deletes an own post after confirmation. Returns true when it was deleted.
Future<bool> deletePostFlow(BuildContext context, WidgetRef ref, String postId) async {
  final ok = await confirmFeedAction(
    context,
    title: context.tr('feed.delete_post_confirm'),
    confirmLabel: context.tr('feed.delete'),
  );
  if (!ok) return false;
  try {
    await ref.read(feedActionsProvider).deletePost(postId);
    if (context.mounted) showFeedSnack(context, context.tr('feed.deleted'));
    return true;
  } catch (e) {
    if (context.mounted) showFeedError(context, e);
    return false;
  }
}

class SupplierAvatar extends StatelessWidget {
  const SupplierAvatar({super.key, required this.label, this.radius = 20});

  final String label;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return CircleAvatar(
      radius: radius,
      backgroundColor: scheme.primaryContainer,
      foregroundColor: scheme.onPrimaryContainer,
      child: ExcludeSemantics(
        child: Text(
          label,
          maxLines: 1,
          overflow: TextOverflow.clip,
          style: TextStyle(fontWeight: FontWeight.w800, fontSize: radius * 0.8),
        ),
      ),
    );
  }
}

/// One feed post. State (likes, counts) lives in [PostStore], so this widget
/// only needs the id. With [detail] a tap on the card does nothing.
class PostCard extends ConsumerWidget {
  const PostCard({super.key, required this.postId, this.detail = false});

  final String postId;
  final bool detail;

  Future<void> _toggleLike(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(feedActionsProvider).toggleLike(postId);
    } catch (e) {
      if (context.mounted) showFeedError(context, e);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final post = ref.watch(feedPostProvider(postId));
    if (post == null) return const SizedBox.shrink();
    final me = ref.watch(authProvider);
    final supplier = ref.watch(supplierProvider(post.supplierId));
    final theme = Theme.of(context);
    final secondary = AppColors.secondaryOf(context);
    final isMuted = ref.watch(mutedSuppliersProvider.select((m) => m.contains(post.supplierId)));
    final mine = me?.supplierId != null && me?.supplierId == post.supplierId;
    final name = supplier.maybeWhen(data: (s) => s.name, orElse: () => post.supplierId);
    final verified = supplier.maybeWhen(data: (s) => s.verified, orElse: () => false);

    void openDetail() {
      if (!detail) context.push('/feed/post/${post.id}');
    }

    final header = InkWell(
      onTap: () => context.push('/supplier/${post.supplierId}'),
      borderRadius: BorderRadius.circular(AppRadius.sm),
      child: Row(
        children: [
          SupplierAvatar(label: initialsOf(name)),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Row(
              children: [
                Flexible(
                  child: Text(
                    name,
                    key: ValueKey<String>('feed-name-${post.id}'),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                  ),
                ),
                if (verified) ...[
                  const SizedBox(width: 4),
                  Icon(
                    Icons.verified,
                    size: 18,
                    color: AppColors.accent,
                    semanticLabel: context.tr('listing.verified'),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );

    return Card(
      margin: EdgeInsets.zero,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
        side: BorderSide(
          color: theme.brightness == Brightness.dark ? const Color(0xFF26304D) : AppColors.border,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: header),
                PopupMenuButton<String>(
                  key: ValueKey<String>('feed-menu-${post.id}'),
                  tooltip: context.tr('feed.more'),
                  onSelected: (v) async {
                    if (v == 'report') {
                      await reportPostFlow(context, ref, post.id);
                    } else if (v == 'mute') {
                      await toggleMuteFlow(context, ref, post.supplierId);
                    } else if (v == 'delete') {
                      final done = await deletePostFlow(context, ref, post.id);
                      if (done && detail && context.mounted && context.canPop()) context.pop();
                    }
                  },
                  itemBuilder: (_) => [
                    if (!mine)
                      PopupMenuItem<String>(
                        value: 'report',
                        child: Text(context.tr('feed.report.action')),
                      ),
                    if (!mine)
                      PopupMenuItem<String>(
                        value: 'mute',
                        child: Text(context.tr(isMuted ? 'feed.unmute' : 'feed.mute')),
                      ),
                    if (mine)
                      PopupMenuItem<String>(
                        value: 'delete',
                        child: Text(context.tr('feed.delete')),
                      ),
                  ],
                ),
              ],
            ),
            Wrap(
              spacing: AppSpacing.md,
              runSpacing: AppSpacing.xs,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  feedTimeLabel(context, post.createdAt),
                  style: theme.textTheme.bodySmall?.copyWith(color: secondary),
                ),
                FollowButton(supplierId: post.supplierId),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            InkWell(
              onTap: openDetail,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
                child: SizedBox(
                  width: double.infinity,
                  child: Text(
                    post.body,
                    key: ValueKey<String>('feed-body-${post.id}'),
                    maxLines: detail ? null : 8,
                    overflow: detail ? TextOverflow.visible : TextOverflow.ellipsis,
                    style: theme.textTheme.bodyMedium?.copyWith(height: 1.5),
                  ),
                ),
              ),
            ),
            if (post.media.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: openDetail,
                child: PostMediaGrid(urls: post.media),
              ),
            ],
            if (post.tags.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: [
                  for (final t in post.tags)
                    Text(
                      '#$t',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.primary,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                ],
              ),
            ],
            if (post.listingRef != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Align(
                alignment: AlignmentDirectional.centerStart,
                child: ActionChip(
                  key: ValueKey<String>('feed-listing-${post.id}'),
                  avatar: const Icon(Icons.inventory_2_outlined, size: 18),
                  label: Text(context.tr('feed.view_listing')),
                  onPressed: () => context.push('/listing/${post.listingRef}'),
                ),
              ),
            ],
            const SizedBox(height: AppSpacing.xs),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.xs,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Semantics(
                  button: true,
                  toggled: post.viewerLiked,
                  label: context.tr(post.viewerLiked ? 'feed.unlike' : 'feed.like'),
                  excludeSemantics: true,
                  onTap: () => _toggleLike(context, ref),
                  child: TextButton(
                    key: ValueKey<String>('feed-like-${post.id}'),
                    style: TextButton.styleFrom(
                      minimumSize: const Size(48, 48),
                      foregroundColor: post.viewerLiked ? AppColors.danger : secondary,
                    ),
                    onPressed: () => _toggleLike(context, ref),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(post.viewerLiked ? Icons.favorite : Icons.favorite_border, size: 22),
                        const SizedBox(width: 6),
                        Text(
                          '${post.likeCount}',
                          key: ValueKey<String>('feed-like-count-${post.id}'),
                        ),
                      ],
                    ),
                  ),
                ),
                Semantics(
                  button: true,
                  label: context.tr('feed.comments'),
                  excludeSemantics: true,
                  onTap: openDetail,
                  child: TextButton(
                    key: ValueKey<String>('feed-comments-${post.id}'),
                    style: TextButton.styleFrom(
                      minimumSize: const Size(48, 48),
                      foregroundColor: secondary,
                    ),
                    onPressed: openDetail,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.chat_bubble_outline, size: 22),
                        const SizedBox(width: 6),
                        Text(
                          '${post.commentCount}',
                          key: ValueKey<String>('feed-comment-count-${post.id}'),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
