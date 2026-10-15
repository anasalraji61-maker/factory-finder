import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/widgets/listing_card.dart';
import 'package:factory_finder/features/reco/reco_models.dart';
import 'package:factory_finder/features/reco/reco_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Horizontal row of listing cards, each with up to two reason chips
/// (Arabic or English by locale).
class RecoCarousel extends StatelessWidget {
  const RecoCarousel({super.key, required this.items});

  final List<RecoItem> items;

  @override
  Widget build(BuildContext context) {
    final raw = MediaQuery.textScalerOf(context).scale(14) / 14;
    final scale = raw < 1 ? 1.0 : (raw > 1.6 ? 1.6 : raw);
    final cardHeight = 290 * scale;
    final chipsHeight = 74 * scale;
    return SizedBox(
      height: cardHeight + 6 + chipsHeight,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        itemCount: items.length,
        separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.md),
        itemBuilder: (_, i) {
          final item = items[i];
          return SizedBox(
            key: ValueKey<String>('reco-item-${item.listing.id}'),
            width: 180,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(height: cardHeight, child: ListingCard(listing: item.listing)),
                const SizedBox(height: 6),
                Expanded(
                  child: ClipRect(
                    child: SingleChildScrollView(
                      physics: const NeverScrollableScrollPhysics(),
                      child: _ReasonChips(item: item),
                    ),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _ReasonChips extends StatelessWidget {
  const _ReasonChips({required this.item});

  final RecoItem item;

  @override
  Widget build(BuildContext context) {
    final lang = Localizations.localeOf(context).languageCode;
    final primary = Theme.of(context).colorScheme.primary;
    return Wrap(
      spacing: 6,
      runSpacing: 4,
      children: [
        for (final r in item.reasons.take(2))
          Container(
            key: ValueKey<String>('reco-reason-${item.listing.id}-${r.code}'),
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: primary.withOpacity(0.10),
              borderRadius: BorderRadius.circular(AppRadius.lg),
            ),
            child: Text(
              r.text(lang),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600),
            ),
          ),
      ],
    );
  }
}

/// Small non-blocking notice shown when the backend returned partial results.
class PartialResultsNotice extends StatelessWidget {
  const PartialResultsNotice({super.key});

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.onSurfaceVariant;
    return Padding(
      key: const ValueKey<String>('reco-partial-notice'),
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.lg,
        vertical: AppSpacing.xs,
      ),
      child: Row(
        children: [
          Icon(Icons.info_outline, size: 16, color: color),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              context.tr('reco.partial'),
              style: TextStyle(fontSize: 12, color: color),
            ),
          ),
        ],
      ),
    );
  }
}

/// "Similar listings" block of the listing detail page. Hidden while loading,
/// on errors and when nothing similar exists (it is a bonus, not essential).
class SimilarListingsSection extends ConsumerWidget {
  const SimilarListingsSection({super.key, required this.listingId});

  final String listingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(similarListingsProvider(listingId));
    return async.maybeWhen(
      data: (page) => page.items.isEmpty
          ? (page.isPartial ? const PartialResultsNotice() : const SizedBox.shrink())
          : Column(
              key: const ValueKey<String>('similar-section'),
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                  child: SectionHeader(title: context.tr('reco.similar')),
                ),
                if (page.isPartial) const PartialResultsNotice(),
                RecoCarousel(items: page.items),
              ],
            ),
      orElse: () => const SizedBox.shrink(),
    );
  }
}

/// "Recommended for you" block of the Discover tab.
class RecommendedSection extends ConsumerWidget {
  const RecommendedSection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(recommendationsProvider);
    return async.maybeWhen(
      data: (page) => page.items.isEmpty
          ? (page.isPartial ? const PartialResultsNotice() : const SizedBox.shrink())
          : Column(
              key: const ValueKey<String>('recommended-section'),
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                  child: SectionHeader(title: context.tr('reco.title')),
                ),
                if (page.isPartial) const PartialResultsNotice(),
                RecoCarousel(items: page.items),
              ],
            ),
      orElse: () => const SizedBox.shrink(),
    );
  }
}
