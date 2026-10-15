import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/feed/feed_controller.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:factory_finder/features/feed/widgets/feed_common.dart';
import 'package:factory_finder/features/feed/widgets/post_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Pull-to-refresh list of [PostCard]s for one feed list ([listKey] is
/// `home`, `trending` or `sup:<id>`), with a "load more" tail.
class PostListView extends ConsumerWidget {
  const PostListView({
    super.key,
    required this.listKey,
    this.header,
    this.emptyTitleKey = 'feed.empty',
    this.emptyHintKey = 'feed.empty_hint',
    this.emptyAction,
  });

  final String listKey;
  final Widget? header;
  final String emptyTitleKey;
  final String emptyHintKey;
  final Widget? emptyAction;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final raw = ref.watch(feedListProvider(listKey));
    final ctrl = ref.read(feedListProvider(listKey).notifier);
    // Posts that vanished from the store (hidden / deleted, e.g. a like got
    // 404) disappear from the list; rebuild only when that count changes.
    ref.watch(feedPostStoreProvider.select((m) => raw.ids.where(m.containsKey).length));
    final known = ref.read(feedPostStoreProvider);
    // Optimistic mute: posts of muted suppliers leave the list at once.
    final muted = ref.watch(mutedSuppliersProvider);
    final shown = raw.ids
        .where((id) => known.containsKey(id) && !muted.contains(known[id]!.supplierId))
        .toList();
    final st = shown.length == raw.ids.length ? raw : raw.copyWith(ids: shown);

    // Banner when the personalised feed fell back to trending.
    final showFallback = listKey == 'home' && st.source == FeedSource.trending && st.ids.isNotEmpty;
    final head = <Widget>[
      if (st.fromCache && st.ids.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.md),
          child: OfflineBanner(savedNote: true, onRetry: ctrl.refresh),
        ),
      if (st.error != null && st.ids.isNotEmpty && !st.loading)
        Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.md),
          child: Row(
            key: const ValueKey<String>('feed-refresh-error'),
            children: [
              Expanded(
                child: Text(
                  feedErrorMessage(context, st.error!),
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
              TextButton(
                onPressed: ctrl.refresh,
                child: Text(context.tr('common.retry')),
              ),
            ],
          ),
        ),
      if (header != null) header!,
      if (showFallback)
        Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.md),
          child: Container(
            key: const ValueKey<String>('feed-fallback-banner'),
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.secondaryContainer,
              borderRadius: BorderRadius.circular(AppRadius.sm),
            ),
            child: Text(
              context.tr('feed.fallback_trending'),
              style: TextStyle(color: Theme.of(context).colorScheme.onSecondaryContainer),
            ),
          ),
        ),
    ];

    Widget body;
    if (st.loading) {
      body = ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [...head, const LoadingList(itemCount: 3)],
      );
    } else if (st.error != null && st.ids.isEmpty) {
      body = ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          ...head,
          ErrorState(
            error: st.error,
            message: feedErrorMessage(context, st.error!),
            onRetry: ctrl.refresh,
          ),
        ],
      );
    } else if (st.ids.isEmpty) {
      body = ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          ...head,
          EmptyState(
            icon: Icons.dynamic_feed_outlined,
            title: context.tr(emptyTitleKey),
            message: context.tr(emptyHintKey),
            action: emptyAction,
          ),
        ],
      );
    } else {
      body = ListView.separated(
        key: ValueKey<String>('feed-list-$listKey'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.lg),
        itemCount: st.ids.length + 2,
        separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
        itemBuilder: (context, i) {
          if (i == 0) {
            return head.isEmpty ? const SizedBox.shrink() : Column(children: head);
          }
          if (i == st.ids.length + 1) return _Tail(state: st, onMore: ctrl.loadMore);
          return PostCard(postId: st.ids[i - 1]);
        },
      );
    }

    return RefreshIndicator(onRefresh: ctrl.refresh, child: body);
  }
}

class _Tail extends StatelessWidget {
  const _Tail({required this.state, required this.onMore});

  final FeedListState state;
  final VoidCallback onMore;

  @override
  Widget build(BuildContext context) {
    if (state.loadingMore) {
      return const Padding(
        padding: EdgeInsets.all(AppSpacing.lg),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (state.moreError != null) {
      return Column(
        children: [
          Text(
            feedErrorMessage(context, state.moreError!),
            textAlign: TextAlign.center,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
          const SizedBox(height: AppSpacing.sm),
          OutlinedButton(
            key: const ValueKey<String>('feed-load-more'),
            onPressed: onMore,
            child: Text(context.tr('common.retry')),
          ),
        ],
      );
    }
    if (!state.hasMore) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
        child: Text(
          context.tr('feed.end'),
          textAlign: TextAlign.center,
          style: TextStyle(color: AppColors.secondaryOf(context)),
        ),
      );
    }
    return Center(
      child: OutlinedButton(
        key: const ValueKey<String>('feed-load-more'),
        style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
        onPressed: onMore,
        child: Text(context.tr('feed.load_more')),
      ),
    );
  }
}
