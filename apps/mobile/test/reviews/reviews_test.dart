import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/reviews/reviews_models.dart';
import 'package:factory_finder/features/reviews/reviews_repository.dart';
import 'package:factory_finder/features/reviews/reviews_strings.dart';
import 'package:factory_finder/features/reviews/widgets/review_sheets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

class _Adapter implements HttpClientAdapter {
  _Adapter(this.body, [this.status = 200]);

  final Object body;
  final int status;
  final List<RequestOptions> calls = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

ApiClient _client(_Adapter a) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
  dio.httpClientAdapter = a;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

class _FakeRepo implements ReviewsRepository {
  final List<ReviewDraft> drafts = <ReviewDraft>[];
  int calls = 0;

  @override
  Future<Review> create(String dealId, ReviewDraft draft, {String? supplierRef}) async {
    calls++;
    drafts.add(draft);
    if (calls == 1) {
      throw ApiException(
        status: 409,
        code: 'review_already_exists',
        message: 'exists',
      );
    }
    return Review(id: 'rev_1', supplierRef: 'sup_x', rating: draft.rating, mine: true);
  }

  @override
  Future<void> delete(String reviewId) async {}

  @override
  Future<ReviewsPage> list(String supplierRef,
          {int page = 1, int pageSize = 20, ReviewSort sort = ReviewSort.recent}) async =>
      const ReviewsPage();

  @override
  Future<ReviewReply> reply(String reviewId, String text) async =>
      ReviewReply(text: text);

  @override
  Future<ReviewReportResult> report(String reviewId,
          {String? reason, String? note}) async =>
      ReviewReportResult(id: reviewId);

  @override
  Future<ReviewSummary> summary(String supplierRef) async =>
      ReviewSummary(supplierRef: supplierRef);

  @override
  Future<Review> update(String reviewId, ReviewDraft draft) async =>
      Review(id: reviewId, supplierRef: 'sup_x', rating: draft.rating);
}

void main() {
  setUpWidgetTests();

  group('parsing', () {
    test('summary fixture', () {
      final s = ReviewSummary.fromJson(_load('review_summary'));
      expect(s.supplierRef, 'sup_cn_018');
      expect(s.count, 7);
      expect(s.average, closeTo(3.71, 0.0001));
      expect(s.histogram[5], 3);
      expect(s.histogram[1], 0);
      expect(s.subRatings.quality, 4.5);
      expect(s.subRatings.shipping, isNull);
      expect(s.completedDeals, 12);
      expect(s.hasReviews, isTrue);
    });

    test('summary tolerates empty / odd input', () {
      final s = ReviewSummary.fromJson({
        'supplier_ref': 'x',
        'count': 0,
        'average': null,
        'histogram': {'1': 0, 'zz': 4, '9': 2},
      });
      expect(s.hasReviews, isFalse);
      expect(s.displayAverage, isNull);
      expect(s.histogram.containsKey(9), isFalse);
      expect(ReviewSummary.fromJson('nope').count, 0);
    });

    test('reviews page fixture', () {
      final p = ReviewsPage.fromJson(_load('reviews'));
      expect(p.total, 7);
      expect(p.pageSize, 10);
      expect(p.items, hasLength(2));
      final a = p.items.first;
      expect(a.reviewer, 'Ahmed K.');
      expect(a.reply?.text, 'Thank you for your trust.');
      expect(a.reply?.createdAt, DateTime.utc(2026, 9, 20, 10));
      expect(a.mine, isFalse);
      expect(a.editableUntil, isNull);
      expect(a.subRatings.quality, 5);
      final b = p.items[1];
      expect(b.mine, isTrue);
      expect(b.edited, isTrue);
      expect(b.reply, isNull);
      expect(b.subRatings.isEmpty, isTrue);
      expect(b.isEditable(DateTime.utc(2026, 9, 29)), isTrue);
      expect(b.isEditable(DateTime.utc(2026, 10, 1)), isFalse);
      expect(a.isEditable(DateTime.utc(2026, 9, 1)), isFalse);
    });

    test('report result fixture', () {
      final r = ReviewReportResult.fromJson(_load('review_report'));
      expect(r.id, 'rev_a1b2c3');
      expect(r.alreadyReported, isFalse);
    });
  });

  group('histogram math', () {
    const h = {1: 0, 2: 1, 3: 1, 4: 2, 5: 3};
    test('total, share and average', () {
      expect(histogramTotal(h), 7);
      expect(histogramShare(h, 5), closeTo(3 / 7, 1e-9));
      expect(histogramShare(h, 1), 0);
      expect(histogramShare(const <int, int>{}, 3), 0);
      expect(averageFromHistogram(h), closeTo(26 / 7, 1e-9));
      expect(averageFromHistogram(const <int, int>{}), isNull);
    });
  });

  group('validation', () {
    test('prohibited content', () {
      expect(findProhibited('see https://x.example/a'), ProhibitedKind.url);
      expect(findProhibited('go to www.shop.cn'), ProhibitedKind.url);
      expect(findProhibited('mail me a.b@c.com'), ProhibitedKind.email);
      expect(findProhibited('call +964 770 123 4567'), ProhibitedKind.phone);
      expect(findProhibited('0770-123-4567'), ProhibitedKind.phone);
      expect(findProhibited('Great quality, 500 pcs, arrived in 20 days'), isNull);
    });

    test('review validation', () {
      expect(validateReview(rating: 0, title: '', text: '').ratingKey, 'reviews.err.rating');
      expect(validateReview(rating: 6, title: '', text: '').ok, isFalse);
      expect(validateReview(rating: 5, title: '', text: '').ok, isTrue);
      expect(
        validateReview(rating: 5, title: 'x' * 81, text: '').titleKey,
        'reviews.err.text_too_long',
      );
      expect(
        validateReview(rating: 5, title: '', text: 'y' * 1001).textKey,
        'reviews.err.text_too_long',
      );
      expect(
        validateReview(rating: 5, title: 'a@b.co', text: 'ok').titleKey,
        'reviews.err.prohibited.email',
      );
      expect(validateReply('  '), 'reviews.err.reply_empty');
      expect(validateReply('z' * 501), 'reviews.err.text_too_long');
      expect(validateReply('Thanks'), isNull);
    });

    test('draft body omits empty fields', () {
      final d = ReviewDraft(
        rating: 4,
        title: ' ',
        text: ' hi ',
        subRatings: const SubRatings(quality: 5, shipping: 3),
      );
      expect(d.toJson(), {
        'rating': 4,
        'text': 'hi',
        'sub_ratings': {'quality': 5, 'shipping': 3},
      });
      expect(const ReviewDraft(rating: 2).toJson(), {'rating': 2});
    });
  });

  group('error mapping', () {
    String key(int status, String code) => reviewErrorKey(
          ApiException(status: status, code: code, message: ''),
        );

    test('known codes', () {
      for (final c in [
        'deal_not_reviewable',
        'review_already_exists',
        'supplier_unverified',
        'review_window_closed',
        'reply_already_exists',
      ]) {
        expect(key(409, c), 'reviews.err.$c');
      }
      expect(key(422, 'prohibited_content'), 'reviews.err.prohibited');
      expect(key(422, 'text_too_long'), 'reviews.err.text_too_long');
      expect(key(429, 'rate_limited'), 'reviews.err.rate_limited');
    });

    test('status fallbacks', () {
      expect(key(401, 'http_401'), 'reviews.err.auth');
      expect(key(403, 'http_403'), 'reviews.err.forbidden');
      expect(key(404, 'http_404'), 'reviews.err.not_found');
      expect(key(409, 'other'), 'reviews.err.conflict');
      expect(key(422, 'http_422'), 'reviews.err.validation_error');
      expect(key(429, 'http_429'), 'reviews.err.rate_limited');
      expect(key(500, 'http_500'), 'reviews.err.generic');
      expect(reviewErrorKey(ApiException(code: 'timeout', message: '')), 'reviews.err.network');
      expect(reviewErrorKey(StateError('x')), 'reviews.err.generic');
    });

    test('every key exists in both languages', () {
      final keys = <String>{
        for (final c in [
          'deal_not_reviewable', 'review_already_exists', 'supplier_unverified',
          'review_window_closed', 'reply_already_exists', 'text_too_long',
          'rate_limited', 'validation_error',
        ])
          'reviews.err.$c',
        'reviews.err.prohibited', 'reviews.err.conflict', 'reviews.err.auth',
        'reviews.err.forbidden', 'reviews.err.not_found', 'reviews.err.network',
        'reviews.err.generic', 'reviews.err.rating', 'reviews.err.reply_empty',
        'reviews.err.prohibited.url', 'reviews.err.prohibited.email',
        'reviews.err.prohibited.phone',
      };
      for (final k in keys) {
        expect(reviewsStrings['ar']!.containsKey(k), isTrue, reason: k);
        expect(reviewsStrings['en']!.containsKey(k), isTrue, reason: k);
      }
    });
  });

  group('repositories', () {
    test('live list sends query and parses', () async {
      final a = _Adapter(_load('reviews'));
      final repo = LiveReviewsRepository(_client(a));
      final page = await repo.list('sup_cn_018', page: 2, pageSize: 500, sort: ReviewSort.rating);
      expect(page.items, hasLength(2));
      expect(a.calls.single.path, '/v1/suppliers/sup_cn_018/reviews');
      expect(a.calls.single.queryParameters['page'], 2);
      expect(a.calls.single.queryParameters['page_size'], 100);
      expect(a.calls.single.queryParameters['sort'], 'rating');
    });

    test('live create maps error body', () async {
      final a = _Adapter(_load('error_review_exists'), 409);
      final repo = LiveReviewsRepository(_client(a));
      try {
        await repo.create('deal_1', const ReviewDraft(rating: 5));
        fail('should throw');
      } on ApiException catch (e) {
        expect(e.code, 'review_already_exists');
        expect(reviewErrorKey(e), 'reviews.err.review_already_exists');
      }
      expect(a.calls.single.method, 'POST');
      expect(a.calls.single.path, '/v1/deals/deal_1/reviews');
    });

    test('mock: paging, sort, create, duplicate, edit window, delete', () async {
      var now = DateTime.utc(2026, 10, 1);
      final repo = MockReviewsRepository(clock: () => now);
      final p1 = await repo.list('sup_a', page: 1, pageSize: 3);
      final p3 = await repo.list('sup_a', page: 3, pageSize: 3);
      expect(p1.items, hasLength(3));
      expect(p1.total, 7);
      expect(p3.items, hasLength(1));
      final byRating = await repo.list('sup_a', pageSize: 100, sort: ReviewSort.rating);
      expect(byRating.items.first.rating, 5);
      expect(byRating.items.last.rating, 2);

      final before = await repo.summary('sup_a');
      final r = await repo.create('deal_1', const ReviewDraft(rating: 1, text: 'bad'), supplierRef: 'sup_a');
      expect(r.mine, isTrue);
      final after = await repo.summary('sup_a');
      expect(after.count, before.count + 1);
      expect(after.histogram[1], (before.histogram[1] ?? 0) + 1);

      await expectLater(
        repo.create('deal_1', const ReviewDraft(rating: 3), supplierRef: 'sup_a'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'review_already_exists')),
      );
      await expectLater(
        repo.create('deal_2', const ReviewDraft(rating: 3, text: 'visit www.x.com'), supplierRef: 'sup_a'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'prohibited_content')),
      );

      final edited = await repo.update(r.id, const ReviewDraft(rating: 2));
      expect(edited.edited, isTrue);
      now = now.add(const Duration(days: 8));
      await expectLater(
        repo.delete(r.id),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'review_window_closed')),
      );
      now = DateTime.utc(2026, 10, 2);
      await repo.delete(r.id);
      expect((await repo.summary('sup_a')).count, before.count);
    });

    test('mock: reply once, report twice', () async {
      final repo = MockReviewsRepository();
      final page = await repo.list('sup_b', pageSize: 100);
      final noReply = page.items.firstWhere((r) => r.reply == null);
      await repo.reply(noReply.id, 'Thanks');
      await expectLater(
        repo.reply(noReply.id, 'Again'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'reply_already_exists')),
      );
      expect((await repo.report(noReply.id, reason: 'spam')).alreadyReported, isFalse);
      expect((await repo.report(noReply.id, reason: 'spam')).alreadyReported, isTrue);
    });
  });

  testWidgets('supplier screen shows rating summary and reviews list', (tester) async {
    await pumpApp(tester, location: '/supplier/sup_cn_004');
    await settle(tester, frames: 8);

    final card = find.byKey(const Key('rating_summary_card'));
    await tester.scrollUntilVisible(card, 300, scrollable: find.byType(Scrollable).first);
    expect(card, findsOneWidget);
    expect(find.byKey(const Key('rating_average')), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const Key('rating_average'))).data, '4.0');
    expect(find.byKey(const Key('hist_bar_5')), findsOneWidget);
    expect(find.byKey(const Key('sub_chip_quality')), findsOneWidget);
    expect(find.byKey(const Key('rating_completed_deals')), findsOneWidget);

    final seeAll = find.byKey(const Key('see_all_reviews'));
    await tester.scrollUntilVisible(seeAll, 300, scrollable: find.byType(Scrollable).first);
    await tester.tap(seeAll);
    await settle(tester, frames: 8);

    expect(find.byKey(const Key('reviews_list')), findsOneWidget);
    expect(find.byKey(const Key('review_rev_sup_cn_004_0')), findsOneWidget);
    expect(find.byKey(const Key('review_reply_rev_sup_cn_004_0')), findsOneWidget);
    expect(find.byKey(const Key('edited_badge_rev_sup_cn_004_1')), findsOneWidget);

    // Report from the overflow menu.
    await tester.tap(find.byKey(const Key('review_menu_rev_sup_cn_004_0')));
    await settle(tester, frames: 3);
    await tester.tap(find.byKey(const Key('menu_report')));
    await settle(tester, frames: 3);
    await tester.tap(find.byKey(const Key('report_reason_spam')));
    await settle(tester, frames: 3);
    expect(find.text('شكراً، سنراجع التقييم'), findsOneWidget);

    // Sort toggle keeps the list.
    await tester.tap(find.text('الأعلى تقييماً'));
    await settle(tester, frames: 2);

    expect(tester.takeException(), isNull);
    ScaffoldMessenger.of(tester.element(find.byKey(const Key('reviews_list'))))
        .clearSnackBars();
    await disposeApp(tester);
  });

  testWidgets('write review sheet: client checks, server error, success', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final repo = _FakeRepo();
    Review? result;

    await tester.pumpWidget(
      ProviderScope(
        overrides: [reviewsRepositoryProvider.overrideWithValue(repo)],
        child: MaterialApp(
          home: Builder(
            builder: (ctx) => Scaffold(
              body: Center(
                child: ElevatedButton(
                  key: const Key('open_sheet'),
                  onPressed: () async {
                    result = await showWriteReviewSheet(
                      ctx,
                      dealId: 'deal_1',
                      supplierRef: 'sup_x',
                    );
                  },
                  child: const Text('open'),
                ),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('open_sheet')));
    await settle(tester, frames: 5);

    Future<void> submit() async {
      final b = find.byKey(const Key('review_submit'));
      await tester.ensureVisible(b);
      await tester.tap(b);
      await settle(tester, frames: 3);
    }

    await submit();
    expect(find.byKey(const Key('review_rating_error')), findsOneWidget);
    expect(repo.calls, 0);

    await tester.tap(find.byKey(const Key('review_star_4')));
    await tester.tap(find.byKey(const Key('review_sub_quality_5')));
    await tester.enterText(find.byKey(const Key('review_text')), 'visit www.spam.com now');
    await submit();
    expect(find.text('Links are not allowed.'), findsOneWidget);
    expect(repo.calls, 0);

    await tester.enterText(find.byKey(const Key('review_text')), 'Good supplier');
    await submit();
    expect(find.byKey(const Key('review_error')), findsOneWidget);
    expect(find.text('You already reviewed this deal.'), findsOneWidget);
    expect(repo.calls, 1);

    await submit();
    expect(find.byKey(const Key('review_submit')), findsNothing);
    expect(result?.rating, 4);
    expect(repo.drafts.last.subRatings.quality, 5);
    expect(repo.drafts.last.text, 'Good supplier');

    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
