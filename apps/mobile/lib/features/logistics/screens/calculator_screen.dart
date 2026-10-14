import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/data/freight_prefill.dart' show lastQuoteRequestProvider;
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:factory_finder/features/logistics/screens/hs_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

double _num(String s) {
  const arabic = '٠١٢٣٤٥٦٧٨٩';
  final buffer = StringBuffer();
  for (final ch in s.trim().replaceAll(',', '').replaceAll('٫', '.').split('')) {
    final i = arabic.indexOf(ch);
    buffer.write(i >= 0 ? '$i' : ch);
  }
  return double.tryParse(buffer.toString()) ?? 0;
}

String _fmt(double v) {
  final s = v.toStringAsFixed(4);
  return s.replaceFirst(RegExp(r'\.?0+$'), '');
}

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

  @override
  void initState() {
    super.initState();
    final id = widget.listingId;
    if (id != null && id.isNotEmpty) {
      ref.read(logisticsRepositoryProvider).prefill(id).then((p) {
        if (!mounted || p == null) return;
        setState(() {
          _prefill = p;
          _byUnit = true;
          _unitPrice.text = _fmt(p.unitPrice);
          _quantity.text = '${p.quantity}';
          _weight.text = _fmt(p.unitWeightKg * p.quantity);
          _volume.text = _fmt(p.unitVolumeM3 * p.quantity);
          _hs.text = p.hsCode ?? '';
          _goodsCurrency = p.currency;
          _origin = p.origin;
          _incoterm = p.incoterm;
        });
      }).catchError((Object _) {});
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
    if (p == null) return;
    final q = _num(text);
    if (q <= 0) return;
    _weight.text = _fmt(p.unitWeightKg * q);
    _volume.text = _fmt(p.unitVolumeM3 * q);
  }

  void _snack(String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _submit() async {
    final value = _byUnit ? _num(_unitPrice.text) * _num(_quantity.text) : _num(_totalValue.text);
    final weight = _num(_weight.text);
    if (value <= 0 || weight <= 0) {
      _snack(context.tr('logistics.calc.invalid'));
      return;
    }
    final hs = _hs.text.trim();
    final request = QuoteRequest(
      goodsValue: value,
      goodsCurrency: _goodsCurrency,
      weightKg: weight,
      volumeM3: _num(_volume.text),
      hsCode: hs.isEmpty ? null : hs,
      dangerousGoods: _dangerous,
      origin: _origin,
      destination: _destination,
      incoterm: _incoterm,
      displayCurrency: _currency,
      insurance: _insurance,
      modes: Set<TransportMode>.of(_modes),
    );
    final lang = ref.read(localeProvider).languageCode;
    setState(() => _loading = true);
    try {
      final quote = await ref
          .read(logisticsRepositoryProvider)
          .calculate(request, lang: lang);
      ref.read(lastQuoteProvider.notifier).state = quote;
      ref.read(lastQuoteRequestProvider.notifier).state = request;
      if (!mounted) return;
      context.push('/logistics/results');
    } catch (e) {
      if (mounted) _snack('$e');
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
    ValueChanged<String>? onChanged,
  }) {
    return TextField(
      controller: c,
      onChanged: onChanged,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9٠-٩.,٫]'))],
      decoration: InputDecoration(labelText: label, suffixText: suffix),
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
                        ),
                      ),
                      const SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: _numberField(
                          _quantity,
                          context.tr('logistics.calc.quantity'),
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
                  ),
                const SizedBox(height: AppSpacing.md),
                Row(
                  children: [
                    Expanded(
                      child: _numberField(_weight, context.tr('logistics.calc.weight')),
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: _numberField(_volume, context.tr('logistics.calc.volume')),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                HsCodePicker(
                  controller: _hs,
                  destinationCountry: _destination.countryCode,
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
