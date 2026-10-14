import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

String unitLabel(BuildContext context, String unit) {
  final key = 'unit.$unit';
  final label = context.tr(key);
  return label == key ? unit : label;
}

class ListingCard extends StatelessWidget {
  const ListingCard({super.key, required this.listing});

  final Listing listing;

  @override
  Widget build(BuildContext context) {
    final lang = Localizations.localeOf(context).languageCode;
    final theme = Theme.of(context);
    final l = listing;
    return AppCard(
      padding: EdgeInsets.zero,
      onTap: () => context.push('/listing/${l.id}'),
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
                if (l.condition != ItemCondition.brandNew)
                  PositionedDirectional(
                    top: 8,
                    start: 8,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: AppColors.warning,
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
                          ?.copyWith(color: AppColors.textSecondary),
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
    return SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
      sliver: SliverGrid(
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 2,
          mainAxisSpacing: AppSpacing.md,
          crossAxisSpacing: AppSpacing.md,
          childAspectRatio: 0.58,
        ),
        delegate: SliverChildBuilderDelegate(
          (context, i) => ListingCard(listing: items[i]),
          childCount: items.length,
        ),
      ),
    );
  }
}
