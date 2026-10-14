import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/deals/deals_models.dart';
import 'package:factory_finder/features/deals/deals_repository.dart';
import 'package:factory_finder/features/deals/widgets/deal_lifecycle_section.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// One deal opened from the deals list (buyer or supplier): summary plus the
/// lifecycle actions for the caller's role.
class DealDetailScreen extends ConsumerWidget {
  const DealDetailScreen({super.key, required this.dealId});

  final String dealId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(dealDetailProvider(dealId));
    final session = ref.watch(acceptedDealsProvider);
    final me = ref.watch(authProvider);
    final isMock = ref.watch(apiClientProvider).isMock;
    final myId = me?.id ?? (isMock ? kMockUserId : null);

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('deals.detail.title'))),
      body: async.when(
        loading: () => const LoadingList(itemCount: 3),
        error: (e, _) => ErrorState(
          message: describeError(e),
          onRetry: () => ref.invalidate(dealDetailProvider(dealId)),
        ),
        data: (loaded) {
          // Prefer the copy updated by a lifecycle action in this session.
          final fresh = session[loaded.requestId];
          final deal = fresh != null && fresh.id == loaded.id ? fresh : loaded;
          final role = dealRoleFor(deal, myId, demo: isMock);
          final theme = Theme.of(context);
          return ListView(
            padding: const EdgeInsets.all(AppSpacing.lg),
            children: [
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      deal.id,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: AppColors.textSecondary),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      context.tr('deals.detail.goods'),
                      style: theme.textTheme.bodySmall,
                    ),
                    Text(
                      deal.subtotal.format(),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleMedium
                          ?.copyWith(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      '${context.tr('deals.detail.commission')}: ${deal.commission.format()}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall,
                    ),
                    if (role.isBuyer) ...[
                      const SizedBox(height: AppSpacing.sm),
                      OutlinedButton(
                        key: const Key('deal_open_request'),
                        onPressed: () => context.push('/requests/${deal.requestId}'),
                        child: Text(context.tr('deals.detail.open_request')),
                      ),
                    ],
                  ],
                ),
              ),
              if (role != DealRole.none) ...[
                const SizedBox(height: AppSpacing.lg),
                DealLifecycleSection(deal: deal, role: role),
              ],
            ],
          );
        },
      ),
    );
  }
}
