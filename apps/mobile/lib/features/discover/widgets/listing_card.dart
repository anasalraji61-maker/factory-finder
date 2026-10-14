import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/compare_logic.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

String unitLabel(BuildContext context, String unit) {
  final key = 'unit.$unit';
  final label = context.tr(key);
  return label == key ? unit : label;
}

/// Adds/removes [l] from the compare tray; warns when the tray is full.
void toggleCompare(BuildContext context, WidgetRef ref, Listing l) {
  final result = ref.read(compareProvider.notifier).toggle(l);
  if (result == CompareToggle.full) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          context.tr('compare.full', {'n': '${CompareNotifier.maxItems}'}),
        ),
      ),
    );
  }
}

class ListingCard extends ConsumerWidget {
  const ListingCard({super.key, required this.listing});

  final Listing listing;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final inCompare = ref.watch(compareProvider).any((x) => x.id == listing.id);
    final lang = Localizations.localeOf(context).languageCode;
    final theme = Theme.of(context);
    final l = listing;
    final trustLabel = context.tr('trust.${l.supplier.trustBand.json}') +
        (l.supplier.trustScore == null ? '' : ' ${l.supplier.trustScore}');
    return AppCard(
      padding: EdgeInsets.zero,
      onTap: () => context.push('/listing/${l.id}'),
      onLongPress: () => toggleCompare(context, ref, l),
      semanticLabel: context.tr('a11y.listing_card', {
        'title': l.displayTitle(lang),
        'price': l.price.format(),
        'trust': trustLabel,
      }),
      semanticActions: {
        CustomSemanticsAction(
          label: context.tr(inCompare ? 'compare.remove' : 'compare.add'),
        ): () => toggleCompare(context, ref, l),
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AspectRatio(
            aspectRatio: 4 / 3,
            child: Stack(
              fit: StackFit.expand,
              children: [
                AppNetworkImage(
                  url: l.images.isEmpty ? null : l.images.first,
                  borderRadius: const BorderRadius.vertical(
                    top: Radius.circular(AppRadius.md),
                  ),
                ),
                PositionedDirectional(
                  top: 0,
                  end: 0,
                  // 48dp tap target around a 28dp visual.
                  child: SizedBox(
                    width: 48,
                    height: 48,
                    child: Tooltip(
                      message: context.tr(inCompare ? 'compare.remove' : 'compare.add'),
                      child: InkResponse(
                        radius: 24,
                        onTap: () => toggleCompare(context, ref, l),
                        child: Center(
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              color: inCompare
                                  ? theme.colorScheme.primary
                                  : Colors.black.withOpacity(0.55),
                              shape: BoxShape.circle,
                            ),
                            child: Padding(
                              padding: const EdgeInsets.all(5),
                              child: Icon(
                                inCompare ? Icons.check : Icons.compare_arrows,
                                size: 18,
                                color: inCompare
                                    ? theme.colorScheme.onPrimary
                                    : Colors.white,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
                if (l.condition != ItemCondition.brandNew)
                  PositionedDirectional(
                    top: 8,
                    start: 8,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: const Color(0xFFB45309), // white text >= 4.5:1
                        borderRadius: BorderRadius.circular(AppRadius.lg),
                      ),
                      child: Text(
                        context.tr('condition.${l.condition.json}'),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 11,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          Expanded(
            child: ClipRect(
              child: SingleChildScrollView(
                physics: const NeverScrollableScrollPhysics(),
                child: Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  l.displayTitle(lang),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium
                      ?.copyWith(fontWeight: FontWeight.w700, height: 1.3),
                ),
                const SizedBox(height: 6),
                MoneyText.range(
                  l.price,
                  style: TextStyle(
                    color: theme.colorScheme.primary,
                    fontWeight: FontWeight.w800,
                    fontSize: 13,
                  ),
                ),
                if (l.moq != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      context.tr('listing.moq', {
                        'n': '${l.moq}',
                        'unit': unitLabel(context, l.unit),
                      }),
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: AppColors.secondaryOf(context)),
                    ),
                  ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    CountryFlag(
                      countryCode: l.origin?.countryCode ?? l.supplier.location.countryCode,
                      size: 16,
                    ),
                    const Spacer(),
                    TrustBadge(
                      band: l.supplier.trustBand,
                      score: l.supplier.trustScore,
                      compact: true,
                    ),
                  ],
                ),
              ],
            ),
          ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Sliver grid of listing cards (2 columns).
class ListingGrid extends StatelessWidget {
  const ListingGrid({super.key, required this.items});

  final List<Listing> items;

  @override
  Widget build(BuildContext context) {
    // Large text: one wide column so titles/prices stay readable.
    final big = MediaQuery.textScalerOf(context).scale(14) / 14 > 1.35;
    return SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
      sliver: SliverGrid(
        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: big ? 1 : 2,
          mainAxisSpacing: AppSpacing.md,
          crossAxisSpacing: AppSpacing.md,
          childAspectRatio: big ? 0.8 : 0.58,
        ),
        delegate: SliverChildBuilderDelegate(
          (context, i) => ListingCard(listing: items[i]),
          childCount: items.length,
        ),
      ),
    );
  }
}
