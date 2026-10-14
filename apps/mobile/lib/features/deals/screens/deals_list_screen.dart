import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:factory_finder/features/requests/screens/requests_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

Color dealStatusColor(String status) {
  switch (status) {
    case 'completed':
    case 'paid':
      return AppColors.success;
    case 'in_fulfilment':
      return AppColors.primary;
    case 'pending_payment':
      return AppColors.warning;
    case 'disputed':
    case 'cancelled':
    case 'refunded':
      return AppColors.danger;
    default:
      return AppColors.textSecondary;
  }
}

/// Deals accepted in this session (in-memory only), newest first.
class DealsListScreen extends ConsumerWidget {
  const DealsListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final deals = ref.watch(acceptedDealsProvider).values.toList()
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('deals.list.title'))),
      body: deals.isEmpty
          ? EmptyState(
              icon: Icons.assignment_turned_in_outlined,
              title: context.tr('deals.list.empty_title'),
              message: context.tr('deals.list.empty_msg'),
            )
          : ListView.separated(
              padding: const EdgeInsets.all(AppSpacing.lg),
              itemCount: deals.length,
              separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.sm),
              itemBuilder: (context, i) => _DealTile(deal: deals[i]),
            ),
    );
  }
}

class _DealTile extends StatelessWidget {
  const _DealTile({required this.deal});
  final Deal deal;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final statusKey = 'deals.status.${deal.status}';
    final label = context.tr(statusKey);
    return AppCard(
      key: Key('deal_tile_${deal.id}'),
      onTap: () => context.push('/requests/${deal.requestId}'),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  deal.subtotal.format(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 2),
                Text(
                  deal.id,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Flexible(
            child: StatusPill(
              label: label == statusKey ? deal.status : label,
              color: dealStatusColor(deal.status),
            ),
          ),
        ],
      ),
    );
  }
}
