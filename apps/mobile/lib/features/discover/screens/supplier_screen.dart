import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/screens/listing_detail_screen.dart';
import 'package:factory_finder/features/discover/widgets/listing_card.dart';
import 'package:factory_finder/features/reviews/widgets/review_widgets.dart';
import 'package:factory_finder/features/trust/trust_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class SupplierScreen extends ConsumerWidget {
  const SupplierScreen({super.key, required this.supplierId});

  final String supplierId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final supplier = ref.watch(supplierProvider(supplierId));
    final listings = ref.watch(listingsProvider(ListingQuery(supplierId: supplierId)));
    final trust = ref.watch(trustProvider(supplierId));
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(),
      body: supplier.when(
        loading: () => const SingleChildScrollView(child: LoadingList(itemCount: 4)),
        error: (e, _) => ErrorState(
          message: '$e',
          onRetry: () => ref.invalidate(supplierProvider(supplierId)),
        ),
        data: (s) => CustomScrollView(
          slivers: [
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.all(AppSpacing.lg),
                child: AppCard(
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          CountryFlag(countryCode: s.location.countryCode, size: 28),
                          const SizedBox(width: AppSpacing.md),
                          Expanded(
                            child: Text(
                              s.name,
                              style: theme.textTheme.titleMedium
                                  ?.copyWith(fontWeight: FontWeight.w900),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      Text(
                        locationLabel(context, s.location),
                        style: const TextStyle(color: AppColors.textSecondary),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      Wrap(
                        spacing: AppSpacing.sm,
                        runSpacing: AppSpacing.xs,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          TrustBadge(band: s.trustBand, score: s.trustScore),
                          if (s.verified)
                            Chip(
                              avatar: const Icon(Icons.check_circle, size: 16),
                              label: Text(context.tr('listing.verified')),
                            ),
                          if (s.yearsInBusiness != null)
                            Text(
                              context.tr('listing.years', {'n': '${s.yearsInBusiness}'}),
                              style: const TextStyle(color: AppColors.textSecondary),
                            ),
                        ],
                      ),
                      trust.maybeWhen(
                        data: (t) => TextButton.icon(
                          onPressed: () => showTrustFactorsSheet(context, t),
                          icon: const Icon(Icons.fact_check_outlined, size: 18),
                          label: Text(context.tr('listing.trust_factors')),
                        ),
                        orElse: () => const SizedBox.shrink(),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            SliverToBoxAdapter(
              child: trust.maybeWhen(
                data: (t) => Padding(
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg,
                    0,
                    AppSpacing.lg,
                    AppSpacing.lg,
                  ),
                  child: TrustInsights(supplierId: supplierId, trust: t),
                ),
                orElse: () => const SizedBox.shrink(),
              ),
            ),
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  0,
                  AppSpacing.lg,
                  AppSpacing.lg,
                ),
                child: RatingSummaryCard(supplierRef: supplierId),
              ),
            ),
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: SectionHeader(title: context.tr('listing.supplier_listings')),
              ),
            ),
            ...listings.when(
              loading: () => <Widget>[
                const SliverToBoxAdapter(child: LoadingList(itemCount: 3)),
              ],
              error: (e, _) => <Widget>[
                SliverToBoxAdapter(child: ErrorState(message: '$e')),
              ],
              data: (page) => page.items.isEmpty
                  ? <Widget>[
                      SliverToBoxAdapter(
                        child: EmptyState(
                          icon: Icons.inventory_2_outlined,
                          title: context.tr('discover.empty_title'),
                        ),
                      ),
                    ]
                  : <Widget>[ListingGrid(items: page.items)],
            ),
            const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.xxl)),
          ],
        ),
      ),
    );
  }
}
