import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/reviews/reviews_models.dart';
import 'package:factory_finder/features/reviews/reviews_repository.dart';
import 'package:factory_finder/features/reviews/widgets/review_sheets.dart';
import 'package:factory_finder/features/reviews/widgets/review_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// "Rate the supplier" block under an accepted deal: write, edit or delete
/// the buyer's review.
class DealReviewSection extends ConsumerWidget {
  const DealReviewSection({super.key, required this.deal, this.supplierRef});

  final Deal deal;

  /// Supplier of the accepted offer; lets the section find an existing review.
  final String? supplierRef;

  void _refresh(WidgetRef ref) {
    final ref0 = supplierRef;
    if (ref0 != null) {
      ref.invalidate(myReviewProvider(ref0));
      ref.invalidate(reviewSummaryProvider(ref0));
    }
  }

  Future<void> _write(BuildContext context, WidgetRef ref, Review? existing) async {
    final saved = await showWriteReviewSheet(
      context,
      dealId: deal.id,
      supplierRef: supplierRef,
      existing: existing,
    );
    if (saved == null || !context.mounted) return;
    _refresh(ref);
    showReviewSnack(
      context,
      context.tr(existing == null ? 'reviews.posted' : 'reviews.updated'),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ref0 = supplierRef;
    final AsyncValue<Review?> mine =
        ref0 == null ? const AsyncValue<Review?>.data(null) : ref.watch(myReviewProvider(ref0));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: context.tr('reviews.section.title')),
        mine.when(
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpacing.lg),
            child: Center(child: CircularProgressIndicator()),
          ),
          error: (e, _) => ErrorState(
            message: context.tr(reviewErrorKey(e)),
            onRetry: () => _refresh(ref),
          ),
          data: (review) {
            if (review == null) {
              return SizedBox(
                width: double.infinity,
                child: PrimaryButton(
                  key: const Key('write_review_button'),
                  label: context.tr('reviews.write'),
                  icon: Icons.rate_review_outlined,
                  onPressed: () => _write(context, ref, null),
                ),
              );
            }
            final editable = review.isEditable(DateTime.now().toUtc());
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ReviewTile(
                  key: Key('my_review_${review.id}'),
                  review: review,
                  onEdit: editable ? () => _write(context, ref, review) : null,
                  onDelete: editable
                      ? () async {
                          final done = await deleteReviewFlow(context, ref, review);
                          if (done && context.mounted) _refresh(ref);
                        }
                      : null,
                ),
                if (!editable)
                  Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.sm),
                    child: Text(
                      context.tr('reviews.window_closed'),
                      style: const TextStyle(color: AppColors.textSecondary),
                    ),
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}
