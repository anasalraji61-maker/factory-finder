import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart' show formatDate;
import 'package:factory_finder/features/freight/data/freight_prefill.dart' show lastQuoteRequestProvider;
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/quote_format.dart';
import 'package:factory_finder/features/logistics/data/saved_quotes.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

class LogisticsScreen extends ConsumerWidget {
  const LogisticsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final last = ref.watch(lastQuoteProvider);
    final saved = ref.watch(savedQuotesProvider);
    final theme = Theme.of(context);
    final tools = <(IconData, String, String?)>[
      (Icons.currency_exchange, 'logistics.tool.fx', '/logistics/fx'),
      (Icons.directions_boat_outlined, 'logistics.tool.carriers', '/logistics/carriers'),
      (Icons.request_quote_outlined, 'logistics.tool.freight', '/logistics/freight'),
      (Icons.track_changes, 'logistics.tool.tracking', '/logistics/tracking'),
      (Icons.smart_toy_outlined, 'logistics.tool.assistant', '/assistant'),
    ];

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('logistics.title'))),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          Container(
            padding: const EdgeInsets.all(AppSpacing.xl),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [AppColors.primary, AppColors.primaryDark],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(AppRadius.lg),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.local_shipping_rounded, color: AppColors.accent, size: 36),
                const SizedBox(height: AppSpacing.md),
                Text(
                  context.tr('logistics.hero_title'),
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 22,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                Text(
                  context.tr('logistics.hero_msg'),
                  style: const TextStyle(color: Colors.white70, height: 1.5),
                ),
                const SizedBox(height: AppSpacing.lg),
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    foregroundColor: Colors.black,
                    minimumSize: const Size(0, 48),
                  ),
                  onPressed: () => context.push('/logistics/calculator'),
                  icon: const Icon(Icons.calculate_outlined),
                  label: Text(
                    context.tr('logistics.open_calc'),
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
              ],
            ),
          ),
          if (last != null) ...[
            const SizedBox(height: AppSpacing.lg),
            SectionHeader(title: context.tr('logistics.last_quote')),
            AppCard(
              onTap: () => context.push('/logistics/results'),
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Row(
                children: [
                  CountryFlag(countryCode: last.origin?.countryCode ?? 'CN', size: 22),
                  const Icon(Icons.arrow_right_alt, size: 20),
                  CountryFlag(countryCode: last.destination?.countryCode ?? 'IQ', size: 22),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: last.options.isEmpty
                        ? Text(context.tr('logistics.results.no_options'))
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              MoneyText.range(
                                last.options
                                    .firstWhere(
                                      (o) => o.recommended,
                                      orElse: () => last.options.first,
                                    )
                                    .total,
                              ),
                              Text(
                                _estimateLine(context, last),
                                key: const ValueKey<String>('last_quote_estimate'),
                                style: theme.textTheme.bodySmall
                                    ?.copyWith(color: AppColors.textSecondary),
                              ),
                            ],
                          ),
                  ),
                  Text(
                    context.tr('logistics.view'),
                    style: TextStyle(color: theme.colorScheme.primary),
                  ),
                ],
              ),
            ),
          ],
          if (saved.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.lg),
            SectionHeader(title: context.tr('logistics.saved.title')),
            for (final s in saved)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: AppCard(
                  key: ValueKey<String>('saved_${s.quote.id}'),
                  onTap: () {
                    ref.read(lastQuoteProvider.notifier).state = s.quote;
                    // The original request is unknown: results hide the
                    // currency switch instead of recomputing the wrong thing.
                    ref.read(lastQuoteRequestProvider.notifier).state = null;
                    context.push('/logistics/results');
                  },
                  child: Row(
                    children: [
                      CountryFlag(countryCode: s.quote.origin?.countryCode ?? 'CN', size: 20),
                      const Icon(Icons.arrow_right_alt, size: 20),
                      CountryFlag(countryCode: s.quote.destination?.countryCode ?? 'IQ', size: 20),
                      const SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (s.quote.options.isNotEmpty)
                              MoneyText.range(
                                s.quote.options
                                    .firstWhere(
                                      (o) => o.recommended,
                                      orElse: () => s.quote.options.first,
                                    )
                                    .total,
                              ),
                            Text(
                              '${_estimateLine(context, s.quote)} · ${formatDate(context, s.savedAt)}',
                              style: theme.textTheme.bodySmall
                                  ?.copyWith(color: AppColors.textSecondary),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        key: ValueKey<String>('saved_delete_${s.quote.id}'),
                        tooltip: context.tr('logistics.saved.delete'),
                        icon: const Icon(Icons.delete_outline),
                        onPressed: () =>
                            ref.read(savedQuotesProvider.notifier).remove(s.quote.id),
                      ),
                    ],
                  ),
                ),
              ),
          ],
          const SizedBox(height: AppSpacing.lg),
          SectionHeader(title: context.tr('logistics.tools')),
          for (final tool in tools)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: AppCard(
                onTap: tool.$3 == null ? null : () => context.push(tool.$3!),
                child: Row(
                  children: [
                    Icon(tool.$1, color: AppColors.textSecondary),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(child: Text(context.tr(tool.$2))),
                    if (tool.$3 == null)
                      Text(
                        context.tr('common.coming_soon'),
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: AppColors.textSecondary),
                      )
                    else
                      const Icon(Icons.chevron_right,
                          color: AppColors.textSecondary),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// "Estimate · Confidence: low · As of 2026-10" (or "Exact").
String _estimateLine(BuildContext context, LandedCostQuote q) {
  final l = estimateLabelOfQuote(q);
  if (!l.isEstimate) return context.tr('logistics.exact');
  String t(String k, [Map<String, String> a = const {}]) => context.tr(k, a);
  final parts = <String>[
    t('common.estimate'),
    t('logistics.confidence.label', {'c': confidenceText(t, l.confidence)}),
    if (l.asOf != null) t('logistics.as_of', {'d': l.asOf!}),
  ];
  return parts.join(' · ');
}
