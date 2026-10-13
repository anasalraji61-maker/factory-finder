import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/common_widgets.dart';
import 'package:flutter/material.dart';

const List<String> kCountryCodes = [
  'CN', 'IQ', 'TR', 'AE', 'SA', 'DE', 'IT', 'US', 'IN', 'EG', 'JO', 'KW',
];

/// Bottom sheet to pick a country + free-text city. Returns null if dismissed.
Future<Location?> showLocationEditor(
  BuildContext context, {
  required Location initial,
}) {
  return showModalBottomSheet<Location>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (ctx) => _LocationEditor(initial: initial),
  );
}

class _LocationEditor extends StatefulWidget {
  const _LocationEditor({required this.initial});

  final Location initial;

  @override
  State<_LocationEditor> createState() => _LocationEditorState();
}

class _LocationEditorState extends State<_LocationEditor> {
  late String _country = widget.initial.countryCode;
  late final TextEditingController _city =
      TextEditingController(text: widget.initial.city ?? '');

  @override
  void dispose() {
    _city.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;
    return Padding(
      padding: EdgeInsets.fromLTRB(
        AppSpacing.lg,
        0,
        AppSpacing.lg,
        AppSpacing.lg + bottom,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              context.tr('location.country'),
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final code in kCountryCodes)
                  ChoiceChip(
                    avatar: CountryFlag(countryCode: code, size: 16),
                    label: Text(context.tr('country.$code')),
                    selected: _country == code,
                    onSelected: (_) => setState(() => _country = code),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.lg),
            TextField(
              controller: _city,
              decoration: InputDecoration(labelText: context.tr('location.city')),
            ),
            const SizedBox(height: AppSpacing.lg),
            SizedBox(
              width: double.infinity,
              child: PrimaryButton(
                label: context.tr('common.save'),
                onPressed: () {
                  final city = _city.text.trim();
                  Navigator.of(context).pop(
                    Location(
                      countryCode: _country,
                      city: city.isEmpty ? null : city,
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// "Baghdad, Iraq" style label.
String locationLabel(BuildContext context, Location? l) {
  if (l == null) return '—';
  final country = context.tr('country.${l.countryCode}');
  return (l.city == null || l.city!.isEmpty) ? country : '${l.city}, $country';
}
