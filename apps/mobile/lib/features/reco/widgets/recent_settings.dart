import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/reco/recently_viewed.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Settings card explaining the local-only history, with a clear button.
class RecentlyViewedSettings extends ConsumerWidget {
  const RecentlyViewedSettings({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: AppCard(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: SizedBox(
          width: double.infinity,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Semantics(
                header: true,
                child: Text(
                  context.tr('reco.recent_title'),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(height: 2),
              Text(
                context.tr('reco.recent_hint'),
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: AppColors.secondaryOf(context)),
              ),
              const SizedBox(height: AppSpacing.sm),
              OutlinedButton(
                key: const ValueKey<String>('settings-clear-recent'),
                style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
                onPressed: () async {
                  final messenger = ScaffoldMessenger.of(context);
                  final done = context.tr('reco.recent_cleared');
                  await ref.read(recentlyViewedProvider.notifier).clear();
                  messenger.showSnackBar(SnackBar(content: Text(done)));
                },
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.delete_outline, size: 18),
                    const SizedBox(width: 8),
                    Flexible(
                      child: Text(
                        context.tr('reco.recent_clear'),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
