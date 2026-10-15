import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/compare_logic.dart';
import 'package:factory_finder/features/discover/widgets/listing_card.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

const Location _kDefaultDestination = Location(countryCode: 'IQ', city: 'Baghdad');

/// Landed-cost estimate of one listing (at its MOQ) to the user's destination.
/// Null result = no data for this listing.
final compareLandedProvider =
    FutureProvider.autoDispose.family<CompareLanded?, String>((ref, id) async {
  final repo = ref.watch(logisticsRepositoryProvider);
  final dest = ref.watch(destinationProvider) ?? _kDefaultDestination;
  final currency = ref.watch(displayCurrencyProvider);
  final lang = ref.watch(localeProvider).languageCode;
  final p = await repo.prefill(id);
  if (p == null) return null;
  final qty = p.quantity <= 0 ? 1 : p.quantity;
  final request = QuoteRequest(
    goodsValue: p.unitPrice * qty,
    goodsCurrency: p.currency,
    weightKg: p.unitWeightKg * qty,
    volumeM3: p.unitVolumeM3 * qty,
    hsCode: p.hsCode,
    origin: p.origin,
    destination: dest,
    incoterm: p.incoterm,
    displayCurrency: currency,
  );
  final quote = await repo.calculate(request, lang: lang);
  final option = pickLandedOption(quote);
  if (option == null) return null;
  return CompareLanded(
    total: option.total,
    quantity: qty,
    transitDays: option.transitDays,
  );
});

class CompareScreen extends ConsumerWidget {
  const CompareScreen({super.key});

  static const double _labelWidth = 104;
  static const double _colWidth = 150;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(compareProvider);
    final lang = Localizations.localeOf(context).languageCode;
    final dest = ref.watch(destinationProvider) ?? _kDefaultDestination;
    final destCity = dest.city ?? context.tr('country.${dest.countryCode}');

    if (items.isEmpty) {
      return Scaffold(
        appBar: AppBar(title: Text(context.tr('compare.title'))),
        body: EmptyState(
          icon: Icons.compare_arrows,
          title: context.tr('compare.empty_title'),
          message: context.tr('compare.empty_msg'),
        ),
      );
    }

    final prices = comparablePrices(items);
    final bestPrice = bestLowIndex(prices);
    final bestTrust = bestHighIndex([
      for (final l in items) l.supplier.trustScore?.toDouble(),
    ]);
    final landedAsync = [
      for (final l in items) ref.watch(compareLandedProvider(l.id)),
    ];
    final bestLanded = bestLowIndex([
      for (final a in landedAsync) a.valueOrNull?.perUnitMid,
    ]);

    final rows = <Widget>[
      _row(context, '', [
        for (var i = 0; i < items.length; i++) _header(context, ref, items[i], lang),
      ]),
      _row(context, context.tr('compare.row.price'), [
        for (var i = 0; i < items.length; i++)
          _cell(
            context,
            MoneyText.range(items[i].price),
            badge: i == bestPrice ? context.tr('compare.best_price') : null,
          ),
      ]),
      _row(context, context.tr('compare.row.moq'), [
        for (final l in items)
          _cell(
            context,
            Text(l.moq == null
                ? context.tr('compare.na')
                : '${l.moq} ${unitLabel(context, l.unit)}'),
          ),
      ]),
      _row(context, context.tr('compare.row.condition'), [
        for (final l in items)
          _cell(context, Text(context.tr('condition.${l.condition.json}'))),
      ]),
      _row(context, context.tr('compare.row.trust'), [
        for (var i = 0; i < items.length; i++)
          _cell(
            context,
            TrustBadge(
              band: items[i].supplier.trustBand,
              score: items[i].supplier.trustScore,
            ),
            badge: i == bestTrust ? context.tr('compare.most_trusted') : null,
          ),
      ]),
      _row(context, context.tr('compare.row.lead'), [
        for (final l in items)
          _cell(
            context,
            Text(l.leadTimeDays == null
                ? context.tr('compare.na')
                : context.tr('common.days', {
                    'min': '${l.leadTimeDays!.min}',
                    'max': '${l.leadTimeDays!.max}',
                  })),
          ),
      ]),
      _row(context, context.tr('compare.row.origin'), [
        for (final l in items)
          _cell(
            context,
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                CountryFlag(
                  countryCode: l.origin?.countryCode ?? l.supplier.location.countryCode,
                  size: 16,
                ),
                const SizedBox(width: 6),
                Flexible(
                  child: Text(
                    context.tr(
                        'country.${l.origin?.countryCode ?? l.supplier.location.countryCode}'),
                  ),
                ),
              ],
            ),
          ),
      ]),
      _row(
        context,
        context.tr('compare.row.landed'),
        [
          for (var i = 0; i < items.length; i++)
            _landedCell(context, ref, items[i], landedAsync[i], destCity,
                best: i == bestLanded),
        ],
        sublabel: context.tr('compare.landed_dest', {'city': destCity}),
      ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: Text(context.tr('compare.title')),
        actions: [
          IconButton(
            tooltip: context.tr('compare.clear'),
            icon: const Icon(Icons.delete_outline),
            onPressed: () {
              ref.read(compareProvider.notifier).clear();
              if (context.canPop()) context.pop();
            },
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: rows),
        ),
      ),
    );
  }

  Widget _row(BuildContext context, String label, List<Widget> cells,
      {String? sublabel}) {
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            width: _labelWidth,
            padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.sm, vertical: AppSpacing.md),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: AppColors.border)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label,
                    style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 12,
                        color: AppColors.textSecondary)),
                if (sublabel != null)
                  Text(sublabel,
                      style: const TextStyle(
                          fontSize: 11, color: AppColors.textSecondary)),
              ],
            ),
          ),
          ...cells,
        ],
      ),
    );
  }

  Widget _cell(BuildContext context, Widget child, {String? badge, bool best = false}) {
    return Container(
      width: _colWidth,
      alignment: AlignmentDirectional.centerStart,
      padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.sm, vertical: AppSpacing.md),
      decoration: BoxDecoration(
        color: (badge != null || best) ? AppColors.success.withOpacity(0.08) : null,
        border: const Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          child,
          if (badge != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                badge,
                style: const TextStyle(
                  color: AppColors.success,
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _header(BuildContext context, WidgetRef ref, Listing l, String lang) {
    return Container(
      width: _colWidth,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: AppSpacing.md),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: InkWell(
              onTap: () => context.push('/listing/${l.id}'),
              child: Text(
                l.displayTitle(lang),
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
            ),
          ),
          IconButton(
            onPressed: () => ref.read(compareProvider.notifier).remove(l.id),
            tooltip: context.tr('compare.remove'),
            icon: const Icon(Icons.close, size: 18),
          ),
        ],
      ),
    );
  }

  Widget _landedCell(
    BuildContext context,
    WidgetRef ref,
    Listing l,
    AsyncValue<CompareLanded?> async,
    String destCity, {
    required bool best,
  }) {
    final Widget body = async.when(
      loading: () => const SizedBox(
        width: 20,
        height: 20,
        child: CircularProgressIndicator(strokeWidth: 2),
      ),
      error: (e, _) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Flexible(
            child: Text(
              context.tr('compare.landed_unavailable'),
              style: const TextStyle(color: AppColors.danger),
            ),
          ),
          IconButton(
            onPressed: () => ref.invalidate(compareLandedProvider(l.id)),
            tooltip: context.tr('common.retry'),
            icon: const Icon(Icons.refresh, size: 18),
          ),
        ],
      ),
      data: (v) {
        if (v == null) return Text(context.tr('compare.landed_unavailable'));
        final unit = Money(
          amount: v.perUnitMid.toStringAsFixed(2),
          currency: v.total.min.currency,
        );
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            MoneyText.range(v.total),
            const SizedBox(height: 2),
            Text(
              context.tr('compare.landed_unit', {'price': unit.formatIsolated()}),
              style: const TextStyle(fontSize: 11, color: AppColors.textSecondary),
            ),
            Text(
              context.tr('common.estimate'),
              style: const TextStyle(fontSize: 11, color: AppColors.textSecondary),
            ),
          ],
        );
      },
    );
    return _cell(
      context,
      body,
      badge: best ? context.tr('compare.best_landed') : null,
    );
  }
}
