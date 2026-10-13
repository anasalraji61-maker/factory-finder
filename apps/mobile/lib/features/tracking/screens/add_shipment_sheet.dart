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

  @override
  void dispose() {
    _ref.dispose();
    _carrier.dispose();
    super.dispose();
  }

  void _revalidate() {
    setState(() {
      _serverError = null;
      _errorKey = _touched ? validateReference(_type, _ref.text) : null;
    });
  }

  Future<void> _submit() async {
    _touched = true;
    final key = validateReference(_type, _ref.text);
    if (key != null) {
      setState(() => _errorKey = key);
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
                decoration: InputDecoration(
                  labelText: context.tr('tracking.reference'),
                  errorText: error == null ? null : context.tr(error),
                  errorMaxLines: 3,
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            TextField(
              controller: _carrier,
              decoration: InputDecoration(labelText: context.tr('tracking.carrier')),
            ),
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
