import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/data/freight_decimal.dart';
import 'package:factory_finder/features/freight/data/freight_drafts.dart';
import 'package:factory_finder/features/freight/data/freight_errors.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/data/freight_prefill.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/freight/screens/freight_home_screen.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Create a shipment quote request. Reads [freightPrefillProvider] once.
class CreateFreightRequestScreen extends ConsumerStatefulWidget {
  const CreateFreightRequestScreen({super.key, this.now});

  /// Clock override for tests.
  final DateTime Function()? now;

  @override
  ConsumerState<CreateFreightRequestScreen> createState() =>
      _CreateFreightRequestScreenState();
}

class _CreateFreightRequestScreenState
    extends ConsumerState<CreateFreightRequestScreen> {
  final GlobalKey<FormState> _form = GlobalKey<FormState>();
  final TextEditingController _originPlace = TextEditingController();
  final TextEditingController _destPlace = TextEditingController();
  final TextEditingController _cargo = TextEditingController();
  final TextEditingController _hs = TextEditingController();
  final TextEditingController _weight = TextEditingController();
  final TextEditingController _volume = TextEditingController();
  final TextEditingController _containerCount = TextEditingController(text: '1');
  final TextEditingController _currency = TextEditingController(text: 'USD');

  String _originCountry = 'CN';
  String _destCountry = 'IQ';
  String _mode = 'sea';
  String? _container;
  String _incoterm = 'FOB';
  int _deadlineDays = 14;
  String? _landedRef;
  late DateTime _ready;
  String? _error;
  bool _busy = false;
  bool _prefilled = false;

  DateTime _now() => (widget.now ?? DateTime.now)();

  @override
  void initState() {
    super.initState();
    final n = _now();
    _ready = DateTime(n.year, n.month, n.day).add(const Duration(days: 14));
    final p = ref.read(freightPrefillProvider);
    if (p != null) {
      _prefilled = true;
      _originCountry = p.originCountry ?? _originCountry;
      _destCountry = p.destinationCountry ?? _destCountry;
      _originPlace.text = p.originPlace ?? '';
      _destPlace.text = p.destinationPlace ?? '';
      _mode = p.mode ?? _mode;
      _container = p.containerType;
      _incoterm = p.incoterm ?? _incoterm;
      _weight.text = p.weightKg ?? '';
      _volume.text = p.volumeCbm ?? '';
      _hs.text = p.hsCode ?? '';
      _landedRef = p.landedCostRef;
      _currency.text = p.currency ?? 'USD';
    }
  }

  @override
  void dispose() {
    for (final c in [_originPlace, _destPlace, _cargo, _hs, _weight, _volume, _containerCount, _currency]) {
      c.dispose();
    }
    super.dispose();
  }

  String? _v(String? Function() check) {
    final key = check();
    return key == null ? null : context.tr(key);
  }

  bool get _containerAllowed => _mode == 'sea' || _mode == 'rail';

  RequestDraft _draft() => RequestDraft(
        originCountry: _originCountry,
        originPlace: _originPlace.text,
        destinationCountry: _destCountry,
        destinationPlace: _destPlace.text,
        cargoDescription: _cargo.text,
        hsCode: _hs.text,
        weightKg: _weight.text,
        volumeCbm: _volume.text,
        mode: _mode,
        containerType: _containerAllowed ? _container : null,
        containerCount: _containerAllowed && _container != null
            ? (int.tryParse(FreightDecimal.normalize(_containerCount.text) ?? '') ?? 1)
            : null,
        incoterm: _incoterm,
        readyDate: _ready,
        currency: _currency.text.trim().toUpperCase(),
        quoteDeadlineDays: _deadlineDays,
        landedCostRef: _landedRef,
      );

  Future<void> _pickDate() async {
    final n = _now();
    final localToday = DateTime(n.year, n.month, n.day);
    // The server window is UTC based (today .. +365 days): never offer a
    // date it would reject, whatever the device time zone.
    final u = n.toUtc();
    final utcToday = DateTime(u.year, u.month, u.day);
    final today = localToday.isAfter(utcToday) ? localToday : utcToday;
    final last = utcToday.add(const Duration(days: 365));
    final initial = _ready.isBefore(today)
        ? today
        : (_ready.isAfter(last) ? last : _ready);
    final picked = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: today,
      lastDate: last,
    );
    if (picked != null && mounted) setState(() => _ready = picked);
  }

  Future<void> _submit() async {
    setState(() => _error = null);
    if (!(_form.currentState?.validate() ?? false)) return;
    final draft = _draft();
    final invalid = draft.validate(_now());
    if (invalid != null) {
      setState(() => _error = context.tr(invalid));
      return;
    }
    setState(() => _busy = true);
    try {
      final created = await ref.read(freightRepositoryProvider).createRequest(draft);
      ref.read(freightRefreshProvider.notifier).state++;
      ref.read(freightPrefillProvider.notifier).state = null;
      if (!mounted) return;
      context.pushReplacement('$kFreightBase/requests/${created.id}');
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = context.freightError(e);
      });
    }
  }

  Widget _gap() => const SizedBox(height: AppSpacing.md);

  @override
  Widget build(BuildContext context) {
    final textInputFormatters = <TextInputFormatter>[
      FilteringTextInputFormatter.allow(RegExp(r'[0-9٠-٩۰-۹.,٫]')),
    ];
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('freight.new_request'))),
      body: Form(
        key: _form,
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            if (_prefilled)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: FreightChip(
                  context.tr('freight.form.prefilled'),
                  icon: Icons.auto_fix_high,
                ),
              ),
            if (_error != null)
              FreightErrorBox(_error!, key: const ValueKey<String>('freight_form_error')),
            SectionHeader(title: context.tr('freight.form.route')),
            FreightCountryDropdown(
              label: context.tr('freight.form.origin_country'),
              value: _originCountry,
              onChanged: (v) => setState(() => _originCountry = v),
            ),
            _gap(),
            TextFormField(
              key: const ValueKey<String>('freight_origin_place'),
              controller: _originPlace,
              maxLength: 80,
              decoration: InputDecoration(labelText: context.tr('freight.form.origin_place')),
              validator: (v) => _v(() => FreightValidators.place(v ?? '')),
            ),
            FreightCountryDropdown(
              label: context.tr('freight.form.dest_country'),
              value: _destCountry,
              onChanged: (v) => setState(() => _destCountry = v),
            ),
            _gap(),
            TextFormField(
              key: const ValueKey<String>('freight_dest_place'),
              controller: _destPlace,
              maxLength: 80,
              decoration: InputDecoration(labelText: context.tr('freight.form.dest_place')),
              validator: (v) => _v(() => FreightValidators.place(v ?? '')),
            ),
            SectionHeader(title: context.tr('freight.form.cargo')),
            TextFormField(
              key: const ValueKey<String>('freight_cargo'),
              controller: _cargo,
              maxLength: 500,
              maxLines: 3,
              minLines: 2,
              decoration: InputDecoration(
                labelText: context.tr('freight.form.cargo_desc'),
                helperText: context.tr('freight.form.no_contacts'),
                helperMaxLines: 2,
              ),
              validator: (v) => _v(() => FreightValidators.cargo(v ?? '')),
            ),
            _gap(),
            TextFormField(
              key: const ValueKey<String>('freight_hs'),
              controller: _hs,
              decoration: InputDecoration(labelText: context.tr('freight.form.hs')),
              validator: (v) => _v(() => FreightValidators.hs(v ?? '')),
            ),
            _gap(),
            TextFormField(
              key: const ValueKey<String>('freight_weight'),
              controller: _weight,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: textInputFormatters,
              decoration: InputDecoration(labelText: context.tr('freight.form.weight')),
              validator: (v) => _v(() => FreightValidators.weightField(v ?? '', _volume.text)),
            ),
            _gap(),
            TextFormField(
              key: const ValueKey<String>('freight_volume'),
              controller: _volume,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: textInputFormatters,
              decoration: InputDecoration(labelText: context.tr('freight.form.volume')),
              validator: (v) => _v(() => FreightValidators.volumeField(_weight.text, v ?? '')),
            ),
            SectionHeader(title: context.tr('freight.form.shipping')),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final m in kFreightModes)
                  ChoiceChip(
                    key: ValueKey<String>('freight_mode_$m'),
                    avatar: Icon(freightModeIcon(m), size: 18),
                    label: Text(freightModeName(context, m)),
                    selected: _mode == m,
                    onSelected: (_) => setState(() {
                      _mode = m;
                      if (!_containerAllowed) _container = null;
                    }),
                  ),
              ],
            ),
            if (_containerAllowed) ...[
              _gap(),
              DropdownButtonFormField<String?>(
                key: const ValueKey<String>('freight_container'),
                value: _container,
                isExpanded: true,
                decoration: InputDecoration(labelText: context.tr('freight.form.container')),
                items: [
                  DropdownMenuItem<String?>(
                    value: null,
                    child: Text(context.tr('freight.form.container_none')),
                  ),
                  for (final c in kContainerTypes)
                    DropdownMenuItem<String?>(value: c, child: Text(c)),
                ],
                onChanged: (v) => setState(() => _container = v),
              ),
              if (_container != null) ...[
                _gap(),
                TextFormField(
                  key: const ValueKey<String>('freight_container_count'),
                  controller: _containerCount,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(labelText: context.tr('freight.form.container_count')),
                  validator: (v) => _v(() => FreightValidators.intRange(
                      v ?? '', 1, 500, 'freight.v.container_count')),
                ),
              ],
            ],
            _gap(),
            DropdownButtonFormField<String>(
              key: const ValueKey<String>('freight_incoterm'),
              value: _incoterm,
              isExpanded: true,
              decoration: InputDecoration(labelText: context.tr('freight.form.incoterm')),
              items: [
                for (final i in kFreightIncoterms)
                  DropdownMenuItem<String>(value: i, child: Text(i)),
              ],
              onChanged: (v) => setState(() => _incoterm = v ?? _incoterm),
            ),
            _gap(),
            OutlinedButton.icon(
              key: const ValueKey<String>('freight_ready_date'),
              style: OutlinedButton.styleFrom(minimumSize: const Size(64, 52)),
              onPressed: _pickDate,
              icon: const Icon(Icons.event_outlined),
              label: Text(
                context.tr('freight.form.ready_date', {'d': formatIsoDate(_ready)}),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            SectionHeader(title: context.tr('freight.form.quotes')),
            TextFormField(
              key: const ValueKey<String>('freight_currency'),
              controller: _currency,
              maxLength: 3,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                labelText: context.tr('freight.form.currency'),
                helperText: context.tr('freight.form.currency_hint'),
                helperMaxLines: 2,
              ),
              validator: (v) =>
                  _v(() => FreightValidators.currency((v ?? '').trim().toUpperCase())),
            ),
            _gap(),
            DropdownButtonFormField<int>(
              key: const ValueKey<String>('freight_deadline'),
              value: _deadlineDays,
              isExpanded: true,
              decoration: InputDecoration(labelText: context.tr('freight.form.deadline')),
              items: [
                for (final d in const [3, 7, 14, 21, 30])
                  DropdownMenuItem<int>(
                    value: d,
                    child: Text(context.tr('freight.days', {'n': '$d'})),
                  ),
              ],
              onChanged: (v) => setState(() => _deadlineDays = v ?? _deadlineDays),
            ),
            const SizedBox(height: AppSpacing.xl),
            PrimaryButton(
              key: const ValueKey<String>('freight_submit_request'),
              label: context.tr('freight.form.submit'),
              icon: Icons.send_outlined,
              loading: _busy,
              onPressed: _submit,
            ),
            const SizedBox(height: AppSpacing.xl),
          ],
        ),
      ),
    );
  }
}
