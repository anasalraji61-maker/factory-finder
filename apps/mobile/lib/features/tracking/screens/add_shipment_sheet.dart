import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/tracking/data/reference_validators.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/tracking_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Bottom sheet: pick reference type, enter number (validated client-side), submit.
class AddShipmentSheet extends ConsumerStatefulWidget {
  const AddShipmentSheet({super.key});

  @override
  ConsumerState<AddShipmentSheet> createState() => _AddShipmentSheetState();
}

class _AddShipmentSheetState extends ConsumerState<AddShipmentSheet> {
  final TextEditingController _ref = TextEditingController();
  final TextEditingController _carrier = TextEditingController();
  ReferenceType _type = ReferenceType.container;
  String? _errorKey;
  String? _serverError;
  bool _busy = false;
  bool _touched = false;
  List<String> _suggestions = const [];
  CarrierSuggestion? _carrierGuess;

  @override
  void dispose() {
    _ref.dispose();
    _carrier.dispose();
    super.dispose();
  }

  void _revalidate() {
    setState(() {
      _serverError = null;
      _suggestions = const [];
      _carrierGuess = null;
      _errorKey = _touched ? validateReference(_type, _ref.text) : null;
    });
  }

  /// Best-effort did-you-mean / carrier hints; failures are silently ignored.
  Future<void> _fetchHints() async {
    final text = _ref.text;
    final type = _type;
    if (text.trim().isEmpty) return;
    try {
      final check = await ref.read(trackingRepositoryProvider).validate(type, text);
      if (!mounted || _ref.text != text || _type != type) return;
      setState(() {
        _suggestions = check.valid ? const [] : check.suggestions;
        _carrierGuess = check.carrierSuggestion;
      });
    } catch (_) {
      // Hints are optional.
    }
  }

  void _applySuggestion(String value) {
    _ref.text = value;
    _touched = true;
    _revalidate();
    _fetchHints();
  }

  void _applyCarrier(CarrierSuggestion c) {
    setState(() {
      _carrier.text = c.label();
      _carrierGuess = null;
    });
  }

  Future<void> _submit() async {
    _touched = true;
    final key = validateReference(_type, _ref.text);
    if (key != null) {
      setState(() => _errorKey = key);
      _fetchHints();
      return;
    }
    setState(() {
      _busy = true;
      _serverError = null;
    });
    try {
      final shipment = await ref
          .read(trackingRepositoryProvider)
          .add(_ref.text, _type, carrier: _carrier.text);
      if (!mounted) return;
      Navigator.of(context).pop(shipment);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _serverError = 'tracking.err.generic';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final error = _errorKey ?? _serverError;
    return Padding(
      padding: EdgeInsets.fromLTRB(
        AppSpacing.lg,
        0,
        AppSpacing.lg,
        MediaQuery.of(context).viewInsets.bottom + AppSpacing.lg,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(context.tr('tracking.add'),
                style: Theme.of(context)
                    .textTheme
                    .titleLarge
                    ?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: AppSpacing.md),
            Text(context.tr('tracking.type')),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final t in ReferenceType.values)
                  ChoiceChip(
                    label: Text(context.tr(typeKey(t))),
                    selected: _type == t,
                    onSelected: (_) {
                      _type = t;
                      _revalidate();
                    },
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            Directionality(
              textDirection: TextDirection.ltr,
              child: TextField(
                controller: _ref,
                textCapitalization: TextCapitalization.characters,
                autocorrect: false,
                onChanged: (_) {
                  _touched = true;
                  _revalidate();
                },
                onEditingComplete: () {
                  FocusScope.of(context).nextFocus();
                  if (validateReference(_type, _ref.text) == null) _fetchHints();
                },
                decoration: InputDecoration(
                  labelText: context.tr('tracking.reference'),
                  errorText: error == null ? null : context.tr(error),
                  errorMaxLines: 3,
                ),
              ),
            ),
            if (_suggestions.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(context.tr('tracking.did_you_mean')),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: [
                  for (final s in _suggestions)
                    ActionChip(
                      key: Key('ref_suggestion_$s'),
                      label: Text(s, textDirection: TextDirection.ltr),
                      onPressed: () => _applySuggestion(s),
                    ),
                ],
              ),
            ],
            const SizedBox(height: AppSpacing.md),
            TextField(
              controller: _carrier,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(labelText: context.tr('tracking.carrier')),
            ),
            if (_carrierGuess != null && _carrier.text.trim().isEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(context.tr('tracking.carrier_guess')),
              const SizedBox(height: AppSpacing.sm),
              Align(
                alignment: AlignmentDirectional.centerStart,
                child: ActionChip(
                  key: const Key('carrier_suggestion'),
                  label: Text(
                    _carrierGuess!.label(
                        arabic: Localizations.localeOf(context).languageCode == 'ar'),
                  ),
                  onPressed: () => _applyCarrier(_carrierGuess!),
                ),
              ),
            ],
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: context.tr('tracking.submit'),
              icon: Icons.track_changes,
              loading: _busy,
              onPressed: _submit,
            ),
          ],
        ),
      ),
    );
  }
}
