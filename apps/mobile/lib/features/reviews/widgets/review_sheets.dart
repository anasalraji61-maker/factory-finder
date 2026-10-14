import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/reviews/reviews_models.dart';
import 'package:factory_finder/features/reviews/reviews_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

void showReviewSnack(BuildContext context, String message) {
  final messenger = ScaffoldMessenger.of(context);
  messenger.clearSnackBars();
  messenger.showSnackBar(SnackBar(content: Text(message)));
}

/// Opens the write/edit sheet. Returns the saved review, or null if dismissed.
Future<Review?> showWriteReviewSheet(
  BuildContext context, {
  required String dealId,
  String? supplierRef,
  Review? existing,
}) {
  return showModalBottomSheet<Review>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (ctx) => WriteReviewSheet(
      dealId: dealId,
      supplierRef: supplierRef,
      existing: existing,
    ),
  );
}

/// Tappable 1..5 star input. Tapping the current value again clears it when
/// [clearable].
class StarInput extends StatelessWidget {
  const StarInput({
    super.key,
    required this.value,
    required this.onChanged,
    this.size = 32,
    this.clearable = false,
    this.keyPrefix = 'star',
  });

  final int value;
  final ValueChanged<int> onChanged;
  final double size;
  final bool clearable;
  final String keyPrefix;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 1; i <= 5; i++)
          InkResponse(
            key: Key('${keyPrefix}_$i'),
            onTap: () => onChanged(clearable && value == i ? 0 : i),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 4),
              child: Icon(
                i <= value ? Icons.star_rounded : Icons.star_outline_rounded,
                size: size,
                color: AppColors.warning,
              ),
            ),
          ),
      ],
    );
  }
}

class WriteReviewSheet extends ConsumerStatefulWidget {
  const WriteReviewSheet({
    super.key,
    required this.dealId,
    this.supplierRef,
    this.existing,
  });

  final String dealId;
  final String? supplierRef;
  final Review? existing;

  @override
  ConsumerState<WriteReviewSheet> createState() => _WriteReviewSheetState();
}

class _WriteReviewSheetState extends ConsumerState<WriteReviewSheet> {
  late final TextEditingController _title;
  late final TextEditingController _text;
  int _rating = 0;
  SubRatings _sub = SubRatings.empty;
  ReviewValidation _v = const ReviewValidation();
  String? _errorKey;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    final e = widget.existing;
    _title = TextEditingController(text: e?.title ?? '');
    _text = TextEditingController(text: e?.text ?? '');
    _rating = e?.rating ?? 0;
    _sub = e?.subRatings ?? SubRatings.empty;
  }

  @override
  void dispose() {
    _title.dispose();
    _text.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy) return;
    final v = validateReview(rating: _rating, title: _title.text, text: _text.text);
    setState(() {
      _v = v;
      _errorKey = null;
    });
    if (!v.ok) return;
    setState(() => _busy = true);
    final draft = ReviewDraft(
      rating: _rating,
      title: _title.text,
      text: _text.text,
      subRatings: _sub,
    );
    final repo = ref.read(reviewsRepositoryProvider);
    try {
      final existing = widget.existing;
      final saved = existing == null
          ? await repo.create(widget.dealId, draft, supplierRef: widget.supplierRef)
          : await repo.update(existing.id, draft);
      if (!mounted) return;
      Navigator.of(context).pop(saved);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _errorKey = reviewErrorKey(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final editing = widget.existing != null;
    final theme = Theme.of(context);
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              context.tr(editing ? 'reviews.edit.title' : 'reviews.write.title'),
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              context.tr('reviews.overall'),
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: StarInput(
                keyPrefix: 'review_star',
                value: _rating,
                size: 36,
                onChanged: (n) => setState(() => _rating = n),
              ),
            ),
            if (_v.ratingKey != null)
              Text(
                context.tr(_v.ratingKey!),
                key: const Key('review_rating_error'),
                style: const TextStyle(color: AppColors.danger),
              ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              context.tr('reviews.optional_ratings'),
              style: const TextStyle(color: AppColors.textSecondary),
            ),
            for (final k in kSubRatingKeys)
              Row(
                children: [
                  Expanded(
                    child: Text(
                      context.tr('reviews.sub.$k'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  StarInput(
                    keyPrefix: 'review_sub_$k',
                    value: (_sub[k] ?? 0).round(),
                    size: 26,
                    clearable: true,
                    onChanged: (n) => setState(
                      () => _sub = _sub.withValue(k, n == 0 ? null : n.toDouble()),
                    ),
                  ),
                ],
              ),
            const SizedBox(height: AppSpacing.sm),
            TextField(
              key: const Key('review_title'),
              controller: _title,
              maxLength: kReviewTitleMax,
              textInputAction: TextInputAction.next,
              decoration: InputDecoration(
                labelText: context.tr('reviews.field.title'),
                errorText: _v.titleKey == null ? null : context.tr(_v.titleKey!),
                errorMaxLines: 2,
              ),
            ),
            TextField(
              key: const Key('review_text'),
              controller: _text,
              maxLength: kReviewTextMax,
              minLines: 3,
              maxLines: 6,
              decoration: InputDecoration(
                labelText: context.tr('reviews.field.text'),
                alignLabelWithHint: true,
                errorText: _v.textKey == null ? null : context.tr(_v.textKey!),
                errorMaxLines: 2,
              ),
            ),
            Text(
              context.tr('reviews.rules'),
              style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
            ),
            if (_errorKey != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(
                context.tr(_errorKey!),
                key: const Key('review_error'),
                style: const TextStyle(color: AppColors.danger),
              ),
            ],
            const SizedBox(height: AppSpacing.md),
            SizedBox(
              width: double.infinity,
              child: PrimaryButton(
                key: const Key('review_submit'),
                label: context.tr(editing ? 'reviews.save' : 'reviews.submit'),
                loading: _busy,
                onPressed: _busy ? null : _submit,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Returns true when the reply was posted.
Future<bool> showReplySheet(BuildContext context, {required String reviewId}) async {
  final ok = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (ctx) => ReplySheet(reviewId: reviewId),
  );
  return ok == true;
}

class ReplySheet extends ConsumerStatefulWidget {
  const ReplySheet({super.key, required this.reviewId});

  final String reviewId;

  @override
  ConsumerState<ReplySheet> createState() => _ReplySheetState();
}

class _ReplySheetState extends ConsumerState<ReplySheet> {
  final TextEditingController _text = TextEditingController();
  String? _errorKey;
  bool _busy = false;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (_busy) return;
    final err = validateReply(_text.text);
    if (err != null) {
      setState(() => _errorKey = err);
      return;
    }
    setState(() {
      _busy = true;
      _errorKey = null;
    });
    try {
      await ref.read(reviewsRepositoryProvider).reply(widget.reviewId, _text.text);
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _errorKey = reviewErrorKey(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              context.tr('reviews.reply.title'),
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: AppSpacing.md),
            TextField(
              key: const Key('reply_text'),
              controller: _text,
              maxLength: kReplyTextMax,
              minLines: 3,
              maxLines: 6,
              decoration: InputDecoration(
                hintText: context.tr('reviews.reply.hint'),
                errorText: _errorKey == null ? null : context.tr(_errorKey!),
                errorMaxLines: 3,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            SizedBox(
              width: double.infinity,
              child: PrimaryButton(
                key: const Key('reply_submit'),
                label: context.tr('reviews.reply.send'),
                loading: _busy,
                onPressed: _busy ? null : _send,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Asks for a reason and reports [reviewId]; shows the outcome in a snackbar.
Future<void> reportReviewFlow(
  BuildContext context,
  WidgetRef ref,
  String reviewId,
) async {
  final reason = await showDialog<String>(
    context: context,
    builder: (ctx) => SimpleDialog(
      title: Text(ctx.tr('reviews.report.title')),
      children: [
        for (final r in kReportReasons)
          SimpleDialogOption(
            key: Key('report_reason_$r'),
            onPressed: () => Navigator.of(ctx).pop(r),
            child: Text(ctx.tr('reviews.report.$r')),
          ),
      ],
    ),
  );
  if (reason == null || !context.mounted) return;
  String message;
  try {
    final res = await ref.read(reviewsRepositoryProvider).report(reviewId, reason: reason);
    if (!context.mounted) return;
    message = context.tr(res.alreadyReported ? 'reviews.report.already' : 'reviews.report.done');
  } catch (e) {
    if (!context.mounted) return;
    message = context.tr(reviewErrorKey(e));
  }
  showReviewSnack(context, message);
}

/// Confirms and deletes own review. Returns true when deleted.
Future<bool> deleteReviewFlow(
  BuildContext context,
  WidgetRef ref,
  Review review,
) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(ctx.tr('reviews.delete.title')),
      content: Text(ctx.tr('reviews.delete.msg')),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(ctx).pop(false),
          child: Text(ctx.tr('reviews.delete.keep')),
        ),
        FilledButton(
          key: const Key('review_delete_confirm'),
          onPressed: () => Navigator.of(ctx).pop(true),
          child: Text(ctx.tr('reviews.delete.confirm')),
        ),
      ],
    ),
  );
  if (ok != true || !context.mounted) return false;
  String message;
  var done = false;
  try {
    await ref.read(reviewsRepositoryProvider).delete(review.id);
    done = true;
    if (!context.mounted) return true;
    message = context.tr('reviews.deleted');
  } catch (e) {
    if (!context.mounted) return false;
    message = context.tr(reviewErrorKey(e));
  }
  showReviewSnack(context, message);
  return done;
}
