import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

const Map<String, Color> _stageColors = {
  'goods': Color(0xFF94A3B8),
  'origin_inland': Color(0xFF60A5FA),
  'origin_handling': Color(0xFF818CF8),
  'main_leg': Color(0xFF2340D9),
  'insurance': Color(0xFF22D3EE),
  'destination_handling': Color(0xFFA78BFA),
  'duties': Color(0xFFF59E0B),
  'taxes': Color(0xFFF97316),
  'clearance': Color(0xFFEC4899),
  'destination_inland': Color(0xFF10B981),
  'platform_fee': Color(0xFF0EA5E9),
  'other': Color(0xFF64748B),
};

Color stageColor(String stage) => _stageColors[stage] ?? const Color(0xFF64748B);

IconData modeIcon(TransportMode m) {
  switch (m) {
    case TransportMode.seaLcl:
    case TransportMode.seaFcl20:
    case TransportMode.seaFcl40:
    case TransportMode.seaFcl40hc:
      return Icons.directions_boat_filled_outlined;
    case TransportMode.air:
      return Icons.flight_outlined;
    case TransportMode.rail:
      return Icons.train_outlined;
    case TransportMode.road:
      return Icons.local_shipping_outlined;
  }
}

class ResultsScreen extends ConsumerWidget {
  const ResultsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final quote = ref.watch(lastQuoteProvider);
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('logistics.results.title'))),
      body: quote == null
          ? EmptyState(
              icon: Icons.receipt_long_outlined,
              title: context.tr('logistics.results.none'),
              message: context.tr('logistics.results.none_msg'),
            )
          : _QuoteView(quote: quote),
    );
  }
}

class _QuoteView extends StatelessWidget {
  const _QuoteView({required this.quote});

  final LandedCostQuote quote;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: [
        AppCard(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Row(
            children: [
              CountryFlag(countryCode: quote.origin?.countryCode ?? 'CN', size: 24),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  '${locationLabel(context, quote.origin)}  ›  ${locationLabel(context, quote.destination)}',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              CountryFlag(countryCode: quote.destination?.countryCode ?? 'IQ', size: 24),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        if (quote.options.isEmpty)
          EmptyState(
            icon: Icons.inventory_2_outlined,
            title: context.tr('logistics.results.no_options'),
          )
        else
          for (final o in quote.options)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.md),
              child: OptionCard(option: o),
            ),
        const SizedBox(height: AppSpacing.sm),
        if (quote.assumptions.isNotEmpty) ...[
          Text(
            context.tr('logistics.results.assumptions'),
            style: theme.textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.xs),
          for (final a in quote.assumptions)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                '• $a',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: AppColors.textSecondary,
                  height: 1.4,
                ),
              ),
            ),
        ],
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

class OptionCard extends StatelessWidget {
  const OptionCard({super.key, required this.option});

  final LandedCostOption option;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final o = option;
    return AppCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (o.recommended)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.lg,
                vertical: AppSpacing.sm,
              ),
              decoration: const BoxDecoration(
                color: AppColors.accent,
                borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.md)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.star_rounded, size: 18, color: Colors.black87),
                  const SizedBox(width: 6),
                  Text(
                    context.tr('logistics.results.recommended'),
                    style: const TextStyle(
                      fontWeight: FontWeight.w900,
                      color: Colors.black87,
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
                    CircleAvatar(
                      radius: 20,
                      backgroundColor: AppColors.primary.withOpacity(0.10),
                      child: Icon(modeIcon(o.mode), color: theme.colorScheme.primary),
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Text(
                        context.tr('logistics.mode.${o.mode.json}'),
                        style: theme.textTheme.titleMedium
                            ?.copyWith(fontWeight: FontWeight.w800),
                      ),
                    ),
                    Icon(Icons.schedule, size: 16, color: theme.colorScheme.primary),
                    const SizedBox(width: 4),
                    Text(
                      context.tr('common.days', {
                        'min': '${o.transitDays.min}',
                        'max': '${o.transitDays.max}',
                      }),
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                Text(
                  context.tr('logistics.results.total'),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
                MoneyText.range(
                  o.total,
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w900,
                    color: theme.colorScheme.primary,
                  ),
                ),
                if (o.routeSummary != null) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    o.routeSummary!,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: AppColors.textSecondary, height: 1.4),
                  ),
                ],
                const SizedBox(height: AppSpacing.md),
                CostBar(lines: o.lines),
                for (final w in o.warnings) WarningBanner(text: w),
              ],
            ),
          ),
          Theme(
            data: theme.copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              title: Text(
                context.tr('logistics.results.breakdown'),
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              childrenPadding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                0,
                AppSpacing.lg,
                AppSpacing.lg,
              ),
              children: [for (final l in o.lines) _LineRow(line: l)],
            ),
          ),
        ],
      ),
    );
  }
}

class _LineRow extends StatelessWidget {
  const _LineRow({required this.line});

  final CostLine line;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 10,
            height: 10,
            margin: const EdgeInsets.only(top: 5),
            decoration: BoxDecoration(
              color: stageColor(line.stage),
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        context.tr('logistics.stage.${line.stage}'),
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                    ),
                    if (line.estimate) ...[
                      const SizedBox(width: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                          color: AppColors.warning.withOpacity(0.15),
                          borderRadius: BorderRadius.circular(AppRadius.sm),
                        ),
                        child: Text(
                          context.tr('common.estimate'),
                          style: const TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w800,
                            color: AppColors.warning,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
                Text(
                  line.description,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: AppColors.textSecondary, height: 1.3),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          MoneyText(line.amount),
        ],
      ),
    );
  }
}

class WarningBanner extends StatelessWidget {
  const WarningBanner({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: AppSpacing.sm),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.warning.withOpacity(0.12),
        border: Border.all(color: AppColors.warning.withOpacity(0.5)),
        borderRadius: BorderRadius.circular(AppRadius.sm),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.warning_amber_rounded, size: 20, color: AppColors.warning),
          const SizedBox(width: AppSpacing.sm),
          Expanded(child: Text(text, style: const TextStyle(height: 1.4, fontSize: 13))),
        ],
      ),
    );
  }
}

/// Horizontal stacked bar of cost by stage, drawn with plain Containers.
class CostBar extends StatelessWidget {
  const CostBar({super.key, required this.lines});

  final List<CostLine> lines;

  @override
  Widget build(BuildContext context) {
    final totals = <String, double>{};
    for (final l in lines) {
      final v = l.amount.value;
      if (v > 0) totals[l.stage] = (totals[l.stage] ?? 0) + v;
    }
    final sum = totals.values.fold<double>(0, (a, b) => a + b);
    if (sum <= 0) return const SizedBox.shrink();
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: SizedBox(
            height: 12,
            child: Row(
              children: [
                for (final e in totals.entries)
                  Expanded(
                    flex: ((e.value / sum) * 1000).round().clamp(1, 1000).toInt(),
                    child: Container(color: stageColor(e.key)),
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        Wrap(
          spacing: AppSpacing.md,
          runSpacing: 4,
          children: [
            for (final e in totals.entries)
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: stageColor(e.key),
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 4),
                  Text(
                    '${context.tr('logistics.stage.${e.key}')} ${(e.value / sum * 100).round()}%',
                    style: theme.textTheme.bodySmall?.copyWith(fontSize: 11),
                  ),
                ],
              ),
          ],
        ),
      ],
    );
  }
}
