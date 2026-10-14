import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/feed/feed_controller.dart';
import 'package:factory_finder/features/feed/widgets/feed_common.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Follow / unfollow toggle for a supplier. Hidden for the user's own supplier.
class FollowButton extends ConsumerWidget {
  const FollowButton({super.key, required this.supplierId});

  final String supplierId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(authProvider);
    if (me?.supplierId == supplierId) return const SizedBox.shrink();
    final st = ref.watch(followingProvider);
    final following = st.isFollowing(supplierId);
    final busy = st.busy.contains(supplierId);

    Future<void> onTap() async {
      try {
        await ref.read(followingProvider.notifier).toggle(supplierId);
      } catch (e) {
        if (context.mounted) showFeedError(context, e);
      }
    }

    final label = context.tr(following ? 'feed.following' : 'feed.follow');
    final child = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(following ? Icons.check : Icons.add, size: 18),
        const SizedBox(width: 6),
        Flexible(child: Text(label, overflow: TextOverflow.ellipsis)),
      ],
    );
    final key = ValueKey<String>('feed-follow-$supplierId');
    return following
        ? OutlinedButton(
            key: key,
            style: OutlinedButton.styleFrom(
              visualDensity: VisualDensity.compact,
              tapTargetSize: MaterialTapTargetSize.padded,
            ),
            onPressed: busy ? null : onTap,
            child: child,
          )
        : FilledButton.tonal(
            key: key,
            style: FilledButton.styleFrom(
              visualDensity: VisualDensity.compact,
              tapTargetSize: MaterialTapTargetSize.padded,
            ),
            onPressed: busy ? null : onTap,
            child: child,
          );
  }
}
