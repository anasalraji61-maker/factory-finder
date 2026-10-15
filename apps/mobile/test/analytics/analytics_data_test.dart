import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/analytics/analytics_logic.dart';
import 'package:factory_finder/features/analytics/analytics_models.dart';
import 'package:factory_finder/features/analytics/analytics_repository.dart';
import 'package:factory_finder/features/analytics/listing_events.dart';
import 'package:factory_finder/features/analytics/widgets/analytics_chart.dart';
import 'package:flutter_test/flutter_test.dart';

typedef _Handler = ResponseBody Function(RequestOptions options);

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.handler);

  final _Handler handler;
  final List<RequestOptions> calls = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(Object body, [int status = 200]) => ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>[Headers.jsonContentType],
      },
    );

ResponseBody _error(int status, String code) => _json(
      <String, dynamic>{
        'error': <String, dynamic>{'code': code, 'message': 'msg $code'},
      },
      status,
    );

ApiClient _client(_FakeAdapter adapter) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
  dio.httpClientAdapter = adapter;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

ApiClient _mockClient() =>
    ApiClient(baseUrl: 'http://unused.invalid', isMock: true);

Map<String, dynamic> _fixture() => Map<String, dynamic>.from(
    jsonDecode(File('test/fixtures/analytics/analytics_7d.json').readAsStringSync())
        as Map);

void main() {
  group('parsing', () {
    test('fixture parses fully', () {
      final a = SupplierAnalytics.fromJson(_fixture());
      expect(a.period.days, 7);
      expect(a.period.from, '2026-10-09');
      expect(a.period.previousTo, '2026-10-08');
      expect(a.totals.impression, 420);
      expect(a.totals.view, 120);
      expect(a.totals.contactClick, 25);
      expect(a.totals.of(AnalyticsMetric.share), 4);
      expect(a.previousTotals.view, 80);
      expect(a.series, hasLength(7));
      expect(a.series[2].counts.isZero, isTrue);
      expect(a.series.map((d) => d.counts.view).reduce((x, y) => x + y), 120);
      expect(a.changeOf(AnalyticsMetric.view), 50.0);
      expect(a.changeOf(AnalyticsMetric.contactClick), isNull);
      expect(a.changePct.containsKey('contact_click'), isTrue);
      expect(a.conversion.viewToContact, closeTo(0.2083, 0.001));
      expect(a.uniqueViewers, 98);
      expect(a.uniqueContacts, 22);
      expect(a.listings, hasLength(2));
      expect(a.listings.first.listingId, 'lst_a');
      expect(a.listings.first.viewToContact, closeTo(0.1889, 1e-9));
      expect(a.listingsTotal, 3);
      expect(a.isEmpty, isFalse);
    });

    test('tolerates missing / malformed parts', () {
      final a = SupplierAnalytics.fromJson(<String, dynamic>{
        'totals': <String, dynamic>{'view': '5', 'share': 2.9, 'report': null},
        'series': <dynamic>[
          'junk',
          <String, dynamic>{'date': '2026-01-01', 'view': 3},
        ],
        'listings': <dynamic>[
          1,
          <String, dynamic>{'listing_id': 'x', 'title': 'T'},
        ],
        'change_pct': <String, dynamic>{'view': 'bad', 'share': 10},
      }, fallbackDays: 90);
      expect(a.period.days, 90);
      expect(a.totals.view, 5);
      expect(a.totals.share, 2);
      expect(a.totals.report, 0);
      expect(a.series, hasLength(1));
      expect(a.listings.single.viewToContact, isNull);
      expect(a.listingsTotal, 1);
      expect(a.changeOf(AnalyticsMetric.view), isNull);
      expect(a.changeOf(AnalyticsMetric.share), 10);
      expect(a.isEmpty, isFalse);
    });

    test('non-object body is a FormatException; all-zero is empty', () {
      expect(() => SupplierAnalytics.fromJson([]), throwsFormatException);
      expect(SupplierAnalytics.fromJson(<String, dynamic>{}).isEmpty, isTrue);
    });
  });

  group('logic', () {
    test('classifyChange / formatChange', () {
      expect(classifyChange(null).direction, ChangeDirection.unknown);
      expect(classifyChange(double.nan).direction, ChangeDirection.unknown);
      expect(classifyChange(0.04).direction, ChangeDirection.flat);
      expect(classifyChange(12.34).direction, ChangeDirection.up);
      expect(classifyChange(-3).direction, ChangeDirection.down);
      expect(formatChange(classifyChange(12.34)), '+12.3%');
      expect(formatChange(classifyChange(-3)), '-3%');
      expect(formatChange(classifyChange(0.01)), '0%');
      expect(formatChange(classifyChange(null)), '');
      expect(formatChange(classifyChange(100)), '+100%');
    });

    test('formatRatio / formatCount', () {
      expect(formatRatio(null), '-');
      expect(formatRatio(0.2), '20%');
      expect(formatRatio(0.1889), '18.9%');
      expect(formatRatio(1), '100%');
      expect(formatRatio(0), '0%');
      expect(formatCount(12345), '12,345');
      expect(formatCount(0), '0');
    });

    test('funnelFractions', () {
      final f = funnelFractions(<int>[420, 120, 25]);
      expect(f[0], 1.0);
      expect(f[1], closeTo(120 / 420, 1e-9));
      expect(funnelFractions(<int>[0, 0]), <double>[0, 0]);
      expect(funnelFractions(<int>[]), isEmpty);
    });

    test('niceMax', () {
      const cases = <int, int>{
        0: 1, 1: 1, 2: 2, 3: 5, 7: 10, 30: 50, 100: 100,
        101: 200, 999: 1000, 1234: 2000,
      };
      cases.forEach((input, expected) {
        expect(niceMax(input), expected, reason: 'niceMax($input)');
      });
    });

    test('mapSeriesPoints is zero based and evenly spaced', () {
      final p = mapSeriesPoints(<int>[0, 5, 10], const Size(108, 56), yMax: 10);
      expect(p, hasLength(3));
      expect(p[0].dx, closeTo(4, 1e-9));
      expect(p[1].dx, closeTo(54, 1e-9));
      expect(p[2].dx, closeTo(104, 1e-9));
      expect(p[0].dy, closeTo(50, 1e-9)); // 0 sits on the baseline
      expect(p[1].dy, closeTo(28, 1e-9));
      expect(p[2].dy, closeTo(6, 1e-9));
      final one = mapSeriesPoints(<int>[3], const Size(108, 56), yMax: 10);
      expect(one.single.dx, closeTo(54, 1e-9));
      expect(mapSeriesPoints(<int>[], const Size(10, 10), yMax: 1), isEmpty);
      // values above yMax are clamped inside the plot
      final over = mapSeriesPoints(<int>[50], const Size(108, 56), yMax: 10);
      expect(over.single.dy, closeTo(6, 1e-9));
    });

    test('mapSeriesBars grow from the baseline', () {
      final r = mapSeriesBars(<int>[10, 0], const Size(108, 56), yMax: 10);
      expect(r, hasLength(2));
      expect(r[0].left, closeTo(10.25, 1e-9));
      expect(r[0].width, closeTo(37.5, 1e-9));
      expect(r[0].top, closeTo(6, 1e-9));
      expect(r[0].height, closeTo(44, 1e-9));
      expect(r[1].height, 0);
      expect(r[1].bottom, closeTo(50, 1e-9));
    });

    test('painter draws every shape without throwing and repaints on change', () {
      for (final style in AnalyticsChartStyle.values) {
        for (final values in <List<int>>[
          <int>[],
          <int>[3],
          <int>[0, 0],
          <int>[1, 2, 3, 0, 9],
        ]) {
          final painter = AnalyticsChartPainter(
            values: values,
            yMax: niceMax(values.fold<int>(0, (a, b) => a > b ? a : b)),
            color: const Color(0xFF2340D9),
            gridColor: const Color(0xFFE2E8F0),
            style: style,
          );
          final canvas = Canvas(PictureRecorder());
          painter.paint(canvas, const Size(300, 160));
        }
      }
      final a = AnalyticsChartPainter(
        values: const <int>[1],
        yMax: 1,
        color: const Color(0xFF000000),
        gridColor: const Color(0xFF000000),
      );
      final b = AnalyticsChartPainter(
        values: const <int>[2],
        yMax: 1,
        color: const Color(0xFF000000),
        gridColor: const Color(0xFF000000),
      );
      expect(b.shouldRepaint(a), isTrue);
      expect(a.shouldRepaint(a), isFalse);
    });

    test('analyticsErrorKey', () {
      ApiException e(int s, [String c = 'x']) =>
          ApiException(status: s, code: c, message: 'm');
      expect(analyticsErrorKey(e(401)), 'ana.err.signin');
      expect(analyticsErrorKey(e(403)), 'ana.err.supplier');
      expect(analyticsErrorKey(e(404)), 'ana.err.not_found');
      expect(analyticsErrorKey(e(422)), 'ana.err.bad_request');
      expect(analyticsErrorKey(e(429)), 'ana.err.rate_limited');
      expect(analyticsErrorKey(ApiException(code: 'timeout', message: 'm')),
          'ana.err.network');
      expect(analyticsErrorKey(StateError('x')), 'ana.err.generic');
    });
  });

  group('repository', () {
    test('live: sends days and optional listing_id, parses body', () async {
      final adapter = _FakeAdapter((o) => _json(_fixture()));
      final repo = AnalyticsRepository(_client(adapter));

      final a = await repo.fetch(days: 7);
      expect(a.totals.view, 120);
      var call = adapter.calls.single;
      expect(call.method, 'GET');
      expect(call.path, '/v1/my/analytics');
      expect(call.queryParameters['days'], 7);
      expect(call.queryParameters.containsKey('listing_id'), isFalse);

      await repo.fetch(days: 90, listingId: 'lst_a');
      call = adapter.calls.last;
      expect(call.queryParameters['days'], 90);
      expect(call.queryParameters['listing_id'], 'lst_a');

      await repo.fetch(listingId: '');
      expect(adapter.calls.last.queryParameters['days'], 30);
      expect(adapter.calls.last.queryParameters.containsKey('listing_id'), isFalse);
    });

    test('live: 404 other listing, 422 bad days, 403 not a supplier', () async {
      for (final c in <(int, String)>[
        (404, 'not_found'),
        (422, 'validation_error'),
        (403, 'supplier_required'),
      ]) {
        final repo =
            AnalyticsRepository(_client(_FakeAdapter((o) => _error(c.$1, c.$2))));
        await expectLater(
          repo.fetch(days: 30, listingId: 'other'),
          throwsA(isA<ApiException>()
              .having((e) => e.status, 'status', c.$1)
              .having((e) => e.code, 'code', c.$2)),
        );
      }
    });

    test('live: non-object body becomes bad_response', () async {
      final repo = AnalyticsRepository(_client(_FakeAdapter((o) => _json(<int>[1]))));
      await expectLater(
        repo.fetch(),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'bad_response')),
      );
    });

    test('mock: zero-filled series, dates and validation', () async {
      final now = DateTime.utc(2026, 10, 15, 13);
      final repo = AnalyticsRepository(_mockClient(), clock: () => now);
      final a = await repo.fetch(days: 7);
      expect(a.series, hasLength(7));
      expect(a.series.first.date, '2026-10-09');
      expect(a.series.last.date, '2026-10-15');
      expect(a.period.previousFrom, '2026-10-02');
      expect(a.period.previousTo, '2026-10-08');
      var sum = AnalyticsCounts.zero;
      for (final d in a.series) {
        sum = sum + d.counts;
      }
      expect(sum.view, a.totals.view);
      expect(a.listings, isNotEmpty);
      expect((await repo.fetch(days: 90)).series, hasLength(90));

      final one = await repo.fetch(days: 30, listingId: kMockAnalyticsListings.first.$1);
      final all = await repo.fetch(days: 30);
      expect(one.listings, hasLength(1));
      expect(one.totals.view, lessThan(all.totals.view));

      await expectLater(repo.fetch(days: 5),
          throwsA(isA<ApiException>().having((e) => e.status, 'status', 422)));
      await expectLater(repo.fetch(listingId: 'nope'),
          throwsA(isA<ApiException>().having((e) => e.status, 'status', 404)));
    });
  });

  group('event reporter', () {
    test('live: posts type once per listing+type and never throws', () async {
      final adapter = _FakeAdapter((o) => _json(<String, dynamic>{'counted': true}, 202));
      final r = ListingEventReporter(_client(adapter));

      r.report('lst_1', ListingEventType.view);
      r.report('lst_1', ListingEventType.view); // duplicate
      r.report('lst_1', ListingEventType.contactClick);
      r.report('lst_2', ListingEventType.view);
      r.report('lst_1', ListingEventType.share);
      r.report('', ListingEventType.view); // ignored
      await pumpEventQueue();

      expect(adapter.calls, hasLength(4));
      final first = adapter.calls.first;
      expect(first.method, 'POST');
      expect(first.path, '/v1/listings/lst_1/events');
      expect(first.data, <String, dynamic>{'type': 'view'});
      expect(adapter.calls.map((c) => (c.data as Map)['type']).toList(),
          <String>['view', 'contact_click', 'view', 'share']);
      expect(r.hasReported('lst_1', ListingEventType.view), isTrue);
      expect(r.mockEvents, isEmpty);
    });

    test('live: report returns synchronously (does not wait for the network)', () {
      final adapter = _FakeAdapter((o) => _json(<String, dynamic>{'counted': true}, 202));
      final r = ListingEventReporter(_client(adapter));
      r.report('lst_1', ListingEventType.view);
      // Nothing awaited: the call is only started.
      expect(r.hasReported('lst_1', ListingEventType.view), isTrue);
    });

    test('live: 5xx frees the pair for a retry, 429 does not', () async {
      var status = 500;
      final adapter = _FakeAdapter((o) => _error(status, 'boom'));
      final r = ListingEventReporter(_client(adapter));

      r.report('lst_1', ListingEventType.view);
      await pumpEventQueue();
      expect(r.hasReported('lst_1', ListingEventType.view), isFalse);
      r.report('lst_1', ListingEventType.view);
      await pumpEventQueue();
      expect(adapter.calls, hasLength(2));

      status = 429;
      r.report('lst_2', ListingEventType.share);
      await pumpEventQueue();
      expect(r.hasReported('lst_2', ListingEventType.share), isTrue);
      r.report('lst_2', ListingEventType.share);
      await pumpEventQueue();
      expect(adapter.calls, hasLength(3));
    });

    test('live: transport failure is swallowed', () async {
      final adapter = _FakeAdapter((o) => throw const SocketLikeError());
      final r = ListingEventReporter(_client(adapter));
      r.report('lst_1', ListingEventType.view);
      await pumpEventQueue();
      expect(r.hasReported('lst_1', ListingEventType.view), isFalse);
    });

    test('mock: nothing is sent, deduped events are recorded', () async {
      final r = ListingEventReporter(_mockClient());
      r.report('lst_1', ListingEventType.view);
      r.report('lst_1', ListingEventType.view);
      r.report('lst_1', ListingEventType.contactClick);
      r.report('lst_1', ListingEventType.share);
      await pumpEventQueue();
      expect(r.mockEvents, const <ListingEventRecord>[
        ListingEventRecord('lst_1', ListingEventType.view),
        ListingEventRecord('lst_1', ListingEventType.contactClick),
        ListingEventRecord('lst_1', ListingEventType.share),
      ]);
      expect(() => r.mockEvents.add(const ListingEventRecord('x', ListingEventType.view)),
          throwsUnsupportedError);
    });
  });
}

class SocketLikeError implements Exception {
  const SocketLikeError();
}
