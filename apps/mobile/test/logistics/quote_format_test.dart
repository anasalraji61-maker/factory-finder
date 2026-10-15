import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_format.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:factory_finder/features/logistics/data/saved_quotes.dart';
import 'package:flutter_test/flutter_test.dart';

final DateTime _now = DateTime.utc(2026, 10, 15, 12);

QuoteRequest _req({
  Incoterm incoterm = Incoterm.fob,
  FreightOverride? override,
  String currency = 'USD',
}) =>
    QuoteRequest(
      goodsValue: 10000,
      weightKg: 2000,
      volumeM3: 8,
      origin: const Location(countryCode: 'CN', city: 'Guangzhou'),
      destination: const Location(countryCode: 'IQ', city: 'Baghdad'),
      incoterm: incoterm,
      displayCurrency: currency,
      freightOverride: override,
    );

LandedCostQuote _quote({String lang = 'en', QuoteRequest? r}) =>
    MockQuoteGenerator.generate(r ?? _req(), lang: lang, now: _now);

LandedCostOption _option(List<String> warnings, {List<CostLine>? lines}) => LandedCostOption(
      mode: TransportMode.air,
      lines: lines ??
          const [
            CostLine(
              stage: 'main_leg',
              description: 'x',
              amount: Money(amount: '10.00', currency: 'USD'),
              estimate: true,
            ),
          ],
      total: const MoneyRange(
        min: Money(amount: '9.00', currency: 'USD'),
        max: Money(amount: '12.00', currency: 'USD'),
      ),
      transitDays: const DayRange(min: 3, max: 5),
      warnings: warnings,
    );

void main() {
  setUpAll(registerFeatureStrings);

  group('normalizeDecimalInput', () {
    test('plain, grouped, arabic and decimal-comma inputs', () {
      expect(normalizeDecimalInput('12.50'), '12.5');
      expect(normalizeDecimalInput('007'), '7');
      expect(normalizeDecimalInput('0.050'), '0.05');
      expect(normalizeDecimalInput('.5'), '0.5');
      expect(normalizeDecimalInput('5.'), '5');
      expect(normalizeDecimalInput('1,500'), '1500');
      expect(normalizeDecimalInput('1,234,567.8'), '1234567.8');
      expect(normalizeDecimalInput('1,5'), '1.5');
      expect(normalizeDecimalInput('١٢٫٥'), '12.5');
      expect(normalizeDecimalInput('١٬٥٠٠'), '1500');
      expect(normalizeDecimalInput(' 3 '), '3');
    });

    test('rejects garbage instead of silently turning it into zero', () {
      for (final bad in ['', '   ', '.', '1.2.3', '1,2,3', 'abc', '1e3', '-5', '--', '1,5000']) {
        expect(normalizeDecimalInput(bad), isNull, reason: bad);
      }
      expect(normalizeDecimalInput('1234567890123456'), isNull); // > 15 integer digits
      expect(normalizeDecimalInput('0.123456789'), isNull); // > 8 decimals
    });

    test('zero detection', () {
      expect(isZeroDecimal('0'), isTrue);
      expect(isZeroDecimal('0.00'), isTrue);
      expect(isZeroDecimal('0.01'), isFalse);
      expect(isZeroDecimal('100'), isFalse);
    });
  });

  group('exact decimal math', () {
    test('decimalMul never goes through binary floats', () {
      expect(decimalMul('0.1', '3'), '0.3'); // double gives 0.30000000000000004
      expect(decimalMul('5.5', '500'), '2750');
      expect(decimalMul('0.06', '500'), '30');
      expect(decimalMul('0.0002', '500'), '0.1');
      expect(decimalMul('19.99', '3'), '59.97');
      expect(decimalMul('123456789012', '1000'), '123456789012000');
      expect(decimalMul('0', '5'), '0');
    });

    test('decimalAtLeast2 pads but never rounds', () {
      expect(decimalAtLeast2('10'), '10.00');
      expect(decimalAtLeast2('10.5'), '10.50');
      expect(decimalAtLeast2('0.125'), '0.125');
    });
  });

  group('HS code', () {
    test('empty is fine, 6-10 digits ok, separators stripped', () {
      expect(parseHsCode('').ok, isTrue);
      expect(parseHsCode('  ').code, isNull);
      expect(parseHsCode('851830').code, '851830');
      expect(parseHsCode('8518.30').code, '851830');
      expect(parseHsCode('8518.30.10').code, '85183010');
      expect(parseHsCode('8518301099').code, '8518301099');
      expect(parseHsCode('٨٥١٨٣٠').code, '851830');
    });

    test('too short, too long or non digits fail', () {
      for (final bad in ['85183', '85183010999', 'abcdef', '8518a30', '8518/30']) {
        expect(parseHsCode(bad).ok, isFalse, reason: bad);
      }
    });
  });

  group('incoterm coverage', () {
    test('mirrors the quote engine table', () {
      expect(supplierCoversStage(Incoterm.exw, 'origin_inland'), isFalse);
      expect(supplierCoversStage(Incoterm.fca, 'origin_inland'), isTrue);
      expect(supplierCoversStage(Incoterm.fca, 'origin_handling'), isFalse);
      expect(supplierCoversStage(Incoterm.fob, 'origin_handling'), isTrue);
      expect(supplierCoversStage(Incoterm.fob, 'main_leg'), isFalse);
      expect(supplierCoversStage(Incoterm.cfr, 'main_leg'), isTrue);
      expect(supplierCoversStage(Incoterm.cfr, 'insurance'), isFalse);
      expect(supplierCoversStage(Incoterm.cif, 'insurance'), isTrue);
      expect(supplierCoversStage(Incoterm.dap, 'destination_inland'), isTrue);
      expect(supplierCoversStage(Incoterm.dap, 'duties'), isFalse);
      expect(supplierCoversStage(Incoterm.ddp, 'duties'), isTrue);
      expect(supplierCoversStage(Incoterm.ddp, 'taxes'), isTrue);
      expect(supplierCoversStage(Incoterm.ddp, 'destination_handling'), isFalse);
    });

    test('zero lines of the mock quote are exactly the covered stages', () {
      for (final inc in Incoterm.values) {
        final q = _quote(r: _req(incoterm: inc));
        for (final line in q.options.first.lines) {
          if (line.stage == 'goods' || line.stage == 'destination_handling') continue;
          final zero = isZeroDecimal(line.amount.amount);
          expect(zero, supplierCoversStage(inc, line.stage),
              reason: '${inc.json} ${line.stage}');
        }
      }
    });
  });

  group('estimate label', () {
    test('parses the server warning (en and ar)', () {
      final en = estimateLabelOf(_option(
          ['Logistics are 50% of goods.', 'Estimate, confidence low, as of 2026-10: transit 3-5 days is indicative.']));
      expect(en.isEstimate, isTrue);
      expect(en.confidence, QuoteConfidence.low);
      expect(en.asOf, '2026-10');

      final med = estimateLabelOf(_option(['Estimate, confidence medium, as of 2026-10-15: x']));
      expect(med.confidence, QuoteConfidence.medium);
      expect(med.asOf, '2026-10-15');

      final ar = estimateLabelOf(_option(['تقدير، الثقة منخفضة، حتى 2026-10: مدة النقل']));
      expect(ar.confidence, QuoteConfidence.low);
      expect(ar.asOf, '2026-10');
    });

    test('missing label stays "not stated", never high', () {
      final l = estimateLabelOf(_option(const []));
      expect(l.isEstimate, isTrue);
      expect(l.confidence, isNull);
      expect(l.asOf, isNull);
    });

    test('lowest confidence wins', () {
      final l = estimateLabelOf(_option([
        'Estimate, confidence high, as of 2026-09: a',
        'Estimate, confidence low, as of 2026-10: b',
      ]));
      expect(l.confidence, QuoteConfidence.low);
      expect(l.asOf, '2026-10');
    });

    test('line sources contribute as-of and confidence', () {
      final l = estimateLabelOf(_option(const [], lines: const [
        CostLine(
          stage: 'duties',
          description: 'd',
          amount: Money(amount: '1.00', currency: 'USD'),
          estimate: true,
          source: 'approx. duty table; as of 2026-09, confidence medium',
        ),
      ]));
      expect(l.confidence, QuoteConfidence.medium);
      expect(l.asOf, '2026-09');
    });

    test('only exact lines -> not an estimate', () {
      final l = estimateLabelOf(_option(const [], lines: const [
        CostLine(
          stage: 'goods',
          description: 'g',
          amount: Money(amount: '5.00', currency: 'USD'),
          estimate: false,
        ),
        CostLine(
          stage: 'main_leg',
          description: 'q',
          amount: Money(amount: '5.00', currency: 'USD'),
          estimate: false,
          quoted: true,
        ),
      ]));
      expect(l.isEstimate, isFalse);
    });

    test('mock quote carries the label: low, or medium with a live forwarder quote', () {
      final low = estimateLabelOf(_quote().options.first);
      expect(low.isEstimate, isTrue);
      expect(low.confidence, QuoteConfidence.low);
      expect(low.asOf, '2026-10');
      expect(estimateLabelOf(_quote(lang: 'ar').options.first).confidence, QuoteConfidence.low);

      final fo = FreightOverride(
        amount: '2750.00',
        currency: 'USD',
        quoteId: 'fq_1',
        validUntil: DateTime.utc(2026, 11, 1),
        modeFamily: 'sea',
      );
      final q = _quote(r: _req(override: fo));
      final sea = q.options.firstWhere((o) => o.mode.json.startsWith('sea'));
      expect(estimateLabelOf(sea).confidence, QuoteConfidence.medium);
      expect(estimateLabelOfQuote(q).confidence, QuoteConfidence.low);
    });
  });

  group('share text', () {
    String share(LandedCostQuote q, {Incoterm? inc}) => buildQuoteShareText(
          q,
          incoterm: inc,
          t: (String k, [Map<String, String> a = const {}]) => AppStrings.lookup('en', k, a),
          modeName: (m) => AppStrings.lookup('en', 'logistics.mode.${m.json}'),
        );

    test('always carries the estimate disclaimer, confidence, as-of and range', () {
      final q = _quote();
      final text = share(q, inc: Incoterm.fob);
      expect(text, contains('not a binding quote'));
      expect(text, contains('Confidence: low'));
      expect(text, contains('As of 2026-10'));
      expect(text, contains('FOB'));
      expect(text, contains('Estimate'));
      expect(text, contains('–')); // a range, not a single number
      expect(text, contains(q.options.first.total.format()));
      expect(text.trimRight().split('\n').last, startsWith('Disclaimer:'));
    });

    test('empty quote still ends with the disclaimer', () {
      final q = LandedCostQuote(
        id: 'q',
        currency: 'USD',
        options: const [],
        createdAt: _now,
      );
      expect(share(q), contains('Disclaimer'));
    });

    test('amounts beyond double precision are not rounded', () {
      final q = LandedCostQuote(
        id: 'q',
        currency: 'USD',
        createdAt: _now,
        options: [
          LandedCostOption(
            mode: TransportMode.air,
            lines: const [],
            total: const MoneyRange(
              min: Money(amount: '12345678901234567.89', currency: 'USD'),
              max: Money(amount: '12345678901234568.91', currency: 'USD'),
            ),
            transitDays: const DayRange(min: 1, max: 2),
          ),
        ],
      );
      final text = share(q);
      expect(text, contains(r'$12,345,678,901,234,567.89 – $12,345,678,901,234,568.91'));
    });
  });

  group('QuoteRequest wire format', () {
    test('typed decimal strings are sent verbatim', () {
      final r = QuoteRequest(
        goodsValue: 0.1 * 3,
        goodsValueText: '0.3',
        weightKg: 12.5,
        weightText: '12.5',
        volumeM3: 0.00004,
        volumeText: '0.00004',
        origin: const Location(countryCode: 'CN'),
        destination: const Location(countryCode: 'IQ'),
      );
      final goods = r.toJson()['goods'] as Map;
      expect((goods['total_value'] as Map)['amount'], '0.30');
      expect(goods['total_weight_kg'], '12.5');
      expect(goods['total_volume_m3'], '0.00004');
    });

    test('zero or empty volume is omitted; no text falls back to doubles', () {
      final zero = QuoteRequest(
        goodsValue: 10,
        weightKg: 5,
        volumeM3: 0,
        volumeText: '0',
        origin: const Location(countryCode: 'CN'),
        destination: const Location(countryCode: 'IQ'),
      ).toJson()['goods'] as Map;
      expect(zero.containsKey('total_volume_m3'), isFalse);
      final plain = _req().toJson()['goods'] as Map;
      expect((plain['total_value'] as Map)['amount'], '10000.00');
      expect(plain['total_weight_kg'], '2000');
    });

    test('copyWith changes only what it is asked to and keeps typed texts', () {
      final r = QuoteRequest(
        goodsValue: 10,
        goodsValueText: '10',
        weightKg: 5,
        weightText: '5',
        volumeM3: 1,
        origin: const Location(countryCode: 'CN'),
        destination: const Location(countryCode: 'IQ'),
        incoterm: Incoterm.cif,
        modes: const {TransportMode.air},
        freightOverride: FreightOverride(
          amount: '1.00',
          currency: 'USD',
          quoteId: 'a',
          validUntil: DateTime.utc(2027),
        ),
      );
      final c = r.copyWith(displayCurrency: 'EUR');
      expect(c.displayCurrency, 'EUR');
      expect(c.incoterm, Incoterm.cif);
      expect(c.modes, {TransportMode.air});
      expect(c.goodsValueText, '10');
      expect(c.weightText, '5');
      expect(c.freightOverride, isNotNull);
      expect(r.withoutOverride().freightOverride, isNull);
      expect(r.withoutOverride().weightText, '5');
      expect(c.toJson()['display_currency'], 'EUR');
    });
  });

  group('saved quotes', () {
    test('save, dedupe, persist, reload and delete', () async {
      final store = MemoryStore();
      final n = SavedQuotesNotifier(store);
      await n.ready;
      final q1 = _quote();
      await n.save(q1, incoterm: Incoterm.fob, now: _now);
      await n.save(q1, incoterm: Incoterm.cif, now: _now);
      expect(n.state, hasLength(1));
      expect(n.state.single.incoterm, Incoterm.cif);

      final again = SavedQuotesNotifier(store);
      await again.ready;
      expect(again.state, hasLength(1));
      expect(again.state.single.quote.id, q1.id);
      expect(again.state.single.savedAt, _now);
      expect(again.state.single.quote.options.length, q1.options.length);
      expect(estimateLabelOf(again.state.single.quote.options.first).asOf, '2026-10');

      await again.remove(q1.id);
      expect(again.state, isEmpty);
      final third = SavedQuotesNotifier(store);
      await third.ready;
      expect(third.state, isEmpty);
    });

    test('capped at the newest 10', () async {
      final n = SavedQuotesNotifier(MemoryStore());
      await n.ready;
      for (var i = 0; i < 12; i++) {
        await n.save(
          LandedCostQuote.fromJson({..._quote().toJson(), 'id': 'q$i'}),
          now: _now,
        );
      }
      expect(n.state, hasLength(kMaxSavedQuotes));
      expect(n.state.first.quote.id, 'q11');
      expect(n.state.any((s) => s.quote.id == 'q0'), isFalse);
    });

    test('corrupt storage is ignored', () async {
      for (final junk in ['not json', '{"a":1}', '[1,2,{"quote":5}]', '']) {
        final n = SavedQuotesNotifier(MemoryStore({kSavedQuotesKey: junk}));
        await n.ready;
        expect(n.state, isEmpty, reason: junk);
      }
    });
  });
}
