import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:flutter/material.dart';

Color trustColor(TrustBand band) {
  switch (band) {
    case TrustBand.green:
      return AppColors.success;
    case TrustBand.yellow:
      return AppColors.warning;
    case TrustBand.red:
      return AppColors.danger;
    case TrustBand.unknown:
      return AppColors.textSecondary;
  }
}

class TrustBadge extends StatelessWidget {
  const TrustBadge({
    super.key,
    required this.band,
    this.score,
    this.compact = false,
  });

  final TrustBand band;
  final int? score;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final color = trustColor(band);
    final label = context.tr('trust.${band.json}');
    final scoreText = score == null ? '' : '$score';
    return Semantics(
      label: '$label $scoreText'.trim(),
      excludeSemantics: true,
      child: Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 6 : 10,
        vertical: compact ? 2 : 5,
      ),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            band == TrustBand.unknown
                ? Icons.help_outline
                : Icons.verified_user_rounded,
            size: compact ? 12 : 16,
            color: color,
          ),
          const SizedBox(width: 4),
          Flexible(
            child: Text(
            compact ? (scoreText.isEmpty ? label : scoreText) : '$label $scoreText'.trim(),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              color: color,
              fontWeight: FontWeight.w700,
              fontSize: compact ? 11 : 13,
            ),
          ),
          ),
        ],
      ),
    ),
    );
  }
}
