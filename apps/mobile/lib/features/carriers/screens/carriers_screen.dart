import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/carriers/data/carrier_models.dart';
import 'package:factory_finder/features/carriers/data/carriers_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

const Map<String, IconData> _modeIcons = {
  'sea': Icons.directions_boat_outlined,
  'air': Icons.flight_outlined,
  'rail': Icons.train_outlined,
  'road': Icons.local_shipping_outlined,
};

class CarriersScreen extends ConsumerWidget {
  const CarriersScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final group = ref.watch(carrierModeGroupProvider);
    final async = ref.watch(carriersProvider);
    final labels = [
      context.tr('carriers.mode.all'),
      for (final g in kCarrierModeGroups) context.tr('carriers.mode.$g'),
    ];
    final selected = group == null ? 0 : kCarrierModeGroups.indexOf(group) + 1;

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('carriers.title'))),
      body: Column(
        children: [
          const SizedBox(height: AppSpacing.md),
          FilterChipBar(
            labels: labels,
            selectedIndex: selected < 0 ? 0 : selected,
            onSelected: (i) => ref.read(carrierModeGroupProvider.notifier).state =
                i == 0 ? null : kCarrierModeGroups[i - 1],
          ),
          const SizedBox(height: AppSpacing.sm),
          Expanded(
            child: async.when(
              loading: () => const LoadingList(),
              error: (e, _) => ErrorState(
                message: e.toString(),
                onRetry: () => ref.invalidate(carriersProvider),
              ),
              data: (all) {
                final list = filterByModeGroup(all, group);
                return RefreshIndicator(
                  onRefresh: () async {
                    ref.invalidate(carriersProvider);
                    try {
                      await ref.read(carriersProvider.future);
                    } catch (_) {}
                  },
                  child: list.isEmpty
                      ? ListView(
                          physics: const AlwaysScrollableScrollPhysics(),
                          children: [
                            EmptyState(
                              icon: Icons.directions_boat_outlined,
                              title: context.tr('carriers.empty_title'),
                              message: context.tr('carriers.empty_msg'),
                            ),
                          ],
                        )
                      : ListView.separated(
                          physics: const AlwaysScrollableScrollPhysics(),
                          padding: const EdgeInsets.all(AppSpacing.lg),
                          itemCount: list.length,
                          separatorBuilder: (_, __) =>
                              const SizedBox(height: AppSpacing.sm),
                          itemBuilder: (context, i) => CarrierCard(carrier: list[i]),
                        ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class RatingStars extends StatelessWidget {
  const RatingStars({super.key, required this.rating, this.size = 16});
  final double rating;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 1; i <= 5; i++)
          Icon(
            rating >= i
                ? Icons.star_rounded
                : (rating >= i - 0.5 ? Icons.star_half_rounded : Icons.star_outline_rounded),
            size: size,
            color: AppColors.warning,
          ),
        const SizedBox(width: AppSpacing.xs),
        Text(rating.toStringAsFixed(1),
            style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12)),
      ],
    );
  }
}

class CarrierCard extends StatelessWidget {
  const CarrierCard({super.key, required this.carrier});
  final Carrier carrier;

  Widget _regions(BuildContext context, String labelKey, List<String> items) {
    if (items.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.sm),
      child: Wrap(
        spacing: AppSpacing.xs,
        runSpacing: AppSpacing.xs,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Text(context.tr(labelKey),
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: AppColors.textSecondary)),
          for (final r in items)
            Chip(
              visualDensity: VisualDensity.compact,
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
              avatar: isCountryCode(r) ? CountryFlag(countryCode: r, size: 14) : null,
              label: Text(r, style: const TextStyle(fontSize: 12)),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final groups = <String>{for (final m in carrier.modes) modeGroup(m)};
    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(carrier.name,
                    style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
              ),
              for (final g in groups)
                Padding(
                  padding: const EdgeInsetsDirectional.only(start: AppSpacing.xs),
                  child: Icon(_modeIcons[g] ?? Icons.local_shipping_outlined,
                      size: 20, color: AppColors.textSecondary),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Row(
            children: [
              RatingStars(rating: carrier.rating),
              const SizedBox(width: AppSpacing.md),
              Text(context.tr('carriers.kind.${carrier.kind}'),
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: AppColors.textSecondary)),
            ],
          ),
          _regions(context, 'carriers.from', carrier.originRegions),
          _regions(context, 'carriers.to', carrier.destinationRegions),
        ],
      ),
    );
  }
}
