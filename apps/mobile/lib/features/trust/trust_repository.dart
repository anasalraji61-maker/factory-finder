import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/trust/trust_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class TrustExtrasRepository {
  Future<List<TrustHistoryPoint>> history(String supplierId);

  /// Throws [ApiException] (401 login needed, 429 rate limited, 422 invalid).
  Future<ReportResult> report(String supplierId, String type, String text);
}

class LiveTrustExtrasRepository implements TrustExtrasRepository {
  LiveTrustExtrasRepository(this._api);
  final ApiClient _api;

  @override
  Future<List<TrustHistoryPoint>> history(String supplierId) async =>
      parseTrustHistory(await _api.get('/v1/trust/suppliers/$supplierId/history'));

  @override
  Future<ReportResult> report(String supplierId, String type, String text) async {
    final data = await _api.post(
      '/v1/trust/suppliers/$supplierId/report',
      body: {'type': type, 'text': text.trim()},
    );
    return ReportResult.fromJson(data);
  }
}

class MockTrustExtrasRepository implements TrustExtrasRepository {
  MockTrustExtrasRepository({this.maxReports = 5});

  final int maxReports;
  int _count = 0;

  @override
  Future<List<TrustHistoryPoint>> history(String supplierId) async {
    await mockDelay(150);
    final seed = supplierId.codeUnits.fold<int>(0, (a, b) => (a + b) % 17);
    final base = DateTime.utc(2026, 4, 1);
    return [
      for (var i = 0; i < 6; i++)
        TrustHistoryPoint(
          at: base.add(Duration(days: 30 * i)),
          score: 55 + seed + i * 3 + (i.isOdd ? 2 : 0),
          band: 'yellow',
          confidence: 40 + i * 6,
          source: 'mock',
        ),
    ];
  }

  @override
  Future<ReportResult> report(String supplierId, String type, String text) async {
    await mockDelay(150);
    if (_count >= maxReports) {
      throw ApiException(
        status: 429,
        code: 'rate_limited',
        message: 'Too many reports',
      );
    }
    _count++;
    return ReportResult(id: 'rep_mock_$_count', status: 'pending_review');
  }
}

final trustExtrasRepositoryProvider = Provider<TrustExtrasRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockTrustExtrasRepository() : LiveTrustExtrasRepository(api);
});

final trustHistoryProvider = FutureProvider.autoDispose
    .family<List<TrustHistoryPoint>, String>(
  (ref, id) => ref.watch(trustExtrasRepositoryProvider).history(id),
);
