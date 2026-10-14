import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/trust/trust_models.dart';
import 'package:factory_finder/features/trust/trust_repository.dart';
import 'package:factory_finder/features/trust/trust_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

class _Adapter implements HttpClientAdapter {
  _Adapter(this.handler);
  final ResponseBody Function(RequestOptions) handler;
  final List<RequestOptions> calls = [];

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
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );

ApiClient _client(_Adapter a) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
  dio.httpClientAdapter = a;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

void main() {
  test('TrustScore parses v2 fields from the live fixture', () {
    final t = TrustScore.fromJson(Map<String, dynamic>.from(_load('trust_v2') as Map));
    expect(t.score, 91);
    expect(t.confidence, 82);
    expect(t.modelVersion, 'trust-v2');
    expect(t.flags, ['price_anomaly', 'certification_expiring']);
    expect(t.dataGaps, hasLength(2));
    expect(t.dataGaps.first.display('ar'), 'حالة الترخيص التجاري');
    expect(t.dataGaps.first.display('en'), 'Business licence status');
  });

  test('TrustScore stays tolerant of v1 / odd payloads', () {
    final v1 = TrustScore.fromJson(Map<String, dynamic>.from(_load('trust') as Map));
    expect(v1.confidence, 100); // legacy fractional 1.0
    expect(v1.dataGaps, isEmpty);
    expect(v1.flags, isEmpty);
    final odd = TrustScore.fromJson({
      'supplier_id': 's',
      'score': 50,
      'band': 'yellow',
      'data_gaps': [
        'x',
        {'key': 'a'},
        {'label': 'only label'},
      ],
      'flags': ['f', 3, null],
      'confidence': 'high',
    });
    expect(odd.confidence, isNull);
    expect(odd.dataGaps.map((g) => g.key), ['a', '']);
    expect(odd.dataGaps.first.label, 'a');
    expect(odd.flags, ['f']);
    expect(parseConfidence(250), 100);
    expect(parseConfidence(-5), 0);
    expect(parseConfidence(0.5), 50);
    expect(parseConfidence(45), 45);
  });

  test('history parsing: oldest first, skips malformed, handles empty', () {
    final pts = parseTrustHistory(_load('trust_history'));
    expect(pts, hasLength(4));
    expect(pts.first.score, 78);
    expect(pts.last.source, 'snapshot');
    expect(pts.last.confidence, 82);
    expect(pts.first.at.isBefore(pts.last.at), isTrue);

    final messy = parseTrustHistory({
      'points': [
        {'at': '2026-02-01T00:00:00Z', 'score': 70},
        {'at': 'bad', 'score': 10},
        {'at': '2026-01-01T00:00:00Z', 'score': 150.4},
        'nope',
      ],
    });
    expect(messy.map((p) => p.score), [100, 70]);
    expect(parseTrustHistory(null), isEmpty);
    expect(parseTrustHistory({'points': 'x'}), isEmpty);
  });

  test('report validation', () {
    expect(validateReport(null, 'text'), 'trust.report.err_type');
    expect(validateReport('bogus', 'text'), 'trust.report.err_type');
    expect(validateReport('fraud', '   '), 'trust.report.err_text');
    expect(validateReport('fraud', 'a' * 1001), 'trust.report.err_long');
    expect(validateReport('fraud', 'a' * 1000), isNull);
    expect(validateReport('other', ' ok '), isNull);
    expect(ReportResult.fromJson(_load('supplier_report')).status, 'pending_review');
  });

  test('chart painter maps scores to pixels', () {
    const size = Size(100, 100);
    expect(TrustHistoryPainter.pointAt(0, 3, 100, size), const Offset(0, 0));
    expect(TrustHistoryPainter.pointAt(2, 3, 0, size), const Offset(100, 100));
    expect(TrustHistoryPainter.pointAt(1, 3, 50, size), const Offset(50, 50));
  });

  test('live repo: history GET and report POST (incl. 429)', () async {
    final a = _Adapter((o) {
      if (o.method == 'GET') return _json(_load('trust_history') as Object);
      if (o.data is Map && (o.data as Map)['type'] == 'fraud') {
        return _json({'error': {'code': 'rate_limited', 'message': 'slow down'}}, 429);
      }
      return _json(_load('supplier_report') as Object, 201);
    });
    final repo = LiveTrustExtrasRepository(_client(a));
    final pts = await repo.history('sup_cn_018');
    expect(pts, hasLength(4));
    expect(a.calls.first.path, '/v1/trust/suppliers/sup_cn_018/history');

    final r = await repo.report('sup_cn_018', 'quality', ' bad ');
    expect(r.id, 'rep_1a2b3c4d');
    expect(a.calls.last.method, 'POST');
    expect(a.calls.last.path, '/v1/trust/suppliers/sup_cn_018/report');
    expect((a.calls.last.data as Map)['text'], 'bad');

    expect(
      () => repo.report('sup_cn_018', 'fraud', 'x'),
      throwsA(isA<ApiException>().having((e) => e.status, 'status', 429)),
    );
  });

  test('mock repo rate-limits after maxReports', () async {
    final repo = MockTrustExtrasRepository(maxReports: 1);
    await repo.report('s', 'other', 'x');
    await expectLater(
      repo.report('s', 'other', 'x'),
      throwsA(isA<ApiException>().having((e) => e.status, 'status', 429)),
    );
    expect(confidenceLabelKey(80), 'trust.confidence_high');
    expect(confidenceLabelKey(10), 'trust.confidence_low');
  });
}
