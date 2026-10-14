import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/reviews/reviews_models.dart';
import 'package:factory_finder/features/reviews/reviews_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// yyyy-MM-dd of a date (local), empty for null.
String reviewDate(DateTime? d) {
  if (d == null) return '';
  final l = d.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${l.year}-${two(l.month)}-${two(l.day)}';
}

/// Read-only row of five stars (supports halves).
class StarRow extends StatelessWidget {
  const StarRow({super.key, required this.value, this.size = 16});

  final double value;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 1; i <= 5; i++)
          Icon(
            value >= i - 0.25
                ? Icons.star_rounded
                : (value >= i - 0.75 ? Icons.star_half_rounded : Icons.star_outline_rounded),
            size: size,
            color: AppColors.warning,
          ),
      ],
    );
  }
}

/// Rating overview on the supplier screen: average, histogram, sub-ratings.
class RatingSummaryCard extends ConsumerWidget {
  const RatingSummaryCard({super.key, required this.supplierRef});

  final String supplierRef;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(reviewSummaryProvider(supplierRef));
    return async.when(
      loading: () => const SizedBox.shrink(),
      error: (e, _) => const SizedBox.shrink(),
      data: (s) => ReviewSummaryView(summary: s, onSeeAll: () {
        context.push('/supplier-reviews/${Uri.encodeComponent(supplierRef)}');
      }),
    );
  }
}

class ReviewSummaryView extends StatelessWidget {
  const ReviewSummaryView({super.key, required this.summary, this.onSeeAll});

  final ReviewSummary summary;
  final VoidCallback? onSeeAll;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = summary;
    final avg = s.displayAverage;
    return AppCard(
      key: const Key('rating_summary_card'),
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.tr('reviews.summary.title'),
            style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: AppSpacing.md),
          if (!s.hasReviews)
            Text(
              context.tr('reviews.summary.none'),
              style: const TextStyle(color: AppColors.textSecondary),
            )
          else ...[
            Builder(builder: (context) {
              final big = MediaQuery.textScalerOf(context).scale(14) / 14 > 1.3;
              final summaryCol = Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    avg == null ? '-' : avg.toStringAsFixed(1),
                    key: const Key('rating_average'),
                    style: theme.textTheme.displaySmall?.copyWith(fontWeight: FontWeight.w900),
                  ),
                  StarRow(value: avg ?? 0, size: 16),
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    context.tr('reviews.summary.count', {'n': '${s.count}'}),
                    style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
                  ),
                ],
              );
              if (big) {
                // Large text: stack instead of side by side.
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    summaryCol,
                    const SizedBox(height: AppSpacing.md),
                    _Histogram(histogram: s.histogram),
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Flexible(child: summaryCol),
                  const SizedBox(width: AppSpacing.lg),
                  Expanded(child: _Histogram(histogram: s.histogram)),
                ],
              );
            }),
            if (!s.subRatings.isEmpty) ...[
              const SizedBox(height: AppSpacing.md),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: [
                  for (final k in kSubRatingKeys)
                    if (s.subRatings[k] != null)
                      Chip(
                        key: Key('sub_chip_$k'),
                        visualDensity: VisualDensity.compact,
                        avatar: const Icon(Icons.star_rounded, size: 16, color: AppColors.warning),
                        label: Text(
                          '${context.tr('reviews.sub.$k')} ${s.subRatings[k]!.toStringAsFixed(1)}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                ],
              ),
            ],
          ],
          if (s.completedDeals > 0) ...[
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                const Icon(Icons.task_alt_outlined, size: 18, color: AppColors.textSecondary),
                const SizedBox(width: AppSpacing.xs),
                Flexible(
                  child: Text(
                    context.tr('reviews.summary.deals', {'n': '${s.completedDeals}'}),
                    key: const Key('rating_completed_deals'),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: AppColors.textSecondary),
                  ),
                ),
              ],
            ),
          ],
          if (onSeeAll != null && s.hasReviews)
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: TextButton(
                key: const Key('see_all_reviews'),
                onPressed: onSeeAll,
                child: Text(context.tr('reviews.see_all')),
              ),
            ),
        ],
      ),
    );
  }
}

class _Histogram extends StatelessWidget {
  const _Histogram({required this.histogram});

  final Map<int, int> histogram;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var star = 5; star >= 1; star--)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Row(
              children: [
                SizedBox(
                  width: 14,
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: AlignmentDirectional.centerStart,
                    child: Text('$star', style: const TextStyle(fontSize: 12)),
                  ),
                ),
                const Icon(Icons.star_rounded, size: 12, color: AppColors.warning),
                const SizedBox(width: AppSpacing.xs),
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: LinearProgressIndicator(
                      key: Key('hist_bar_$star'),
                      minHeight: 8,
                      value: histogramShare(histogram, star),
                      color: AppColors.warning,
                      backgroundColor: AppColors.border,
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.xs),
                SizedBox(
                  width: 28,
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: AlignmentDirectional.centerEnd,
                    child: Text(
                      '${histogram[star] ?? 0}',
                      maxLines: 1,
                      textAlign: TextAlign.end,
                      style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

enum ReviewMenuAction { report, edit, delete }

/// One review: stars, text, badges, nested supplier reply and actions.
class ReviewTile extends StatelessWidget {
  const ReviewTile({
    super.key,
    required this.review,
    this.onReport,
    this.onReply,
    this.onEdit,
    this.onDelete,
  });

  final Review review;
  final VoidCallback? onReport;
  final VoidCallback? onReply;
  final VoidCallback? onEdit;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final r = review;
    final hasMenu = onReport != null || onEdit != null || onDelete != null;
    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StarRow(value: r.rating.toDouble()),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  r.mine ? context.tr('reviews.mine') : r.reviewer,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              if (hasMenu)
                PopupMenuButton<ReviewMenuAction>(
                  key: Key('review_menu_${r.id}'),
                  padding: EdgeInsets.zero,
                  onSelected: (a) {
                    switch (a) {
                      case ReviewMenuAction.report:
                        onReport?.call();
                      case ReviewMenuAction.edit:
                        onEdit?.call();
                      case ReviewMenuAction.delete:
                        onDelete?.call();
                    }
                  },
                  itemBuilder: (ctx) => <PopupMenuEntry<ReviewMenuAction>>[
                    if (onReport != null)
                      PopupMenuItem<ReviewMenuAction>(
                        key: const Key('menu_report'),
                        value: ReviewMenuAction.report,
                        child: Text(ctx.tr('reviews.menu.report')),
                      ),
                    if (onEdit != null)
                      PopupMenuItem<ReviewMenuAction>(
                        key: const Key('menu_edit'),
                        value: ReviewMenuAction.edit,
                        child: Text(ctx.tr('reviews.edit')),
                      ),
                    if (onDelete != null)
                      PopupMenuItem<ReviewMenuAction>(
                        key: const Key('menu_delete'),
                        value: ReviewMenuAction.delete,
                        child: Text(ctx.tr('reviews.delete')),
                      ),
                  ],
                ),
            ],
          ),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: 2,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              if (r.createdAt != null)
                Text(
                  reviewDate(r.createdAt),
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
                ),
              if (r.verifiedPurchase)
                _Badge(
                  icon: Icons.verified_outlined,
                  label: context.tr('reviews.verified'),
                  color: AppColors.success,
                ),
              if (r.edited)
                _Badge(
                  key: Key('edited_badge_${r.id}'),
                  icon: Icons.edit_outlined,
                  label: context.tr('reviews.edited'),
                  color: AppColors.textSecondary,
                ),
              if (r.mine && r.flaggedForReview)
                _Badge(
                  icon: Icons.flag_outlined,
                  label: context.tr('reviews.flagged'),
                  color: AppColors.warning,
                ),
            ],
          ),
          if (r.title.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(r.title, style: const TextStyle(fontWeight: FontWeight.w800)),
          ],
          if (r.text.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.xs),
            Text(r.text),
          ],
          if (!r.subRatings.isEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.md,
              runSpacing: 2,
              children: [
                for (final k in kSubRatingKeys)
                  if (r.subRatings[k] != null)
                    Text(
                      '${context.tr('reviews.sub.$k')}: ${r.subRatings[k]!.round()}/5',
                      style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
                    ),
              ],
            ),
          ],
          if (r.reply != null) ...[
            const SizedBox(height: AppSpacing.sm),
            Container(
              key: Key('review_reply_${r.id}'),
              width: double.infinity,
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.primary.withOpacity(0.06),
                borderRadius: BorderRadius.circular(AppRadius.sm),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    context.tr('reviews.reply.label'),
                    style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 12),
                  ),
                  const SizedBox(height: 2),
                  Text(r.reply!.text),
                ],
              ),
            ),
          ],
          if (onReply != null && r.reply == null)
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: TextButton.icon(
                key: Key('review_reply_btn_${r.id}'),
                onPressed: onReply,
                icon: const Icon(Icons.reply_rounded, size: 18),
                label: Text(context.tr('reviews.reply.action')),
              ),
            ),
        ],
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({super.key, required this.icon, required this.label, required this.color});

  final IconData icon;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: color),
        const SizedBox(width: 2),
        Flexible(
          child: Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 12, color: color),
          ),
        ),
      ],
    );
  }
}
