import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/tracking/screens/add_shipment_sheet.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/tracking_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

class TrackingListScreen extends ConsumerWidget {
  const TrackingListScreen({super.key});

  Future<void> _openAdd(BuildContext context, WidgetRef ref) async {
    final added = await showModalBottomSheet<Shipment>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => const AddShipmentSheet(),
    );
    if (added != null) {
      if (!context.mounted) return;
      ref.invalidate(shipmentsProvider);
      if (context.mounted) context.push('/logistics/tracking/${added.id}');
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(shipmentsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('tracking.title'))),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _openAdd(context, ref),
        icon: const Icon(Icons.add),
        label: Text(context.tr('tracking.add')),
      ),
      body: async.when(
        loading: () => const LoadingList(),
        error: (e, _) => ErrorState(
          error: e,
          onRetry: () => ref.invalidate(shipmentsProvider),
        ),
        data: (list) {
          if (list.isEmpty) {
            return EmptyState(
              icon: Icons.local_shipping_outlined,
              title: context.tr('tracking.empty_title'),
              message: context.tr('tracking.empty_msg'),
            );
          }
          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(shipmentsProvider);
              await ref.read(shipmentsProvider.future);
            },
            child: ListView.separated(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg, AppSpacing.md, AppSpacing.lg, 96),
              itemCount: list.length,
              separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
              itemBuilder: (context, i) => _ShipmentCard(shipment: list[i]),
            ),
          );
        },
      ),
    );
  }
}

class _ShipmentCard extends StatelessWidget {
  const _ShipmentCard({required this.shipment});
  final Shipment shipment;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = shipment;
    final color = statusColor(s.status);
    return AppCard(
      onTap: () => context.push('/logistics/tracking/${s.id}'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(statusIcon(s.status), color: color),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Directionality(
                  textDirection: TextDirection.ltr,
                  child: Text(
                    s.reference,
                    style: theme.textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w800, letterSpacing: 0.5),
                  ),
                ),
              ),
              StatusChip(status: s.status),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            '${context.tr(typeKey(s.referenceType))}'
            '${s.carrier == null ? '' : ' · ${s.carrier}'}',
            style: theme.textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.md),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(
              value: s.progressValue,
              minHeight: 8,
              color: color,
              backgroundColor: AppColors.border,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: [
              Expanded(
                child: Text(
                  '${s.origin} ← ${s.destination}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall,
                ),
              ),
              if (s.eta != null)
                Text(
                  '${context.tr('tracking.eta')}: ${dateLabel(s.eta!)}',
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
