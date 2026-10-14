import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/feed/widgets/follow_button.dart';
import 'package:factory_finder/features/feed/widgets/post_list_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Posts of one supplier with a follow button.
class SupplierPostsScreen extends ConsumerWidget {
  const SupplierPostsScreen({super.key, required this.supplierId});

  final String supplierId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final name = ref
        .watch(supplierProvider(supplierId))
        .maybeWhen(data: (s) => s.name, orElse: () => supplierId);
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('feed.supplier_posts'))),
      body: PostListView(
        listKey: 'sup:$supplierId',
        emptyTitleKey: 'feed.supplier_empty',
        emptyHintKey: 'feed.supplier_empty_hint',
        header: Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.md),
          child: Wrap(
            spacing: AppSpacing.md,
            runSpacing: AppSpacing.sm,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 260),
                child: Text(
                  name,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              FollowButton(supplierId: supplierId),
            ],
          ),
        ),
      ),
    );
  }
}
