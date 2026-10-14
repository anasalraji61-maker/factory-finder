import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:flutter/material.dart';

/// Collapsible "what if" block with the optional cost sensitivity bands.
/// Renders nothing when the server sent no (or an empty) sensitivity.
class SensitivitySection extends StatelessWidget {
  const SensitivitySection({super.key, required this.sensitivity});

  final CostSensitivity? sensitivity;

  @override
  Widget build(BuildContext context) {
    final s = sensitivity;
    if (s == null || s.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final rows = <(String, MoneyBand)>[
      if (s.freight != null) ('logistics.whatif.freight', s.freight!),
      if (s.fx != null) ('logistics.whatif.fx', s.fx!),
      if (s.combined != null) ('logistics.whatif.combined', s.combined!),
    ];
    return Theme(
      data: theme.copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        key: const ValueKey('whatif_tile'),
        title: Text(
          context.tr('logistics.whatif.title'),
          style: const TextStyle(fontWeight: FontWeight.w800),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.tr('logistics.whatif.intro'),
            style: theme.textTheme.bodySmall
                ?.copyWith(color: AppColors.textSecondary, height: 1.4),
          ),
          const SizedBox(height: AppSpacing.sm),
          for (final r in rows) _BandRow(labelKey: r.$1, band: r.$2),
          if (s.note != null && s.note!.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.xs),
              child: Text(
                s.note!,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: AppColors.textSecondary, height: 1.4),
              ),
            ),
        ],
      ),
    );
  }
}

class _BandRow extends StatelessWidget {
  const _BandRow({required this.labelKey, required this.band});

  final String labelKey;
  final MoneyBand band;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final shock = band.shockPct;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Flexible(
                child: Text(
                  context.tr(labelKey),
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              if (shock != null && shock.isNotEmpty) ...[
                const SizedBox(width: 6),
                Text(
                  context.tr('logistics.whatif.shock', {'p': shock}),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ],
          ),
          Text(
            context.tr('logistics.whatif.range', {
              'low': band.low.format(),
              'high': band.high.format(),
            }),
            style: TextStyle(
              fontWeight: FontWeight.w800,
              color: theme.colorScheme.primary,
            ),
          ),
          Text(
            context.tr('logistics.whatif.base', {'base': band.base.format()}),
            style: theme.textTheme.bodySmall
                ?.copyWith(color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }
}
