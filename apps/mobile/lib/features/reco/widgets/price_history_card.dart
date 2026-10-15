import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:factory_finder/core/utils/number_format.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/reco/chart_math.dart';
import 'package:factory_finder/features/reco/reco_models.dart';
import 'package:factory_finder/features/reco/reco_repository.dart';
import 'package:factory_finder/features/reco/widgets/price_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

const List<int> kPriceRanges = [30, 90, 365];

/// Colour + icon of a trend. A price going up is shown as a warning, down as
/// good news; the icon and text carry the meaning too (not colour alone).
({Color color, IconData icon}) trendStyle(PriceDirection d, Brightness b) {
  final dark = b == Brightness.dark;
  switch (d) {
    case PriceDirection.up:
      return (
        color: dark ? const Color(0xFFF87171) : const Color(0xFFB91C1C),
        icon: Icons.trending_up,
      );
    case PriceDirection.down:
      return (
        color: dark ? const Color(0xFF4ADE80) : const Color(0xFF15803D),
        icon: Icons.trending_down,
      );
    case PriceDirection.flat:
      return (
        color: dark ? AppColors.textSecondaryDark : AppColors.textSecondary,
        icon: Icons.trending_flat,
      );
  }
}

/// "+4.2%" / "-3.0%" from a decimal string.
String signedPct(String raw) {
  final text = formatDecimalString(raw, fractionDigits: 1);
  final negative = text.startsWith('-');
  return negative ? '$text%' : '+$text%';
}

class PriceHistoryCard extends ConsumerStatefulWidget {
  const PriceHistoryCard({
    super.key,
    required this.listingId,
    this.onAlertSuggested,
    this.initialDays = 90,
  });

  final String listingId;

  /// Opens the alert creation flow prefilled with the suggested target.
  final void Function(Money suggested)? onAlertSuggested;
  final int initialDays;

  @override
  ConsumerState<PriceHistoryCard> createState() => _PriceHistoryCardState();
}

class _PriceHistoryCardState extends ConsumerState<PriceHistoryCard> {
  late int _days = widget.initialDays;

  PriceHistoryArgs get _args => PriceHistoryArgs(widget.listingId, _days);

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(priceHistoryProvider(_args));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: context.tr('reco.price_history')),
        AppCard(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: SizedBox(
            width: double.infinity,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: [
                    for (final d in kPriceRanges)
                      ChoiceChip(
                        key: ValueKey<String>('price-range-$d'),
                        label: Text(context.tr('reco.range_days', {'n': '$d'})),
                        selected: _days == d,
                        onSelected: (_) => setState(() => _days = d),
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                async.when(
                  loading: () => const SizedBox(
                    key: ValueKey<String>('price-history-loading'),
                    height: 160,
                    child: Center(child: CircularProgressIndicator()),
                  ),
                  error: (e, _) => _LoadError(
                    onRetry: () => ref.invalidate(priceHistoryProvider(_args)),
                  ),
                  data: (h) => _HistoryBody(
                    history: h,
                    onAlert: widget.onAlertSuggested,
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _LoadError extends StatelessWidget {
  const _LoadError({required this.onRetry});
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      key: const ValueKey<String>('price-history-error'),
      spacing: AppSpacing.sm,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        const Icon(Icons.cloud_off_rounded, size: 18),
        Text(context.tr('reco.load_failed')),
        TextButton(onPressed: onRetry, child: Text(context.tr('common.retry'))),
      ],
    );
  }
}

class _Note extends StatelessWidget {
  const _Note({super.key, required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 16, color: AppColors.secondaryOf(context)),
        const SizedBox(width: AppSpacing.sm),
        Expanded(
          child: Text(
            text,
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

class _HistoryBody extends StatelessWidget {
  const _HistoryBody({required this.history, required this.onAlert});

  final PriceHistory history;
  final void Function(Money suggested)? onAlert;

  @override
  Widget build(BuildContext context) {
    final h = history;
    final synthetic = h.synthetic
        ? Padding(
            padding: const EdgeInsets.only(top: AppSpacing.md),
            child: _Note(
              key: const ValueKey<String>('price-synthetic-note'),
              icon: Icons.info_outline,
              text: context.tr('reco.synthetic'),
            ),
          )
        : const SizedBox.shrink();

    if (!h.hasEnoughData) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Note(
            key: const ValueKey<String>('price-insufficient'),
            icon: Icons.query_stats,
            text: context.tr('reco.insufficient'),
          ),
          synthetic,
        ],
      );
    }

    final theme = Theme.of(context);
    final style = trendStyle(h.trend.direction, theme.brightness);
    final word = context.tr('reco.trend.${h.trend.direction.name}');
    final pct = h.trend.changePct == null || h.trend.changePct!.isEmpty
        ? null
        : localizeNumber(signedPct(h.trend.changePct!), DigitStyleScope.of(context));
    final first = h.points.first.t;
    final last = h.points.last.t;
    final semantic = context.tr('reco.chart_a11y', {
      'days': '${h.days}',
      'from': formatChartDate(first),
      'to': formatChartDate(last),
      'trend': pct == null ? word : '$word $pct',
    });
    final summary = h.summary;
    final scale = MediaQuery.textScalerOf(context).scale(14) / 14;
    final chartHeight = 150.0 * (scale > 1.4 ? 1.4 : (scale < 1 ? 1.0 : scale));

    Widget stat(String label, String amount) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              label,
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: AppColors.secondaryOf(context)),
            ),
            MoneyText(Money(amount: amount, currency: h.currency)),
          ],
        );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          key: ValueKey<String>('price-trend-${h.trend.direction.name}'),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: style.color.withOpacity(0.12),
            borderRadius: BorderRadius.circular(AppRadius.lg),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(style.icon, size: 18, color: style.color),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  word,
                  style: TextStyle(color: style.color, fontWeight: FontWeight.w800),
                ),
              ),
              if (pct != null) ...[
                const SizedBox(width: 6),
                Directionality(
                  textDirection: TextDirection.ltr,
                  child: Text(
                    pct,
                    style: TextStyle(color: style.color, fontWeight: FontWeight.w800),
                  ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        Semantics(
          label: semantic,
          image: true,
          child: ExcludeSemantics(
            child: SizedBox(
              key: const ValueKey<String>('price-chart'),
              height: chartHeight,
              width: double.infinity,
              child: CustomPaint(
                painter: PriceChartPainter(
                  points: h.points,
                  lineColor: theme.colorScheme.primary,
                  gridColor: theme.dividerColor.withOpacity(0.5),
                ),
              ),
            ),
          ),
        ),
        const SizedBox(height: 4),
        Directionality(
          textDirection: TextDirection.ltr,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Flexible(
                child: Text(
                  localizeNumber(formatChartDate(first), DigitStyleScope.of(context)),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: AppColors.secondaryOf(context)),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Flexible(
                child: Text(
                  localizeNumber(formatChartDate(last), DigitStyleScope.of(context)),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: AppColors.secondaryOf(context)),
                ),
              ),
            ],
          ),
        ),
        if (summary != null) ...[
          const SizedBox(height: AppSpacing.md),
          Wrap(
            key: const ValueKey<String>('price-stats'),
            spacing: AppSpacing.xl,
            runSpacing: AppSpacing.md,
            children: [
              stat(context.tr('reco.min'), summary.min),
              stat(context.tr('reco.max'), summary.max),
              stat(context.tr('reco.avg'), summary.avg),
            ],
          ),
        ],
        if (h.hints?.atPeriodLow == true || h.hints?.atPeriodHigh == true)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.md),
            child: _Note(
              icon: h.hints!.atPeriodLow ? Icons.south : Icons.north,
              text: context.tr(h.hints!.atPeriodLow ? 'reco.at_low' : 'reco.at_high'),
            ),
          ),
        synthetic,
        if (h.hints != null && onAlert != null) ...[
          const SizedBox(height: AppSpacing.md),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              key: const ValueKey<String>('price-alert-suggested'),
              style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
              onPressed: () => onAlert!(h.hints!.suggestedTarget),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.notifications_active_outlined, size: 18),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      context.tr('reco.alert_suggested'),
                      textAlign: TextAlign.center,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            context.tr('reco.suggested', {'price': h.hints!.suggestedTarget.format()}),
            style: theme.textTheme.bodySmall
                ?.copyWith(color: AppColors.secondaryOf(context)),
          ),
        ],
      ],
    );
  }
}
