import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/freight/data/mock_freight_repository.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:flutter_test/flutter_test.dart';

final DateTime _now = DateTime.utc(2026, 10, 15, 12);

FreightOverride _override({DateTime? validUntil, String? family = 'sea'}) => FreightOverride(
      amount: '2750.00',
      currency: 'USD',
      quoteId: 'fq_102_1',
      validUntil: validUntil ?? DateTime.utc(2026, 11, 1),
      modeFamily: family,
    );

LandedCostQuote _gen(FreightOverride? o) => MockQuoteGenerator.generate(
      QuoteRequest(
        goodsValue: 10000,
        weightKg: 2000,
        volumeM3: 8,
        origin: const Location(countryCode: 'CN', city: 'Guangzhou'),
        destination: const Location(countryCode: 'IQ', city: 'Baghdad'),
        freightOverride: o,
      ),
      lang: 'en',
      now: _now,
    );

Iterable<CostLine> _mainLegs(LandedCostQuote q, {String? family}) => q.options
    .where((o) => family == null || o.mode.json.startsWith(family))
    .expand((o) => o.lines)
    .where((l) => l.stage == 'main_leg');

void main() {
  test('CostLine parses quoted and defaults to false', () {
    final base = {
      'stage': 'main_leg',
      'description': 'x',
      'amount': {'amount': '10.00', 'currency': 'USD'},
      'estimate': false,
    };
    expect(CostLine.fromJson(base).quoted, isFalse);
    expect(CostLine.fromJson({...base, 'quoted': true}).quoted, isTrue);
    expect(CostLine.fromJson({...base, 'quoted': true}).toJson()['quoted'], true);
    expect(CostLine.fromJson(base).toJson().containsKey('quoted'), isFalse);
  });

  test('FreightOverride json round trip', () {
    final o = _override();
    final back = FreightOverride.fromJson(o.toJson());
    expect(back.amount, '2750.00');
    expect(back.currency, 'USD');
    expect(back.quoteId, 'fq_102_1');
    expect(back.modeFamily, 'sea');
    expect(back.validUntil, DateTime.utc(2026, 11, 1));
    expect(o.toJson()['source'], 'forwarder_quote');
  });

  test('valid override gives an exact quoted main leg on sea options only', () {
    final q = _gen(_override());
    final sea = _mainLegs(q, family: 'sea').toList();
    expect(sea, isNotEmpty);
    for (final l in sea) {
      expect(l.quoted, isTrue);
      expect(l.estimate, isFalse);
      expect(l.amount.value, 2750);
    }
    for (final l in _mainLegs(q).where((l) => !sea.contains(l))) {
      expect(l.quoted, isFalse);
      expect(l.estimate, isTrue);
    }
    // Other lines stay estimates.
    final duties = q.options.first.lines.firstWhere((l) => l.stage == 'duties');
    expect(duties.estimate, isTrue);
    expect(q.assumptions.any((a) => a.contains('awarded forwarder quote')), isTrue);
  });

  test('expired override is ignored and explained', () {
    final q = _gen(_override(validUntil: DateTime.utc(2026, 10, 1)));
    expect(_mainLegs(q).any((l) => l.quoted), isFalse);
    expect(q.assumptions.any((a) => a.contains('expired')), isTrue);
  });

  test('mock repository: landedCostInput only for the awarded quote', () async {
    final repo = MockFreightRepository(clock: () => _now);
    final o = await repo.landedCostInput('fq_102_1');
    expect(o.amount, '4100.00');
    expect(o.currency, 'USD');
    expect(o.quoteId, 'fq_102_1');
    expect(o.modeFamily, 'sea');
    expect(o.validUntil.isAfter(_now), isTrue);
    await expectLater(
      repo.landedCostInput('fq_100_1'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'quote_not_awarded')),
    );
  });
}
