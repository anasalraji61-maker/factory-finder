import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart';
import 'package:flutter/material.dart';

/// Localized "why this score" lines built from the numeric breakdown
/// (the server text is English only).
List<String> comparisonExplanation(BuildContext context, ComparisonItem item) {
  String pct(double v) => '${(v * 100).round()}%';
  return [
    context.tr('freight.explain.price', {
      'v': pct(item.price.value),
      'w': pct(item.price.weight),
    }),
    context.tr('freight.explain.transit', {
      'v': pct(item.transit.value),
      'w': pct(item.transit.weight),
    }),
    context.tr('freight.explain.rating', {
      'v': item.adjustedRating.toStringAsFixed(2),
      'w': pct(item.rating.weight),
    }),
  ];
}

/// Sort chips + one comparison card per ranked quote + excluded notice.
class QuoteComparisonView extends StatelessWidget {
  const QuoteComparisonView({
    super.key,
    required this.comparison,
    required this.sort,
    required this.onSort,
    required this.canAccept,
    required this.onAccept,
    required this.onReportQuote,
    required this.onReportForwarder,
    this.awardedQuoteId,
    this.onUseInLandedCost,
  });

  final Comparison comparison;
  final String sort;
  final ValueChanged<String> onSort;

  /// True only while the request is open.
  final bool canAccept;
  final String? awardedQuoteId;
  final ValueChanged<Quote> onAccept;
  final ValueChanged<Quote> onReportQuote;
  final ValueChanged<Quote> onReportForwarder;

  /// Shown on the awarded quote only; null hides the button.
  final ValueChanged<Quote>? onUseInLandedCost;

  @override
  Widget build(BuildContext context) {
    final items = sortComparisonItems(comparison.items, sort);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final s in kQuoteSorts)
              ChoiceChip(
                key: ValueKey<String>('freight_sort_$s'),
                label: Text(context.tr('freight.sort.$s')),
                selected: sort == s,
                onSelected: (_) => onSort(s),
              ),
          ],
        ),
        const SizedBox(height: AppSpacing.md),
        if (items.isEmpty)
          Padding(
            key: const ValueKey<String>('freight_no_quotes'),
            padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
            child: Text(
              context.tr('freight.no_quotes'),
              style: TextStyle(color: AppColors.secondaryOf(context)),
            ),
          )
        else
          for (final item in items)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.md),
              child: QuoteCompareCard(
                item: item,
                currency: comparison.currency,
                canAccept: canAccept,
                awarded: item.quote.id == awardedQuoteId,
                onAccept: () => onAccept(item.quote),
                onReportQuote: () => onReportQuote(item.quote),
                onReportForwarder: () => onReportForwarder(item.quote),
                onUseInLandedCost: onUseInLandedCost == null
                    ? null
                    : () => onUseInLandedCost!(item.quote),
              ),
            ),
        if (comparison.excluded.isNotEmpty)
          Padding(
            key: const ValueKey<String>('freight_excluded'),
            padding: const EdgeInsets.only(top: AppSpacing.xs),
            child: Text(
              context.tr('freight.excluded', {
                'n': '${comparison.excluded.length}',
                'reasons': {
                  for (final e in comparison.excluded)
                    context.tr('freight.excluded_reason.${e.reason}'),
                }.join(' · '),
              }),
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: AppColors.secondaryOf(context)),
            ),
          ),
      ],
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          label,
          style: Theme.of(context)
              .textTheme
              .bodySmall
              ?.copyWith(color: AppColors.secondaryOf(context)),
        ),
        child,
      ],
    );
  }
}

class QuoteCompareCard extends StatelessWidget {
  const QuoteCompareCard({
    super.key,
    required this.item,
    required this.currency,
    required this.canAccept,
    required this.awarded,
    required this.onAccept,
    required this.onReportQuote,
    required this.onReportForwarder,
    this.onUseInLandedCost,
  });

  final ComparisonItem item;
  final VoidCallback? onUseInLandedCost;
  final String currency;
  final bool canAccept;
  final bool awarded;
  final VoidCallback onAccept;
  final VoidCallback onReportQuote;
  final VoidCallback onReportForwarder;

  @override
  Widget build(BuildContext context) {
    final q = item.quote;
    final f = q.forwarder;
    final theme = Theme.of(context);
    final digits = DigitStyleScope.of(context);
    final scoreText = localizeDigits(item.score.toStringAsFixed(1), digits);
    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CircleAvatar(
                radius: 16,
                backgroundColor: AppColors.primary.withOpacity(0.12),
                child: Text(
                  localizeDigits('${item.rank}', digits),
                  style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      f?.companyName ?? q.forwarderId,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                    ),
                    Text(
                      f != null && f.rating.count > 0
                          ? context.tr('freight.rating_line', {
                              'avg': f.rating.average ?? '-',
                              'n': '${f.rating.count}',
                              'jobs': '${f.completedJobs}',
                            })
                          : context.tr('freight.unrated'),
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: AppColors.secondaryOf(context)),
                    ),
                  ],
                ),
              ),
              PopupMenuButton<String>(
                key: ValueKey<String>('freight_quote_menu_${q.id}'),
                tooltip: context.tr('freight.report.menu'),
                onSelected: (v) {
                  if (v == 'quote') onReportQuote();
                  if (v == 'forwarder') onReportForwarder();
                },
                itemBuilder: (_) => [
                  PopupMenuItem<String>(
                    value: 'quote',
                    child: Text(context.tr('freight.report.quote')),
                  ),
                  PopupMenuItem<String>(
                    value: 'forwarder',
                    child: Text(context.tr('freight.report.forwarder')),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              FreightChip(
                context.tr('freight.score_chip', {'v': scoreText}),
                icon: Icons.insights_outlined,
              ),
              for (final b in item.badges)
                FreightChip(context.tr('freight.badge.$b'), color: AppColors.accent),
              if (awarded)
                FreightChip(
                  context.tr('freight.qstatus.accepted'),
                  color: AppColors.success,
                  icon: Icons.verified_outlined,
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: 20,
            runSpacing: 10,
            children: [
              _Metric(
                label: context.tr('freight.price'),
                child: FreightMoney(q.amount, q.currency),
              ),
              _Metric(
                label: context.tr('freight.transit'),
                child: Text(
                  context.tr('freight.days', {'n': '${q.transitDays}'}),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              _Metric(
                label: context.tr('freight.rating'),
                child: Text(
                  '${localizeDigits(item.adjustedRating.toStringAsFixed(2), digits)}/5',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
            ],
          ),
          Theme(
            data: theme.copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              key: ValueKey<String>('freight_why_${q.id}'),
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              title: Text(
                context.tr('freight.why'),
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              children: [
                for (final line in comparisonExplanation(context, item))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text('• $line', style: theme.textTheme.bodySmall),
                  ),
                if (q.breakdown.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    context.tr('freight.breakdown'),
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  for (final l in q.breakdown)
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Wrap(
                        spacing: 8,
                        children: [
                          Text(l.label),
                          FreightMoney(l.amount, q.currency,
                              style: const TextStyle(fontWeight: FontWeight.w600)),
                        ],
                      ),
                    ),
                ],
                if (q.inclusions.isNotEmpty)
                  FreightInfoLine(context.tr('freight.inclusions'), q.inclusions.join(' · ')),
                if (q.exclusions.isNotEmpty)
                  FreightInfoLine(context.tr('freight.exclusions'), q.exclusions.join(' · ')),
                if (q.terms != null && q.terms!.isNotEmpty)
                  FreightInfoLine(context.tr('freight.terms'), q.terms!),
                if (q.validUntil != null)
                  FreightInfoLine(
                    context.tr('freight.valid_until'),
                    formatDate(context, q.validUntil),
                  ),
                const SizedBox(height: AppSpacing.sm),
              ],
            ),
          ),
          if (awarded && onUseInLandedCost != null)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.sm),
              child: SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  key: ValueKey<String>('freight_use_landed_${q.id}'),
                  style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
                  onPressed: onUseInLandedCost,
                  icon: const Icon(Icons.calculate_outlined),
                  label: Text(context.tr('freight.use_in_landed')),
                ),
              ),
            ),
          if (canAccept && q.isSubmitted)
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                key: ValueKey<String>('freight_accept_${q.id}'),
                style: FilledButton.styleFrom(minimumSize: const Size(64, 48)),
                onPressed: onAccept,
                icon: const Icon(Icons.handshake_outlined),
                label: Text(context.tr('freight.accept')),
              ),
            ),
        ],
      ),
    );
  }
}
