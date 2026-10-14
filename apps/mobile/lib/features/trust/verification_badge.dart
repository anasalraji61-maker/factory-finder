import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/trust/verification_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

Color _levelColor(String level) {
  switch (level) {
    case 'audited':
      return AppColors.accent;
    case 'documented':
      return AppColors.success;
    default:
      return AppColors.primary;
  }
}

/// Pill for a verification [level] (basic / documented / audited). Renders
/// nothing for `none` or unknown levels.
class VerificationLevelChip extends StatelessWidget {
  const VerificationLevelChip({super.key, required this.level});

  final String level;

  @override
  Widget build(BuildContext context) {
    if (level != 'basic' && level != 'documented' && level != 'audited') {
      return const SizedBox.shrink();
    }
    final color = _levelColor(level);
    final label = context.tr('ver.badge.$level');
    return Semantics(
      label: label,
      excludeSemantics: true,
      child: Container(
        key: ValueKey<String>('ver-badge-$level'),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: color.withOpacity(0.12),
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.domain_verification, size: 16, color: color),
            const SizedBox(width: 4),
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 13),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Public verification badge of [supplierId] (GET /v1/trust/suppliers/{id}/verification).
/// Collapses to nothing while loading, when the level is `none`, and when the
/// endpoint is absent or failing.
class SupplierVerificationBadge extends ConsumerWidget {
  const SupplierVerificationBadge({super.key, required this.supplierId});

  final String supplierId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final v = ref.watch(supplierVerificationProvider(supplierId)).valueOrNull;
    if (v == null || !v.isVerified) return const SizedBox.shrink();
    return VerificationLevelChip(level: v.level);
  }
}
