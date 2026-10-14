import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/reviews/reviews_models.dart';
import 'package:factory_finder/features/reviews/reviews_repository.dart';
import 'package:factory_finder/features/reviews/widgets/review_sheets.dart';
import 'package:factory_finder/features/reviews/widgets/review_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

const int kReviewsPageSize = 10;

/// All reviews of one supplier: sort toggle, load more, pull-to-refresh.
class ReviewsListScreen extends ConsumerStatefulWidget {
  const ReviewsListScreen({super.key, required this.supplierRef});

  final String supplierRef;

  @override
  ConsumerState<ReviewsListScreen> createState() => _ReviewsListScreenState();
}

class _ReviewsListScreenState extends ConsumerState<ReviewsListScreen> {
  ReviewSort _sort = ReviewSort.recent;
  final List<Review> _items = <Review>[];
  int _total = 0;
  int _page = 0;
  bool _loading = true;
  bool _loadingMore = false;
  Object? _error;
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    final gen = ++_generation;
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final page = await ref.read(reviewsRepositoryProvider).list(
            widget.supplierRef,
            page: 1,
            pageSize: kReviewsPageSize,
            sort: _sort,
          );
      if (!mounted || gen != _generation) return;
      setState(() {
        _items
          ..clear()
          ..addAll(page.items);
        _total = page.total;
        _page = 1;
        _loading = false;
      });
    } catch (e) {
      if (!mounted || gen != _generation) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || _loading) return;
    final gen = _generation;
    setState(() => _loadingMore = true);
    try {
      final page = await ref.read(reviewsRepositoryProvider).list(
            widget.supplierRef,
            page: _page + 1,
            pageSize: kReviewsPageSize,
            sort: _sort,
          );
      if (!mounted || gen != _generation) return;
      setState(() {
        _items.addAll(page.items);
        _total = page.total;
        _page += 1;
        _loadingMore = false;
      });
    } catch (e) {
      if (!mounted || gen != _generation) return;
      setState(() => _loadingMore = false);
      showReviewSnack(context, context.tr(reviewErrorKey(e)));
    }
  }

  void _setSort(ReviewSort s) {
    if (s == _sort) return;
    setState(() => _sort = s);
    _reload();
  }

  Future<void> _refreshAll() async {
    ref.invalidate(reviewSummaryProvider(widget.supplierRef));
    await _reload();
  }

  Future<void> _reply(Review r) async {
    final ok = await showReplySheet(context, reviewId: r.id);
    if (!ok || !mounted) return;
    showReviewSnack(context, context.tr('reviews.reply.sent'));
    await _reload();
  }

  @override
  Widget build(BuildContext context) {
    final me = ref.watch(authProvider);
    final isOwner = me?.supplierId != null && me?.supplierId == widget.supplierRef;
    final summary = ref.watch(reviewSummaryProvider(widget.supplierRef));
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('reviews.title'))),
      body: RefreshIndicator(
        onRefresh: _refreshAll,
        child: _buildBody(context, isOwner, summary),
      ),
    );
  }

  Widget _buildBody(BuildContext context, bool isOwner, AsyncValue<ReviewSummary> summary) {
    if (_loading && _items.isEmpty) {
      return ListView(children: const [LoadingList(itemCount: 4)]);
    }
    if (_error != null && _items.isEmpty) {
      return ListView(
        children: [
          ErrorState(
            message: context.tr(reviewErrorKey(_error!)),
            onRetry: _reload,
          ),
        ],
      );
    }
    final hasMore = _items.length < _total;
    // index 0: header (summary + sort); then reviews; then footer.
    final count = _items.length + 2;
    return ListView.builder(
      key: const Key('reviews_list'),
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(AppSpacing.lg),
      itemCount: count,
      itemBuilder: (ctx, i) {
        if (i == 0) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (summary.valueOrNull != null)
                ReviewSummaryView(summary: summary.valueOrNull!),
              const SizedBox(height: AppSpacing.md),
              SegmentedButton<ReviewSort>(
                key: const Key('reviews_sort'),
                showSelectedIcon: false,
                segments: [
                  ButtonSegment<ReviewSort>(
                    value: ReviewSort.recent,
                    label: Text(
                      ctx.tr('reviews.sort.recent'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  ButtonSegment<ReviewSort>(
                    value: ReviewSort.rating,
                    label: Text(
                      ctx.tr('reviews.sort.rating'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
                selected: <ReviewSort>{_sort},
                onSelectionChanged: (s) => _setSort(s.first),
              ),
              const SizedBox(height: AppSpacing.md),
              if (_items.isEmpty)
                EmptyState(
                  icon: Icons.rate_review_outlined,
                  title: ctx.tr('reviews.empty'),
                ),
            ],
          );
        }
        if (i == count - 1) {
          if (!hasMore) return const SizedBox(height: AppSpacing.xl);
          return Padding(
            padding: const EdgeInsets.only(top: AppSpacing.sm),
            child: _loadingMore
                ? const Center(child: CircularProgressIndicator())
                : OutlinedButton(
                    key: const Key('reviews_load_more'),
                    onPressed: _loadMore,
                    child: Text(ctx.tr('reviews.load_more')),
                  ),
          );
        }
        final r = _items[i - 1];
        return Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.md),
          child: ReviewTile(
            key: Key('review_${r.id}'),
            review: r,
            onReport: r.mine ? null : () => reportReviewFlow(ctx, ref, r.id),
            onReply: isOwner && r.reply == null ? () => _reply(r) : null,
          ),
        );
      },
    );
  }
}
