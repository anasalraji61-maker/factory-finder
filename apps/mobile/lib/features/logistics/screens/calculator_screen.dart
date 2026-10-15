import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/data/freight_prefill.dart' show lastQuoteRequestProvider;
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_format.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:factory_finder/features/logistics/screens/hs_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Positive decimal of [s] as a plain string (null when invalid or zero).
String? _positive(String s) {
  final n = normalizeDecimalInput(s);
  return n == null || isZeroDecimal(n) ? null : n;
}

String _fmt(double v) => decimalString(v, digits: 6);

class CalculatorScreen extends ConsumerStatefulWidget {
  const CalculatorScreen({super.key, this.listingId});

  final String? listingId;

  @override
  ConsumerState<CalculatorScreen> createState() => _CalculatorScreenState();
}

class _CalculatorScreenState extends ConsumerState<CalculatorScreen> {
  final _unitPrice = TextEditingController();
  final _quantity = TextEditingController();
  final _totalValue = TextEditingController();
  final _weight = TextEditingController();
  final _volume = TextEditingController();
  final _hs = TextEditingController();

  bool _byUnit = true;
  bool _dangerous = false;
  bool _insurance = true;
  bool _loading = false;
  String _goodsCurrency = 'USD';
  late String _currency = ref.read(displayCurrencyProvider);
  Location _origin = const Location(countryCode: 'CN', city: 'Guangzhou');
  late Location _destination = ref.read(destinationProvider) ??
      const Location(countryCode: 'IQ', city: 'Baghdad');
  Incoterm _incoterm = Incoterm.fob;
  final Set<TransportMode> _modes = <TransportMode>{};
  ListingPrefill? _prefill;
  FreightOverride? _freightOverride;
  bool _prefillFailed = false;
  String? _valueError;
  String? _weightError;
  String? _volumeError;
  String? _hsError;

  @override
  void initState() {
    super.initState();
    final seed = ref.read(calculatorSeedProvider);
    if (seed != null) {
      _origin = seed.origin;
      _destination = seed.destination;
      _freightOverride = seed.freightOverride;
      Future<void>(() {
        if (mounted) ref.read(calculatorSeedProvider.notifier).state = null;
      });
    }
    final id = widget.listingId;
    if (id != null && id.isNotEmpty) {
      ref.read(logisticsRepositoryProvider).prefill(id).then((p) {
        if (!mounted) return;
        if (p == null) {
          setState(() => _prefillFailed = true);
          return;
        }
        setState(() {
          _prefill = p;
          _prefillFailed = false;
          _byUnit = true;
          _unitPrice.text = _fmt(p.unitPrice);
          _quantity.text = '${p.quantity}';
          _weight.text = decimalMul(_fmt(p.unitWeightKg), '${p.quantity}');
          _volume.text = decimalMul(_fmt(p.unitVolumeM3), '${p.quantity}');
          _hs.text = p.hsCode ?? '';
          _goodsCurrency = p.currency;
          _origin = p.origin;
          _incoterm = p.incoterm;
        });
      }).catchError((Object _) {
        if (mounted) setState(() => _prefillFailed = true);
      });
    }
  }

  @override
  void dispose() {
    _unitPrice.dispose();
    _quantity.dispose();
    _totalValue.dispose();
    _weight.dispose();
    _volume.dispose();
    _hs.dispose();
    super.dispose();
  }

  void _onQuantityChanged(String text) {
    final p = _prefill;
    final q = _positive(text);
    if (p == null || q == null) return;
    _weight.text = decimalMul(_fmt(p.unitWeightKg), q);
    _volume.text = decimalMul(_fmt(p.unitVolumeM3), q);
  }

  void _snack(String text, {SnackBarAction? action}) {
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(SnackBar(content: Text(text), action: action));
  }

  Future<void> _submit() async {
    if (_loading) return;
    String? valueText;
    if (_byUnit) {
      final u = _positive(_unitPrice.text);
      final q = _positive(_quantity.text);
      if (u != null && q != null) valueText = decimalMul(u, q);
    } else {
      valueText = _positive(_totalValue.text);
    }
    final weightText = _positive(_weight.text);
    final volRaw = _volume.text.trim();
    final volNorm = volRaw.isEmpty ? null : normalizeDecimalInput(volRaw);
    final hs = parseHsCode(_hs.text);
    final badValue = valueText == null;
    final badWeight = weightText == null;
    final badVolume = volRaw.isNotEmpty && volNorm == null;
    final badHs = !hs.ok;
    setState(() {
      _valueError = badValue ? context.tr('logistics.calc.invalid_value') : null;
      _weightError = badWeight ? context.tr('logistics.calc.invalid_weight') : null;
      _volumeError = badVolume ? context.tr('logistics.calc.invalid_volume') : null;
      _hsError = badHs ? context.tr('logistics.calc.invalid_hs') : null;
    });
    if (valueText == null || weightText == null) {
      _snack(context.tr('logistics.calc.invalid'));
      return;
    }
    if (badVolume || badHs) {
      _snack(context.tr(badVolume ? 'logistics.calc.invalid_volume' : 'logistics.calc.invalid_hs'));
      return;
    }
    final volumeText = volNorm == null || isZeroDecimal(volNorm) ? null : volNorm;
    final request = QuoteRequest(
      goodsValue: double.parse(valueText),
      goodsValueText: valueText,
      goodsCurrency: _goodsCurrency,
      weightKg: double.parse(weightText),
      weightText: weightText,
      volumeM3: volumeText == null ? 0 : double.parse(volumeText),
      volumeText: volumeText,
      hsCode: hs.code,
      dangerousGoods: _dangerous,
      origin: _origin,
      destination: _destination,
      incoterm: _incoterm,
      displayCurrency: _currency,
      insurance: _insurance,
      modes: Set<TransportMode>.of(_modes),
      freightOverride: _freightOverride,
    );
    final lang = ref.read(localeProvider).languageCode;
    setState(() => _loading = true);
    try {
      final quote = await ref
          .read(logisticsRepositoryProvider)
          .calculate(request, lang: lang);
      if (!mounted) return;
      ref.read(lastQuoteProvider.notifier).state = quote;
      ref.read(lastQuoteRequestProvider.notifier).state = request;
      context.push('/logistics/results');
    } catch (_) {
      if (mounted) {
        _snack(
          context.tr('logistics.calc.error'),
          action: SnackBarAction(
            label: context.tr('common.retry'),
            onPressed: _submit,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _section(String title, Widget child) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(title: title),
            child,
          ],
        ),
      );

  Widget _numberField(
    TextEditingController c,
    String label, {
    String? suffix,
    String? error,
    ValueChanged<String>? onChanged,
  }) {
    return TextField(
      controller: c,
      onChanged: (v) {
        if (error != null) {
          setState(() {
            _valueError = null;
            _weightError = null;
            _volumeError = null;
          });
        }
        onChanged?.call(v);
      },
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9٠-٩.,٫]'))],
      decoration: InputDecoration(labelText: label, suffixText: suffix, errorText: error),
    );
  }

  Widget _locationTile(String label, Location loc, ValueChanged<Location> onPicked) {
    return AppCard(
      padding: EdgeInsets.zero,
      child: ListTile(
        leading: CountryFlag(countryCode: loc.countryCode, size: 24),
        title: Text(label, style: const TextStyle(fontSize: 12, color: AppColors.textSecondary)),
        subtitle: Text(
          locationLabel(context, loc),
          style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
        ),
        trailing: const Icon(Icons.edit_outlined, size: 20),
        onTap: () async {
          final picked = await showLocationEditor(context, initial: loc);
          if (picked != null) setState(() => onPicked(picked));
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('logistics.calc.title'))),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          if (_prefill != null)
            Container(
              margin: const EdgeInsets.only(bottom: AppSpacing.lg),
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.accent.withOpacity(0.14),
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              child: Row(
                children: [
                  const Icon(Icons.auto_awesome, size: 18),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text(
                      context.tr('logistics.calc.prefilled', {'title': _prefill!.title}),
                    ),
                  ),
                ],
              ),
            ),
          if (_prefillFailed)
            Container(
              key: const ValueKey<String>('calc_prefill_failed'),
              margin: const EdgeInsets.only(bottom: AppSpacing.lg),
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.warning.withOpacity(0.14),
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              child: Text(context.tr('logistics.calc.prefill_failed')),
            ),
          if (_freightOverride != null)
            Container(
              key: const ValueKey<String>('calc_override_banner'),
              margin: const EdgeInsets.only(bottom: AppSpacing.lg),
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.success.withOpacity(0.12),
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
              child: Row(
                children: [
                  const Icon(Icons.verified_outlined, size: 18, color: AppColors.success),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text(
                      context.tr('logistics.calc.override', {
                        'amount': Money(
                          amount: _freightOverride!.amount,
                          currency: _freightOverride!.currency,
                        ).format(),
                      }),
                    ),
                  ),
                  IconButton(
                    key: const ValueKey<String>('calc_override_remove'),
                    tooltip: context.tr('logistics.calc.override_remove'),
                    icon: const Icon(Icons.close, size: 18),
                    onPressed: () => setState(() => _freightOverride = null),
                  ),
                ],
              ),
            ),
          _section(
            context.tr('logistics.calc.goods'),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SegmentedButton<bool>(
                  segments: [
                    ButtonSegment<bool>(
                      value: true,
                      label: Text(context.tr('logistics.calc.by_unit')),
                    ),
                    ButtonSegment<bool>(
                      value: false,
                      label: Text(context.tr('logistics.calc.by_total')),
                    ),
                  ],
                  selected: {_byUnit},
                  onSelectionChanged: (s) => setState(() => _byUnit = s.first),
                ),
                const SizedBox(height: AppSpacing.md),
                if (_byUnit)
                  Row(
                    children: [
                      Expanded(
                        child: _numberField(
                          _unitPrice,
                          context.tr('logistics.calc.unit_price'),
                          suffix: _goodsCurrency,
                          error: _valueError,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: _numberField(
                          _quantity,
                          context.tr('logistics.calc.quantity'),
                          error: _valueError == null ? null : '',
                          onChanged: _onQuantityChanged,
                        ),
                      ),
                    ],
                  )
                else
                  _numberField(
                    _totalValue,
                    context.tr('logistics.calc.total_value'),
                    suffix: _goodsCurrency,
                    error: _valueError,
                  ),
                const SizedBox(height: AppSpacing.sm),
                Text(
                  context.tr('logistics.calc.goods_currency'),
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
                ),
                const SizedBox(height: AppSpacing.xs),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.xs,
                  children: [
                    for (final c in kUsdRates.keys)
                      ChoiceChip(
                        key: ValueKey<String>('calc_goods_cur_$c'),
                        label: Text(c),
                        selected: _goodsCurrency == c,
                        onSelected: (_) => setState(() => _goodsCurrency = c),
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                Row(
                  children: [
                    Expanded(
                      child: _numberField(
                        _weight,
                        context.tr('logistics.calc.weight'),
                        error: _weightError,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: _numberField(
                        _volume,
                        context.tr('logistics.calc.volume'),
                        error: _volumeError,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                HsCodePicker(
                  controller: _hs,
                  destinationCountry: _destination.countryCode,
                  errorText: _hsError,
                  onChanged: (_) {
                    if (_hsError != null) setState(() => _hsError = null);
                  },
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(context.tr('logistics.calc.dangerous')),
                  value: _dangerous,
                  onChanged: (v) => setState(() => _dangerous = v),
                ),
              ],
            ),
          ),
          _section(
            context.tr('logistics.calc.origin'),
            _locationTile(
              context.tr('logistics.calc.origin'),
              _origin,
              (l) => _origin = l,
            ),
          ),
          _section(
            context.tr('logistics.calc.destination'),
            _locationTile(
              context.tr('logistics.calc.destination'),
              _destination,
              (l) => _destination = l,
            ),
          ),
          _section(
            context.tr('logistics.calc.incoterm'),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final i in Incoterm.values)
                  ChoiceChip(
                    label: Text(i.json),
                    selected: _incoterm == i,
                    onSelected: (_) => setState(() => _incoterm = i),
                  ),
              ],
            ),
          ),
          _section(
            context.tr('logistics.calc.currency'),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final c in kUsdRates.keys)
                  ChoiceChip(
                    key: ValueKey<String>('calc_display_cur_$c'),
                    label: Text(c),
                    selected: _currency == c,
                    onSelected: (_) => setState(() => _currency = c),
                  ),
              ],
            ),
          ),
          _section(
            context.tr('logistics.calc.modes'),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: [
                    for (final m in TransportMode.values)
                      FilterChip(
                        label: Text(context.tr('logistics.mode.${m.json}')),
                        selected: _modes.contains(m),
                        onSelected: (v) => setState(() {
                          if (v) {
                            _modes.add(m);
                          } else {
                            _modes.remove(m);
                          }
                        }),
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  context.tr('logistics.calc.modes_hint'),
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(context.tr('logistics.calc.insurance')),
                  value: _insurance,
                  onChanged: (v) => setState(() => _insurance = v),
                ),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: PrimaryButton(
            label: context.tr('logistics.calc.calculate'),
            icon: Icons.calculate_outlined,
            loading: _loading,
            onPressed: _submit,
          ),
        ),
      ),
    );
  }
}
