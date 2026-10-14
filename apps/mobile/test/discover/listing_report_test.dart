import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/data/listing_report.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:flutter_test/flutter_test.dart';

class _Adapter implements HttpClientAdapter {
  _Adapter(this.respond);
  final ResponseBody Function(RequestOptions) respond;
  final List<RequestOptions> calls = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return respond(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _fixture(String name, int status, {Map<String, List<String>>? headers}) =>
    ResponseBody.fromString(
      File('test/fixtures/live/$name.json').readAsStringSync(),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
        ...?headers,
      },
    );

DiscoverRepository _live(_Adapter a) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = a;
  return DiscoverRepository(ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio));
}

void main() {
  group('body and error mapping', () {
    test('reasons match the contract enum', () {
      final spec = File('../../contracts/openapi/sourcing.yaml').readAsStringSync();
      for (final r in ListingReportReason.values) {
        expect(spec, contains(r.json), reason: r.json);
      }
      expect(ListingReportReason.values, hasLength(7));
    });

    test('details are trimmed, capped at 500 and omitted when empty', () {
      expect(buildReportBody(ListingReportReason.scamOrFraud, '  '),
          {'reason': 'scam_or_fraud'});
      expect(buildReportBody(ListingReportReason.other, null), {'reason': 'other'});
      final long = buildReportBody(ListingReportReason.other, 'x' * 800);
      expect((long['details'] as String).length, kReportDetailsMax);
      expect(buildReportBody(ListingReportReason.offensive, ' bad '),
          {'reason': 'offensive', 'details': 'bad'});
    });

    test('status codes map to i18n keys', () {
      ApiException e(int s, [String code = 'x', int? ra]) =>
          ApiException(status: s, code: code, message: 'm', retryAfterSeconds: ra);
      expect(reportErrorKey(e(401)), 'report.err.auth');
      expect(reportErrorKey(e(404)), 'report.err.not_found');
      expect(reportErrorKey(e(409, 'own_listing')), 'report.err.own_listing');
      expect(reportErrorKey(e(409)), 'report.err.own_listing');
      expect(reportErrorKey(e(422)), 'report.err.invalid');
      expect(reportErrorKey(e(429)), 'report.err.rate_limited');
      expect(reportErrorKey(e(429, 'x', 1800)), 'report.err.rate_limited_wait');
      expect(reportErrorKey(e(0, 'network_error')), 'report.err.network');
      expect(reportErrorKey(e(500)), 'report.err.generic');
      expect(reportErrorKey(Exception('x')), 'report.err.generic');
      expect(retryAfterMinutes(30), 1);
      expect(retryAfterMinutes(1800), 30);
      expect(retryAfterMinutes(61), 2);
    });
  });

  group('live repository', () {
    test('POST /v1/listings/{id}/report with reason and details', () async {
      final adapter = _Adapter((o) => _fixture('report_accepted', 202));
      await _live(adapter).reportListing(
        'lst_0041',
        ListingReportReason.counterfeit,
        details: 'Looks fake',
      );
      final call = adapter.calls.single;
      expect(call.method, 'POST');
      expect(call.path, '/v1/listings/lst_0041/report');
      expect(call.data, {'reason': 'counterfeit', 'details': 'Looks fake'});
    });

    test('409 own_listing and 429 with Retry-After surface as ApiException', () async {
      final own = _Adapter((o) => _fixture('error_report_own_listing', 409));
      await expectLater(
        _live(own).reportListing('lst_1', ListingReportReason.other),
        throwsA(isA<ApiException>()
            .having((e) => e.status, 'status', 409)
            .having((e) => e.code, 'code', 'own_listing')),
      );
      final limited = _Adapter((o) => _fixture('error_report_rate_limited', 429,
          headers: {
            'retry-after': ['1800'],
          }));
      try {
        await _live(limited).reportListing('lst_1', ListingReportReason.other);
        fail('expected 429');
      } on ApiException catch (e) {
        expect(e.status, 429);
        expect(e.retryAfterSeconds, 1800);
        expect(reportErrorKey(e), 'report.err.rate_limited_wait');
      }
    });

    test('accepted fixture is a plain received status', () {
      final j = jsonDecode(File('test/fixtures/live/report_accepted.json').readAsStringSync());
      expect(j['status'], 'received');
    });
  });

  group('mock repository', () {
    DiscoverRepository mock() =>
        DiscoverRepository(ApiClient(baseUrl: 'http://x', isMock: true));

    test('accepts, repeats silently, 404 for unknown ids', () async {
      final repo = mock();
      final id = mockListings.first.id;
      await repo.reportListing(id, ListingReportReason.misleading);
      await repo.reportListing(id, ListingReportReason.misleading);
      await expectLater(
        repo.reportListing('nope', ListingReportReason.other),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 404)),
      );
    });

    test('rate limits after 10 distinct listings', () async {
      final repo = mock();
      expect(mockListings.length, greaterThanOrEqualTo(11));
      for (final l in mockListings.take(10)) {
        await repo.reportListing(l.id, ListingReportReason.other);
      }
      await expectLater(
        repo.reportListing(mockListings[10].id, ListingReportReason.other),
        throwsA(isA<ApiException>()
            .having((e) => e.status, 'status', 429)
            .having((e) => e.retryAfterSeconds, 'retry', isNotNull)),
      );
    });
  });
}
