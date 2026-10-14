import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/discover/data/compare_logic.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Bottom bar listing how many listings are selected for comparison.
/// Renders nothing while the tray is empty.
class CompareTray extends ConsumerWidget {
  const CompareTray({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(compareProvider);
    if (items.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.surface,
      elevation: 8,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
          child: Row(
            children: [
              Icon(Icons.compare_arrows, color: theme.colorScheme.primary),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  context.tr('compare.tray', {
                    'n': '${items.length}',
                    'max': '${CompareNotifier.maxItems}',
                  }),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              IconButton(
                tooltip: context.tr('compare.clear'),
                icon: const Icon(Icons.close),
                onPressed: () => ref.read(compareProvider.notifier).clear(),
              ),
              FilledButton(
                onPressed: items.length < 2 ? null : () => context.push('/compare'),
                child: Text(context.tr('compare.open')),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
