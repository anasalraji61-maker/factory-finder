import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:factory_finder/core/utils/number_format.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/fx/data/fx_models.dart';
import 'package:factory_finder/features/fx/data/fx_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

const Map<String, String> _currencyCountry = {
  'USD': 'US', 'EUR': 'EU', 'CNY': 'CN', 'IQD': 'IQ', 'TRY': 'TR',
  'AED': 'AE', 'SAR': 'SA', 'GBP': 'GB', 'IRR': 'IR',
};

class FxScreen extends ConsumerWidget {
  const FxScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final base = ref.watch(fxBaseProvider);
    final async = ref.watch(fxRatesProvider(base));
    final idx = kFxCurrencies.indexOf(base);

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('fx.title'))),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(fxRatesProvider(base));
          try {
            await ref.read(fxRatesProvider(base).future);
          } catch (_) {}
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              child: SectionHeader(title: context.tr('fx.base')),
            ),
            FilterChipBar(
              labels: kFxCurrencies,
              selectedIndex: idx < 0 ? 0 : idx,
              onSelected: (i) =>
                  ref.read(fxBaseProvider.notifier).state = kFxCurrencies[i],
            ),
            const SizedBox(height: AppSpacing.lg),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              child: const FxConverterCard(),
            ),
            const SizedBox(height: AppSpacing.lg),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              child: SectionHeader(
                title: context.tr('fx.rates_title', {'base': base}),
              ),
            ),
            async.when(
              loading: () => const Padding(
                padding: EdgeInsets.all(AppSpacing.xxl),
                child: Center(child: CircularProgressIndicator()),
              ),
              error: (e, _) => ErrorState(
                message: e.toString(),
                onRetry: () => ref.invalidate(fxRatesProvider(base)),
              ),
              data: (fx) {
                final codes = kFxCurrencies
                    .where((c) => c != base && fx.rates.containsKey(c))
                    .toList();
                if (codes.isEmpty) {
                  return EmptyState(
                    icon: Icons.currency_exchange,
                    title: context.tr('fx.empty_title'),
                    message: context.tr('fx.empty_msg'),
                  );
                }
                return Column(
                  children: [
                    for (final c in codes)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(
                            AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.sm),
                        child: AppCard(
                          child: Row(
                            children: [
                              CountryFlag(
                                  countryCode: _currencyCountry[c] ?? '', size: 22),
                              const SizedBox(width: AppSpacing.md),
                              Expanded(
                                child: Text(
                                  '1 $base = $c',
                                  style: const TextStyle(fontWeight: FontWeight.w600),
                                ),
                              ),
                              Directionality(
                                textDirection: TextDirection.ltr,
                                child: Text(
                                  localizeNumber(formatFx(fx.rateOf(c)), DigitStyleScope.of(context)),
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w800, fontSize: 16),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                      child: Text(
                        '${context.tr('fx.as_of', {'time': formatStamp(fx.timestamp)})}'
                        ' - ${context.tr('fx.source', {'source': fx.source})}',
                        style: Theme.of(context)
                            .textTheme
                            .bodySmall
                            ?.copyWith(color: AppColors.textSecondary),
                      ),
                    ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class FxConverterCard extends ConsumerStatefulWidget {
  const FxConverterCard({super.key});

  @override
  ConsumerState<FxConverterCard> createState() => _FxConverterCardState();
}

class _FxConverterCardState extends ConsumerState<FxConverterCard> {
  final TextEditingController _amount = TextEditingController(text: '100');
  String _from = 'USD';
  String _to = 'IQD';
  ConvertResult? _result;
  Object? _error;
  bool _invalid = false;
  int _seq = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _run());
  }

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  Future<void> _run() async {
    final value = double.tryParse(_amount.text.trim().replaceAll(',', ''));
    if (value == null || value < 0) {
      setState(() {
        _invalid = true;
        _result = null;
        _error = null;
      });
      return;
    }
    final seq = ++_seq;
    try {
      final r = await ref.read(fxRepositoryProvider).convert(value, _from, _to);
      if (!mounted || seq != _seq) return;
      setState(() {
        _invalid = false;
        _result = r;
        _error = null;
      });
    } catch (e) {
      if (!mounted || seq != _seq) return;
      setState(() {
        _invalid = false;
        _result = null;
        _error = e;
      });
    }
  }

  void _swap() {
    setState(() {
      final t = _from;
      _from = _to;
      _to = t;
    });
    _run();
  }

  Widget _dropdown(String value, ValueChanged<String> onChanged) {
    return DropdownButton<String>(
      value: value,
      isExpanded: true,
      underline: const SizedBox.shrink(),
      items: [
        for (final c in kFxCurrencies)
          DropdownMenuItem<String>(value: c, child: Text(c)),
      ],
      onChanged: (v) {
        if (v != null) onChanged(v);
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final r = _result;
    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(context.tr('fx.converter'),
              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
          const SizedBox(height: AppSpacing.md),
          TextField(
            controller: _amount,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            inputFormatters: [
              FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
            ],
            decoration: InputDecoration(
              labelText: context.tr('fx.amount'),
              errorText: _invalid ? context.tr('fx.invalid_amount') : null,
              border: const OutlineInputBorder(),
            ),
            onChanged: (_) => _run(),
          ),
          const SizedBox(height: AppSpacing.md),
          Row(
            children: [
              Expanded(child: _dropdown(_from, (v) {
                setState(() => _from = v);
                _run();
              })),
              IconButton(
                tooltip: context.tr('fx.swap'),
                onPressed: _swap,
                icon: const Icon(Icons.swap_horiz),
              ),
              Expanded(child: _dropdown(_to, (v) {
                setState(() => _to = v);
                _run();
              })),
            ],
          ),
          const Divider(),
          if (_error != null)
            Text(_error.toString(), style: TextStyle(color: theme.colorScheme.error))
          else if (r != null) ...[
            Directionality(
              textDirection: TextDirection.ltr,
              child: Text(
                localizeNumber(
                    '${formatFxString(r.amount)} ${r.currency}',
                    DigitStyleScope.of(context)),
                style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.w900,
                  color: theme.colorScheme.primary,
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              context.tr('fx.rate_line', {
                'from': r.from,
                'to': r.to,
                'rate': isolateLtr(
                    localizeNumber(formatFxString(r.rate), DigitStyleScope.of(context))),
              }),
              style: theme.textTheme.bodySmall,
            ),
            Text(
              context.tr('fx.as_of', {'time': formatStamp(r.timestamp)}),
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: AppColors.textSecondary),
            ),
          ] else
            const SizedBox(height: 24),
        ],
      ),
    );
  }
}
