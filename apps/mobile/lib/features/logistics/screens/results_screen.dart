import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/screens/freight_quote_button.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart' show formatDate;
import 'package:factory_finder/features/freight/data/freight_prefill.dart' show lastQuoteRequestProvider;
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart' show kUsdRates;
import 'package:factory_finder/features/logistics/data/quote_format.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:factory_finder/features/logistics/data/saved_quotes.dart';
import 'package:factory_finder/features/logistics/screens/sensitivity_section.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

class ResultsScreen extends ConsumerStatefulWidget {
  const ResultsScreen({super.key});

  @override
  ConsumerState<ResultsScreen> createState() => _ResultsScreenState();
}

class _ResultsScreenState extends ConsumerState<ResultsScreen> {
  bool _busy = false;
  String? _failedCurrency;

  /// The request that produced the quote on screen, or null when unknown
  /// (e.g. a saved quote) - then the currency cannot be recomputed.
  QuoteRequest? _requestFor(LandedCostQuote quote) {
    final r = ref.read(lastQuoteRequestProvider);
    if (r == null || r.displayCurrency != quote.currency) return null;
    return r;
  }

  Future<void> _recalc(String currency) async {
    final quote = ref.read(lastQuoteProvider);
    final req = quote == null ? null : _requestFor(quote);
    if (req == null || _busy || currency == req.displayCurrency) return;
    final next = req.copyWith(displayCurrency: currency);
    final lang = ref.read(localeProvider).languageCode;
    setState(() {
      _busy = true;
      _failedCurrency = null;
    });
    try {
      final q = await ref.read(logisticsRepositoryProvider).calculate(next, lang: lang);
      if (!mounted) return;
      ref.read(lastQuoteProvider.notifier).state = q;
      ref.read(lastQuoteRequestProvider.notifier).state = next;
      setState(() => _busy = false);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _failedCurrency = currency;
      });
    }
  }

  void _snack(String text) {
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _copy(LandedCostQuote quote, Incoterm? incoterm) async {
    final text = buildQuoteShareText(
      quote,
      incoterm: incoterm,
      t: (String k, [Map<String, String> a = const {}]) => context.tr(k, a),
      modeName: (m) => context.tr('logistics.mode.${m.json}'),
    );
    final done = context.tr('logistics.results.copied');
    try {
      await Clipboard.setData(ClipboardData(text: text));
    } catch (_) {
      // Clipboard unavailable: nothing else to do.
    }
    if (mounted) _snack(done);
  }

  Future<void> _save(LandedCostQuote quote, Incoterm? incoterm) async {
    final done = context.tr('logistics.results.saved');
    await ref.read(savedQuotesProvider.notifier).save(quote, incoterm: incoterm);
    if (mounted) _snack(done);
  }

  @override
  Widget build(BuildContext context) {
    final quote = ref.watch(lastQuoteProvider);
    ref.watch(lastQuoteRequestProvider);
    final savedList = ref.watch(savedQuotesProvider);
    final request = quote == null ? null : _requestFor(quote);
    SavedQuote? saved;
    if (quote != null) {
      for (final s in savedList) {
        if (s.quote.id == quote.id) {
          saved = s;
          break;
        }
      }
    }
    final incoterm = request?.incoterm ?? saved?.incoterm;
    final validUntil = request?.freightOverride?.validUntil;
    return Scaffold(
      appBar: AppBar(
        title: Text(context.tr('logistics.results.title')),
        actions: [
          if (quote != null && quote.options.isNotEmpty) ...[
            IconButton(
              key: const ValueKey<String>('results_copy'),
              tooltip: context.tr('logistics.results.copy'),
              icon: const Icon(Icons.ios_share_outlined),
              onPressed: () => _copy(quote, incoterm),
            ),
            IconButton(
              key: const ValueKey<String>('results_save'),
              tooltip: context.tr('logistics.results.save'),
              icon: Icon(saved != null ? Icons.bookmark : Icons.bookmark_border),
              onPressed: () => _save(quote, incoterm),
            ),
          ],
        ],
      ),
      body: quote == null
          ? EmptyState(
              icon: Icons.receipt_long_outlined,
              title: context.tr('logistics.results.none'),
              message: context.tr('logistics.results.none_msg'),
            )
          : _QuoteView(
              quote: quote,
              quotedValidUntil: validUntil,
              incoterm: incoterm,
              canRecalc: request != null,
              busy: _busy,
              failedCurrency: _failedCurrency,
              onCurrency: _recalc,
              savedAt: request == null ? saved?.savedAt : null,
            ),
    );
  }
}

class _QuoteView extends StatelessWidget {
  const _QuoteView({
    required this.quote,
    this.quotedValidUntil,
    this.incoterm,
    this.canRecalc = false,
    this.busy = false,
    this.failedCurrency,
    this.onCurrency,
    this.savedAt,
  });

  final LandedCostQuote quote;
  final DateTime? quotedValidUntil;
  final Incoterm? incoterm;
  final bool canRecalc;
  final bool busy;
  final String? failedCurrency;
  final ValueChanged<String>? onCurrency;
  final DateTime? savedAt;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: [
        AppCard(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
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
              if (incoterm != null) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  context.tr('logistics.results.incoterm', {'i': incoterm!.json}),
                  key: const ValueKey<String>('results_incoterm'),
                  style: theme.textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ],
          ),
        ),
        if (savedAt != null)
          WarningBanner(
            text: context.tr('logistics.results.saved_note', {'d': formatDate(context, savedAt)}),
          ),
        for (final w in quote.warnings) WarningBanner(text: w),
        if (canRecalc) ...[
          const SizedBox(height: AppSpacing.md),
          Text(
            context.tr('logistics.results.currency'),
            style: theme.textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.xs),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.xs,
            children: [
              for (final c in kUsdRates.keys)
                ChoiceChip(
                  key: ValueKey<String>('results_cur_$c'),
                  label: Text(c),
                  selected: quote.currency == c,
                  onSelected: busy ? null : (_) => onCurrency?.call(c),
                ),
            ],
          ),
          if (busy) ...[
            const SizedBox(height: AppSpacing.sm),
            const LinearProgressIndicator(key: ValueKey<String>('results_recalc_progress')),
            const SizedBox(height: 4),
            Text(
              context.tr('logistics.results.recalculating'),
              style: theme.textTheme.bodySmall,
            ),
          ],
          if (failedCurrency != null && !busy)
            Container(
              key: const ValueKey<String>('results_recalc_error'),
              margin: const EdgeInsets.only(top: AppSpacing.sm),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      context.tr('logistics.results.recalc_failed'),
                      style: const TextStyle(color: AppColors.danger),
                    ),
                  ),
                  TextButton(
                    key: const ValueKey<String>('results_recalc_retry'),
                    onPressed: () => onCurrency?.call(failedCurrency!),
                    child: Text(context.tr('common.retry')),
                  ),
                ],
              ),
            ),
        ],
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
              child: OptionCard(
                option: o,
                quotedValidUntil: quotedValidUntil,
                incoterm: incoterm,
              ),
            ),
        FreightQuoteButton(quote: quote),
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

/// Estimate / confidence / as-of chips plus the honest range note.
class EstimateBadges extends StatelessWidget {
  const EstimateBadges({super.key, required this.label});

  final EstimateLabel label;

  Widget _chip(String text, Color color, {Key? key}) => Container(
        key: key,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: color.withOpacity(0.15),
          borderRadius: BorderRadius.circular(AppRadius.sm),
        ),
        child: Text(
          text,
          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: color),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (!label.isEstimate) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _chip(context.tr('logistics.exact'), AppColors.success,
              key: const ValueKey<String>('est_exact')),
          const SizedBox(height: 4),
          Text(
            context.tr('logistics.exact_note'),
            style: theme.textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
          ),
        ],
      );
    }
    final c = label.confidence;
    final confColor = c == QuoteConfidence.high
        ? AppColors.success
        : (c == QuoteConfidence.medium ? AppColors.warning : AppColors.danger);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: [
            _chip(context.tr('common.estimate'), AppColors.warning,
                key: const ValueKey<String>('est_badge')),
            _chip(
              context.tr('logistics.confidence.label', {
                'c': confidenceText(
                  (String k, [Map<String, String> a = const {}]) => context.tr(k, a),
                  c,
                ),
              }),
              confColor,
              key: const ValueKey<String>('est_confidence'),
            ),
            if (label.asOf != null)
              _chip(
                context.tr('logistics.as_of', {'d': label.asOf!}),
                AppColors.primary,
                key: const ValueKey<String>('est_as_of'),
              ),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          context.tr('logistics.range_note'),
          key: const ValueKey<String>('est_range_note'),
          style: theme.textTheme.bodySmall
              ?.copyWith(color: AppColors.textSecondary, height: 1.4),
        ),
      ],
    );
  }
}

class OptionCard extends StatelessWidget {
  const OptionCard({
    super.key,
    required this.option,
    this.quotedValidUntil,
    this.incoterm,
  });

  final LandedCostOption option;

  /// Supplier incoterm of the request (explains zero "included" lines).
  final Incoterm? incoterm;

  /// Expiry of the forwarder quote behind a `quoted` main-leg line (if known).
  final DateTime? quotedValidUntil;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final o = option;
    final label = estimateLabelOf(o);
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
                  label.isEstimate
                      ? context.tr('logistics.estimate_total')
                      : context.tr('logistics.results.total'),
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
                const SizedBox(height: AppSpacing.xs),
                EstimateBadges(label: label),
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
              children: [
                for (final l in o.lines)
                  _LineRow(line: l, validUntil: quotedValidUntil, incoterm: incoterm),
              ],
            ),
          ),
          SensitivitySection(sensitivity: o.sensitivity),
        ],
      ),
    );
  }
}

class _LineRow extends StatelessWidget {
  const _LineRow({required this.line, this.validUntil, this.incoterm});

  final CostLine line;
  final DateTime? validUntil;
  final Incoterm? incoterm;

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
                Wrap(
                  spacing: 6,
                  runSpacing: 2,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                      context.tr('logistics.stage.${line.stage}'),
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    if (line.quoted) ...[
                      Container(
                        key: const ValueKey<String>('quoted_pill'),
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                          color: AppColors.success.withOpacity(0.15),
                          borderRadius: BorderRadius.circular(AppRadius.sm),
                        ),
                        child: Text(
                          context.tr('logistics.quoted'),
                          style: const TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w800,
                            color: AppColors.success,
                          ),
                        ),
                      ),
                    ] else if (line.estimate) ...[
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
                if (line.quoted)
                  Text(
                    validUntil == null
                        ? context.tr('logistics.quoted_exact')
                        : '${context.tr('logistics.quoted_exact')} · ${context.tr('logistics.quoted_valid', {
                              'date': formatDate(context, validUntil),
                            })}',
                    key: const ValueKey<String>('quoted_note'),
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: AppColors.success,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          if (incoterm != null &&
              !line.quoted &&
              isZeroDecimal(line.amount.amount) &&
              supplierCoversStage(incoterm!, line.stage))
            Text(
              context.tr('logistics.included'),
              key: ValueKey<String>('line_included_${line.stage}'),
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: AppColors.textSecondary,
              ),
            )
          else
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
