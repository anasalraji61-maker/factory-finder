import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/fx/data/fx_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class FxRepository {
  Future<FxRates> rates(String base);
  Future<ConvertResult> convert(double amount, String from, String to);
}

class LiveFxRepository implements FxRepository {
  LiveFxRepository(this._api);
  final ApiClient _api;

  @override
  Future<FxRates> rates(String base) async {
    final data = await _api.get('/v1/fx/rates', query: {'base': base});
    return FxRates.fromJson(Map<String, dynamic>.from(data as Map));
  }

  @override
  Future<ConvertResult> convert(double amount, String from, String to) async {
    final data = await _api.post('/v1/fx/convert', body: {
      'amount': amount.toString(),
      'from': from,
      'to': to,
    });
    return ConvertResult.fromJson(Map<String, dynamic>.from(data as Map));
  }
}

/// Static rates per 1 USD.
const Map<String, String> kMockUsdRates = {
  'USD': '1',
  'EUR': '0.92',
  'CNY': '7.24',
  'IQD': '1310',
  'TRY': '34.2',
  'AED': '3.6725',
  'SAR': '3.75',
  'GBP': '0.78',
  'IRR': '42000',
};

class MockFxRepository implements FxRepository {
  MockFxRepository({DateTime Function()? clock}) : _clock = clock ?? DateTime.now;
  final DateTime Function() _clock;

  double _usd(String code) => double.tryParse(kMockUsdRates[code] ?? '') ?? 0;

  @override
  Future<FxRates> rates(String base) async {
    final b = _usd(base);
    final out = <String, String>{};
    kMockUsdRates.forEach((code, _) {
      if (code == base || b == 0) return;
      out[code] = crossRate(b, _usd(code)).toString();
    });
    return FxRates(
      base: base,
      rates: out,
      timestamp: _clock().toUtc(),
      source: 'mock',
    );
  }

  @override
  Future<ConvertResult> convert(double amount, String from, String to) async {
    final rate = crossRate(_usd(from), _usd(to));
    return ConvertResult(
      amount: (amount * rate).toString(),
      currency: to,
      rate: rate.toString(),
      from: from,
      to: to,
      timestamp: _clock().toUtc(),
      source: 'mock',
    );
  }
}

final fxRepositoryProvider = Provider<FxRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockFxRepository() : LiveFxRepository(api);
});

final fxBaseProvider = StateProvider<String>((ref) => 'USD');

final fxRatesProvider = FutureProvider.autoDispose.family<FxRates, String>(
  (ref, base) => ref.watch(fxRepositoryProvider).rates(base),
);
