import 'package:factory_finder/features/fx/data/fx_models.dart';
import 'package:factory_finder/features/fx/data/fx_repository.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('FxRates JSON round-trip', () {
    final json = {
      'base': 'USD',
      'timestamp': '2026-10-13T10:00:00Z',
      'source': 'mock',
      'rates': {'IQD': '1310', 'EUR': '0.92'},
    };
    final r = FxRates.fromJson(json);
    expect(r.base, 'USD');
    expect(r.rateOf('IQD'), 1310);
    expect(r.rateOf('USD'), 1);
    final again = FxRates.fromJson(r.toJson());
    expect(again.rates, r.rates);
    expect(again.timestamp, r.timestamp);
    expect(again.source, 'mock');
  });

  test('ConvertResult JSON round-trip', () {
    final json = {
      'amount': {'amount': '131000', 'currency': 'IQD'},
      'rate': '1310',
      'from': 'USD',
      'to': 'IQD',
      'timestamp': '2026-10-13T10:00:00Z',
      'source': 'mock',
    };
    final c = ConvertResult.fromJson(json);
    expect(c.amount, '131000');
    expect(c.currency, 'IQD');
    final again = ConvertResult.fromJson(c.toJson());
    expect(again.rate, '1310');
    expect(again.to, 'IQD');
  });

  test('converter math', () {
    expect(convertAmount(100, 1, 1310), 131000);
    expect(crossRate(1310, 1), closeTo(1 / 1310, 1e-12));
    expect(convertAmount(10, 0, 5), 0);
    expect(formatFx(131000), '131,000');
    expect(formatFx(1234.5), '1,234.5');
  });

  test('mock repo: IQD per USD and cross rates', () async {
    final repo = MockFxRepository(clock: () => DateTime.utc(2026, 10, 13));
    final usd = await repo.rates('USD');
    expect(usd.rateOf('IQD'), 1310);
    final eur = await repo.rates('EUR');
    expect(eur.rateOf('USD'), closeTo(1 / 0.92, 1e-9));
    final res = await repo.convert(100, 'USD', 'IQD');
    expect(double.parse(res.amount), closeTo(131000, 1e-6));
    expect(res.source, 'mock');
  });
}
