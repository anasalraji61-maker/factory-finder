import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/feed/widgets/feed_common.dart';
import 'package:factory_finder/features/feed/widgets/post_list_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Icon button for the Discover header that opens the feed.
class FeedEntryButton extends StatelessWidget {
  const FeedEntryButton({super.key});

  @override
  Widget build(BuildContext context) => IconButton(
        key: const ValueKey<String>('feed-entry'),
        tooltip: context.tr('feed.title'),
        icon: const Icon(Icons.dynamic_feed_outlined),
        onPressed: () => context.push('/feed'),
      );
}

/// Social feed: posts of followed suppliers or trending posts.
class FeedScreen extends ConsumerStatefulWidget {
  const FeedScreen({super.key});

  @override
  ConsumerState<FeedScreen> createState() => _FeedScreenState();
}

class _FeedScreenState extends ConsumerState<FeedScreen> {
  /// null = default (following when signed in, else trending).
  bool? _following;

  @override
  Widget build(BuildContext context) {
    final me = ref.watch(authProvider);
    final canPost = ref.watch(verifiedSupplierProvider);
    final following = _following ?? (me != null);
    final key = following ? 'home' : 'trending';

    return Scaffold(
      appBar: AppBar(
        title: Text(context.tr('feed.title')),
        actions: [
          if (canPost)
            IconButton(
              key: const ValueKey<String>('feed-compose'),
              tooltip: context.tr('feed.compose'),
              icon: const Icon(Icons.edit_outlined),
              onPressed: () => context.push('/feed/new'),
            ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.lg,
              AppSpacing.sm,
              AppSpacing.lg,
              AppSpacing.xs,
            ),
            child: Align(
              alignment: AlignmentDirectional.centerStart,
              child: Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: [
                  ChoiceChip(
                    key: const ValueKey<String>('feed-mode-home'),
                    label: Text(context.tr('feed.mode.following')),
                    selected: following,
                    onSelected: (_) => setState(() => _following = true),
                  ),
                  ChoiceChip(
                    key: const ValueKey<String>('feed-mode-trending'),
                    label: Text(context.tr('feed.mode.trending')),
                    selected: !following,
                    onSelected: (_) => setState(() => _following = false),
                  ),
                ],
              ),
            ),
          ),
          Expanded(
            child: PostListView(
              key: ValueKey<String>('feed-view-$key'),
              listKey: key,
              emptyAction: following
                  ? OutlinedButton(
                      onPressed: () => setState(() => _following = false),
                      child: Text(context.tr('feed.mode.trending')),
                    )
                  : null,
            ),
          ),
        ],
      ),
    );
  }
}
