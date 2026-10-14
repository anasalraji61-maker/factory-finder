import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:factory_finder/core/utils/number_format.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:flutter/material.dart';

/// Localized country name; unknown codes are shown as-is, `*` as "any".
String freightCountryName(BuildContext context, String code) {
  if (code == '*') return context.tr('freight.any_country');
  final key = 'country.$code';
  final text = context.tr(key);
  return text == key ? code : text;
}

String freightModeName(BuildContext context, String mode) =>
    context.tr('freight.mode.$mode');

IconData freightModeIcon(String mode) {
  switch (mode) {
    case 'air':
      return Icons.flight_outlined;
    case 'rail':
      return Icons.train_outlined;
    case 'road':
      return Icons.local_shipping_outlined;
    default:
      return Icons.directions_boat_filled_outlined;
  }
}

/// Exact decimal amount + currency, always laid out left-to-right.
class FreightMoney extends StatelessWidget {
  const FreightMoney(this.amount, this.currency, {super.key, this.style});

  final String amount;
  final String currency;
  final TextStyle? style;

  /// "3,200.00 USD" (always 2 decimals; rounding is done on the string).
  static String format(String amount, String currency) =>
      '${formatDecimalString(amount, fractionDigits: 2)} $currency';

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.ltr,
      child: Text(
        localizeNumber(format(amount, currency), DigitStyleScope.of(context)),
        style: style ?? const TextStyle(fontWeight: FontWeight.w800),
      ),
    );
  }
}

class FreightChip extends StatelessWidget {
  const FreightChip(this.label, {super.key, this.color, this.icon});

  final String label;
  final Color? color;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final c = color ?? Theme.of(context).colorScheme.primary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: c.withOpacity(0.12),
        borderRadius: BorderRadius.circular(AppRadius.sm),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[Icon(icon, size: 14, color: c), const SizedBox(width: 4)],
          Flexible(
            child: Text(
              label,
              style: TextStyle(color: c, fontWeight: FontWeight.w700, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }
}

Color requestStatusColor(String status) {
  switch (status) {
    case 'open':
      return AppColors.success;
    case 'awarded':
      return AppColors.primary;
    case 'expired':
      return AppColors.warning;
    default:
      return const Color(0xFF64748B);
  }
}

Color quoteStatusColor(String status) {
  switch (status) {
    case 'accepted':
      return AppColors.success;
    case 'rejected':
      return AppColors.danger;
    case 'withdrawn':
      return const Color(0xFF64748B);
    default:
      return AppColors.primary;
  }
}

String formatDate(BuildContext context, DateTime? d) {
  if (d == null) return '';
  final l = d.toLocal();
  final text =
      '${l.year.toString().padLeft(4, '0')}-${l.month.toString().padLeft(2, '0')}-${l.day.toString().padLeft(2, '0')}';
  return localizeDigits(text, DigitStyleScope.of(context));
}

/// Origin › destination header row (flags + places).
class FreightRouteRow extends StatelessWidget {
  const FreightRouteRow({super.key, required this.request});

  final ShipmentRequest request;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        CountryFlag(countryCode: request.originCountry, size: 20),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            '${request.originPlace}  ›  ${request.destinationPlace}',
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontWeight: FontWeight.w800),
          ),
        ),
        const SizedBox(width: 6),
        CountryFlag(countryCode: request.destinationCountry, size: 20),
      ],
    );
  }
}

/// "18,000 kg · 58 m³" style quantity line (exact strings, trailing zeros trimmed).
String freightQuantityLine(BuildContext context, ShipmentRequest r) {
  String trim(String s) => s.contains('.')
      ? s.replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '')
      : s;
  final parts = <String>[
    if (r.weightKg != null) context.tr('freight.qty_kg', {'v': trim(r.weightKg!)}),
    if (r.volumeCbm != null) context.tr('freight.qty_cbm', {'v': trim(r.volumeCbm!)}),
    if (r.containerType != null)
      '${r.containerCount ?? 1}×${r.containerType}',
  ];
  return parts.join(' · ');
}

/// Compact request card used in the buyer list and the forwarder inbox.
class FreightRequestTile extends StatelessWidget {
  const FreightRequestTile({
    super.key,
    required this.request,
    required this.onTap,
    this.showQuoted = false,
  });

  final ShipmentRequest request;
  final VoidCallback onTap;
  final bool showQuoted;

  @override
  Widget build(BuildContext context) {
    final r = request;
    final theme = Theme.of(context);
    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          FreightRouteRow(request: r),
          const SizedBox(height: AppSpacing.sm),
          Text(
            r.cargoDescription,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.bodyMedium,
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              FreightChip(
                freightModeName(context, r.mode),
                icon: freightModeIcon(r.mode),
              ),
              FreightChip(r.incoterm, color: AppColors.accent),
              FreightChip(
                context.tr('freight.status.${r.status}'),
                color: requestStatusColor(r.status),
              ),
              if (showQuoted && r.hasQuoted)
                FreightChip(
                  context.tr('freight.quoted'),
                  color: AppColors.success,
                  icon: Icons.check_circle_outline,
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            [
              freightQuantityLine(context, r),
              context.tr('freight.quotes_count', {'n': '${r.quoteCount}'}),
            ].where((e) => e.isNotEmpty).join(' · '),
            style: theme.textTheme.bodySmall
                ?.copyWith(color: AppColors.secondaryOf(context)),
          ),
        ],
      ),
    );
  }
}

/// Key-value line that wraps instead of overflowing.
class FreightInfoLine extends StatelessWidget {
  const FreightInfoLine(this.label, this.value, {super.key});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Text.rich(
        TextSpan(
          children: [
            TextSpan(
              text: '$label: ',
              style: TextStyle(color: AppColors.secondaryOf(context)),
            ),
            TextSpan(text: value, style: const TextStyle(fontWeight: FontWeight.w700)),
          ],
        ),
        style: theme.textTheme.bodyMedium,
      ),
    );
  }
}

/// Error box shown inside forms and sheets.
class FreightErrorBox extends StatelessWidget {
  const FreightErrorBox(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.danger.withOpacity(0.10),
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(color: AppColors.danger.withOpacity(0.5)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.error_outline, color: AppColors.danger, size: 20),
          const SizedBox(width: AppSpacing.sm),
          Expanded(child: Text(message)),
        ],
      ),
    );
  }
}

/// Country picker (ISO list + optional wildcard). Shows the current value
/// even when it is not in the standard list.
class FreightCountryDropdown extends StatelessWidget {
  const FreightCountryDropdown({
    super.key,
    required this.label,
    required this.value,
    required this.onChanged,
    this.allowAny = false,
  });

  final String label;
  final String value;
  final ValueChanged<String> onChanged;
  final bool allowAny;

  @override
  Widget build(BuildContext context) {
    final codes = <String>[
      if (allowAny) '*',
      ...kFreightCountries,
      if (value != '*' && !kFreightCountries.contains(value) && value.isNotEmpty) value,
    ];
    return DropdownButtonFormField<String>(
      value: codes.contains(value) ? value : codes.first,
      isExpanded: true,
      decoration: InputDecoration(labelText: label),
      items: [
        for (final c in codes)
          DropdownMenuItem<String>(
            value: c,
            child: Text(freightCountryName(context, c), overflow: TextOverflow.ellipsis),
          ),
      ],
      onChanged: (v) {
        if (v != null) onChanged(v);
      },
    );
  }
}

/// Section title with an optional action that never overflows: the pair
/// wraps onto two lines when the action label does not fit (large text scale).
class FreightSectionHeader extends StatelessWidget {
  const FreightSectionHeader({super.key, required this.title, this.actionLabel, this.onAction});

  final String title;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final titleText = Text(
      title,
      style: Theme.of(context)
          .textTheme
          .titleMedium
          ?.copyWith(fontWeight: FontWeight.w800),
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: SizedBox(
        width: double.infinity,
        child: Wrap(
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            titleText,
            if (actionLabel != null) TextButton(onPressed: onAction, child: Text(actionLabel!)),
          ],
        ),
      ),
    );
  }
}
