import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/widgets/listing_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

void showTrustFactorsSheet(BuildContext context, TrustScore trust) {
  final lang = Localizations.localeOf(context).languageCode;
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (ctx) => SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    ctx.tr('listing.trust_factors'),
                    style: Theme.of(ctx)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.w800),
                  ),
                ),
                TrustBadge(band: trust.band, score: trust.score),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            for (final f in trust.factors)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: 52,
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: (f.impact >= 0 ? AppColors.success : AppColors.danger)
                            .withOpacity(0.12),
                        borderRadius: BorderRadius.circular(AppRadius.sm),
                      ),
                      child: Directionality(
                        textDirection: TextDirection.ltr,
                        child: Text(
                          f.impact >= 0 ? '+${f.impact}' : '${f.impact}',
                          style: TextStyle(
                            fontWeight: FontWeight.w800,
                            color: f.impact >= 0 ? AppColors.success : AppColors.danger,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Text(
                        (lang == 'ar' && f.explanationAr != null)
                            ? f.explanationAr!
                            : f.explanation,
                        style: const TextStyle(height: 1.4),
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

class ListingDetailScreen extends ConsumerWidget {
  const ListingDetailScreen({super.key, required this.listingId});

  final String listingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(listingProvider(listingId));
    return async.when(
      loading: () => Scaffold(
        appBar: AppBar(),
        body: const SingleChildScrollView(child: LoadingList(itemCount: 5)),
      ),
      error: (_, __) => Scaffold(
        appBar: AppBar(),
        body: ErrorState(
          message: context.tr('listing.not_found'),
          onRetry: () => ref.invalidate(listingProvider(listingId)),
        ),
      ),
      data: (listing) => _ListingBody(listing: listing),
    );
  }
}

class _ListingBody extends ConsumerStatefulWidget {
  const _ListingBody({required this.listing});

  final Listing listing;

  @override
  ConsumerState<_ListingBody> createState() => _ListingBodyState();
}

class _ListingBodyState extends ConsumerState<_ListingBody> {
  int _page = 0;

  void _snack(String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  @override
  Widget build(BuildContext context) {
    final l = widget.listing;
    final lang = Localizations.localeOf(context).languageCode;
    final theme = Theme.of(context);
    final trustAsync = ref.watch(trustProvider(l.supplier.id));
    final images = l.images;
    final unit = unitLabel(context, l.unit);
    final leadText = l.leadTimeDays == null
        ? ''
        : context.tr('common.days', {
            'min': '${l.leadTimeDays!.min}',
            'max': '${l.leadTimeDays!.max}',
          });

    final specs = <MapEntry<String, String>>[
      MapEntry(context.tr('listing.spec.unit'), unit),
      if (l.moq != null) MapEntry(context.tr('listing.spec.moq'), '${l.moq} $unit'),
      MapEntry(
        context.tr('listing.spec.condition'),
        context.tr('condition.${l.condition.json}'),
      ),
      if (l.category != null)
        MapEntry(context.tr('listing.spec.category'), context.tr('cat.${l.category}')),
      if (l.unitWeightKg != null)
        MapEntry(context.tr('listing.spec.weight'), '${l.unitWeightKg}'),
      if (l.unitVolumeM3 != null)
        MapEntry(context.tr('listing.spec.volume'), '${l.unitVolumeM3}'),
      if (l.hsCode != null) MapEntry(context.tr('listing.spec.hs'), l.hsCode!),
      if (l.origin != null)
        MapEntry(
          context.tr('listing.spec.origin'),
          context.tr('country.${l.origin!.countryCode}'),
        ),
    ];

    return Scaffold(
      appBar: AppBar(),
      body: ListView(
        padding: const EdgeInsets.only(bottom: AppSpacing.xl),
        children: [
          SizedBox(
            height: 280,
            child: Stack(
              children: [
                PageView.builder(
                  itemCount: images.isEmpty ? 1 : images.length,
                  onPageChanged: (i) => setState(() => _page = i),
                  itemBuilder: (_, i) => AppNetworkImage(
                    url: images.isEmpty ? null : images[i],
                    width: double.infinity,
                    height: 280,
                  ),
                ),
                if (images.length > 1)
                  Positioned(
                    bottom: 10,
                    left: 0,
                    right: 0,
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        for (var i = 0; i < images.length; i++)
                          AnimatedContainer(
                            duration: const Duration(milliseconds: 200),
                            margin: const EdgeInsets.symmetric(horizontal: 3),
                            width: i == _page ? 18 : 7,
                            height: 7,
                            decoration: BoxDecoration(
                              color: i == _page ? Colors.white : Colors.white70,
                              borderRadius: BorderRadius.circular(4),
                            ),
                          ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    if (l.condition != ItemCondition.brandNew)
                      Container(
                        margin: const EdgeInsetsDirectional.only(end: 8),
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: AppColors.warning,
                          borderRadius: BorderRadius.circular(AppRadius.lg),
                        ),
                        child: Text(
                          context.tr('condition.${l.condition.json}'),
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 12,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                    Text(
                      context.tr('discover.kind.${l.kind.json}'),
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: AppColors.textSecondary),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),
                Text(
                  l.displayTitle(lang),
                  style: theme.textTheme.titleLarge
                      ?.copyWith(fontWeight: FontWeight.w900, height: 1.3),
                ),
                const SizedBox(height: AppSpacing.md),
                MoneyText.range(
                  l.price,
                  style: TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.w900,
                    color: theme.colorScheme.primary,
                  ),
                ),
                Text(
                  context.tr('listing.per_unit', {'unit': unit}),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
                const SizedBox(height: AppSpacing.lg),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: [
                    if (l.moq != null)
                      _InfoPill(
                        icon: Icons.inventory_2_outlined,
                        text: context.tr('listing.moq', {'n': '${l.moq}', 'unit': unit}),
                      ),
                    if (l.leadTimeDays != null)
                      _InfoPill(
                        icon: Icons.schedule,
                        text: '${context.tr('listing.lead_time')}: $leadText',
                      ),
                    if (l.incoterm != null)
                      _InfoPill(
                        icon: Icons.assignment_outlined,
                        text: '${context.tr('listing.incoterm')}: ${l.incoterm!.json}',
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.lg),
                SectionHeader(title: context.tr('listing.supplier')),
                AppCard(
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  onTap: () => context.push('/supplier/${l.supplier.id}'),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          CountryFlag(
                            countryCode: l.supplier.location.countryCode,
                            size: 22,
                          ),
                          const SizedBox(width: AppSpacing.sm),
                          Expanded(
                            child: Text(
                              l.supplier.name,
                              style: const TextStyle(fontWeight: FontWeight.w800),
                            ),
                          ),
                          const Icon(Icons.chevron_right),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      Wrap(
                        spacing: AppSpacing.sm,
                        runSpacing: AppSpacing.xs,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          TrustBadge(
                            band: l.supplier.trustBand,
                            score: l.supplier.trustScore,
                          ),
                          if (l.supplier.verified)
                            _InfoPill(
                              icon: Icons.check_circle,
                              text: context.tr('listing.verified'),
                            ),
                          if (l.supplier.yearsInBusiness != null)
                            Text(
                              context.tr(
                                'listing.years',
                                {'n': '${l.supplier.yearsInBusiness}'},
                              ),
                              style: theme.textTheme.bodySmall
                                  ?.copyWith(color: AppColors.textSecondary),
                            ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      trustAsync.when(
                        loading: () => const SizedBox(
                          height: 20,
                          child: LinearProgressIndicator(),
                        ),
                        error: (_, __) => const SizedBox.shrink(),
                        data: (trust) => TextButton.icon(
                          onPressed: () => showTrustFactorsSheet(context, trust),
                          icon: const Icon(Icons.fact_check_outlined, size: 18),
                          label: Text(context.tr('listing.trust_hint')),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                SectionHeader(title: context.tr('listing.specs')),
                AppCard(
                  padding: EdgeInsets.zero,
                  child: Column(
                    children: [
                      for (var i = 0; i < specs.length; i++) ...[
                        if (i > 0) const Divider(height: 1),
                        Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: AppSpacing.lg,
                            vertical: AppSpacing.md,
                          ),
                          child: Row(
                            children: [
                              Expanded(
                                child: Text(
                                  specs[i].key,
                                  style: const TextStyle(color: AppColors.textSecondary),
                                ),
                              ),
                              Text(
                                specs[i].value,
                                style: const TextStyle(fontWeight: FontWeight.w700),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: SafeArea(
        child: Container(
          padding: const EdgeInsets.all(AppSpacing.md),
          decoration: BoxDecoration(
            color: theme.colorScheme.surface,
            border: const Border(top: BorderSide(color: AppColors.border)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              SizedBox(
                width: double.infinity,
                child: PrimaryButton(
                  label: context.tr('listing.calc_cost'),
                  icon: Icons.calculate_outlined,
                  onPressed: () =>
                      context.push('/logistics/calculator?listing_id=${l.id}'),
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => _snack(context.tr('common.coming_soon')),
                      icon: const Icon(Icons.chat_bubble_outline, size: 18),
                      label: Text(context.tr('listing.message_supplier')),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => _snack(context.tr('listing.watch_added')),
                      icon: const Icon(Icons.notifications_none, size: 18),
                      label: Text(context.tr('listing.watch_price')),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _InfoPill extends StatelessWidget {
  const _InfoPill({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: AppColors.primary.withOpacity(0.08),
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 6),
          Flexible(child: Text(text, style: const TextStyle(fontSize: 12.5))),
        ],
      ),
    );
  }
}
