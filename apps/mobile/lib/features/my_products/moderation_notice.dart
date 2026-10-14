import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:flutter/material.dart';

/// Banner explaining why an owner's listing is `pending_review` or `hidden`.
/// Renders nothing for other statuses. [compact] drops the long explanation
/// (used inside list cards).
class ModerationNotice extends StatelessWidget {
  const ModerationNotice({super.key, required this.listing, this.compact = false});

  final OwnedListing listing;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final l = listing;
    if (!l.isModerated) return const SizedBox.shrink();
    final hidden = l.status == ListingStatus.hidden;
    final color = hidden ? AppColors.danger : AppColors.warning;
    final prefix = hidden ? 'myp.mod.hidden' : 'myp.mod.pending';
    final reason = l.moderationReason;
    final src = l.moderationSource;
    final source = (src == 'auto' || src == 'report' || src == 'admin') ? src : null;
    final style = Theme.of(context).textTheme.bodySmall;
    return Container(
      key: ValueKey('myp-mod-${l.id}'),
      width: double.infinity,
      margin: const EdgeInsets.only(top: AppSpacing.sm),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: color.withOpacity(0.10),
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(color: color.withOpacity(0.4)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(hidden ? Icons.block : Icons.gavel_outlined, size: 20, color: color),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  context.tr('${prefix}_title'),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                if (!compact) ...[
                  const SizedBox(height: 2),
                  Text(context.tr('${prefix}_msg'), style: style),
                ],
                if (reason != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    context.tr('myp.mod.reason', {'reason': reason}),
                    key: ValueKey('myp-mod-reason-${l.id}'),
                    maxLines: compact ? 3 : 8,
                    overflow: TextOverflow.ellipsis,
                    style: style,
                  ),
                ],
                if (!compact && source != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    context.tr('myp.mod.source', {
                      'source': context.tr('myp.mod.source.$source'),
                    }),
                    style: style,
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
