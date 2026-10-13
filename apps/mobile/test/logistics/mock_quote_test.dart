import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:flutter_test/flutter_test.dart';

double _mid(LandedCostOption o) => (o.total.min.value + o.total.max.value) / 2;

LandedCostQuote _quote({
  double weight = 2000,
  double volume = 8,
  String city = 'Baghdad',
  bool dangerous = false,
  Incoterm incoterm = Incoterm.fob,
  String currency = 'USD',
}) {
  return MockQuoteGenerator.generate(
    QuoteRequest(
      goodsValue: 10000,
      weightKg: weight,
      volumeM3: volume,
      origin: const Location(countryCode: 'CN', city: 'Guangzhou'),
      destination: Location(countryCode: 'IQ', city: city),
      dangerousGoods: dangerous,
      incoterm: incoterm,
      displayCurrency: currency,
    ),
    lang: 'en',
  );
}

void main() {
  test('options are sorted by total, exactly one is recommended', () {
    final q = _quote();
    expect(q.options, isNotEmpty);
    for (var i = 1; i < q.options.length; i++) {
      expect(_mid(q.options[i]) >= _mid(q.options[i - 1]), isTrue);
    }
    expect(q.options.where((o) => o.recommended).length, 1);
  });

  test('total range brackets the sum of the lines', () {
    for (final q in [_quote(), _quote(weight: 22000, volume: 60), _quote(currency: 'IQD')]) {
      for (final o in q.options) {
        final sum = o.lines.fold<double>(0, (a, l) => a + l.amount.value);
        expect(sum, greaterThanOrEqualTo(o.total.min.value - 0.01));
        expect(sum, lessThanOrEqualTo(o.total.max.value + 0.01));
        expect(o.lines.every((l) => l.amount.currency == q.currency), isTrue);
        expect(o.transitDays.min <= o.transitDays.max, isTrue);
      }
    }
  });

  test('large cargo gets FCL options, small cargo gets LCL and air', () {
    final big = _quote(weight: 22000, volume: 60);
    final modes = big.options.map((o) => o.mode).toSet();
    expect(modes, containsAll([TransportMode.seaFcl20, TransportMode.seaFcl40]));
    expect(modes.contains(TransportMode.seaLcl), isFalse);

    final small = _quote();
    final smallModes = small.options.map((o) => o.mode).toSet();
    expect(smallModes, containsAll([TransportMode.seaLcl, TransportMode.air]));
  });

  test('Baghdad warns about Umm Qasr; Erbil routes via Mersin', () {
    final baghdad = _quote().options.firstWhere((o) => o.mode == TransportMode.seaLcl);
    expect(baghdad.destinationHub, contains('Umm Qasr'));
    expect(baghdad.warnings.any((w) => w.contains('Umm Qasr')), isTrue);

    final erbil = _quote(city: 'Erbil').options.firstWhere((o) => o.mode == TransportMode.seaLcl);
    expect(erbil.destinationHub, contains('Mersin'));
    expect(erbil.warnings.any((w) => w.contains('Mersin')), isTrue);
  });

  test('dangerous goods add a warning and a surcharge line', () {
    final o = _quote(dangerous: true).options.first;
    expect(o.warnings.any((w) => w.toLowerCase().contains('dangerous')), isTrue);
    expect(o.lines.any((l) => l.stage == 'other'), isTrue);
  });

  test('incoterm DDP zeroes duties, taxes and clearance', () {
    final o = _quote(incoterm: Incoterm.ddp).options.first;
    for (final stage in ['duties', 'taxes', 'clearance', 'main_leg']) {
      expect(o.lines.firstWhere((l) => l.stage == stage).amount.value, 0);
    }
  });

  test('preferred modes filter the result', () {
    final q = MockQuoteGenerator.generate(
      const QuoteRequest(
        goodsValue: 5000,
        weightKg: 500,
        volumeM3: 3,
        origin: Location(countryCode: 'CN', city: 'Shenzhen'),
        destination: Location(countryCode: 'IQ', city: 'Baghdad'),
        modes: {TransportMode.air},
      ),
      lang: 'ar',
    );
    expect(q.options.length, 1);
    expect(q.options.single.mode, TransportMode.air);
    expect(q.options.single.recommended, isTrue);
  });
}
