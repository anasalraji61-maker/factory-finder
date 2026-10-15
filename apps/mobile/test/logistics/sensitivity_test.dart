import 'dart:convert';
import 'dart:io';

import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:factory_finder/features/logistics/screens/results_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

Map<String, dynamic> _fixture() => Map<String, dynamic>.from(
    jsonDecode(File('test/fixtures/live/quote_sensitivity.json').readAsStringSync()) as Map);

Future<void> _pumpResults(WidgetTester tester, LandedCostQuote quote, String lang) async {
  tester.view.physicalSize = const Size(1080, 4800);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [lastQuoteProvider.overrideWith((ref) => quote)],
      child: MaterialApp(
        locale: Locale(lang),
        supportedLocales: const [Locale('ar'), Locale('en')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: const ResultsScreen(),
      ),
    ),
  );
  await settle(tester, frames: 3);
}

void main() {
  setUpWidgetTests();

  group('models', () {
    test('sensitivity and quote warnings parse', () {
      final q = LandedCostQuote.fromJson(_fixture());
      expect(q.warnings.single, startsWith('De minimis'));
      final s = q.options.first.sensitivity!;
      expect(s.currency, 'USD');
      expect(s.freight!.low.amount, '170.00');
      expect(s.freight!.shockPct, '20');
      expect(s.fx!.goodsCurrency, 'CNY');
      expect(s.combined!.high.amount, '205.00');
      expect(s.note, contains('not forecasts'));
      // Duty line keeps its "as of / confidence / range" text.
      final duty = q.options.first.lines.firstWhere((l) => l.stage == 'duties');
      expect(duty.description, contains('as of 2026-09-01'));
      // Round trip keeps the new blocks.
      final again = LandedCostQuote.fromJson(q.toJson());
      expect(again.options.first.sensitivity!.fx!.base.amount, '185.00');
      expect(again.warnings, hasLength(1));
    });

    test('absent or malformed sensitivity is tolerated', () {
      final j = _fixture();
      (j['options'] as List).first['sensitivity'] = 'oops';
      expect(LandedCostQuote.fromJson(j).options.first.sensitivity, isNull);
      (j['options'] as List).first.remove('sensitivity');
      j.remove('warnings');
      final q = LandedCostQuote.fromJson(j);
      expect(q.options.first.sensitivity, isNull);
      expect(q.warnings, isEmpty);
      final partial = CostSensitivity.tryParse({
        'currency': 'USD',
        'freight': {'low': {'amount': '1', 'currency': 'USD'}},
      });
      expect(partial!.freight!.high.amount, '0');
      expect(CostSensitivity.tryParse({'currency': 'USD'})!.isEmpty, isTrue);
    });

    test('mock quotes carry ordered bands', () {
      final q = MockQuoteGenerator.generate(
        const QuoteRequest(
          goodsValue: 10000,
          weightKg: 2000,
          volumeM3: 8,
          origin: Location(countryCode: 'CN', city: 'Guangzhou'),
          destination: Location(countryCode: 'IQ', city: 'Baghdad'),
        ),
        lang: 'en',
      );
      expect(q.warnings, isEmpty);
      for (final o in q.options) {
        final s = o.sensitivity!;
        for (final b in [s.freight!, s.fx!, s.combined!]) {
          expect(b.low.value, lessThanOrEqualTo(b.base.value));
          expect(b.base.value, lessThanOrEqualTo(b.high.value));
        }
      }
      final small = MockQuoteGenerator.generate(
        const QuoteRequest(
          goodsValue: 80,
          weightKg: 2,
          volumeM3: 0.01,
          origin: Location(countryCode: 'CN', city: 'Guangzhou'),
          destination: Location(countryCode: 'IQ', city: 'Baghdad'),
        ),
        lang: 'en',
      );
      expect(small.warnings, hasLength(1));
    });
  });

  group('results screen', () {
    testWidgets('warnings and collapsible what-if section', (tester) async {
      final q = LandedCostQuote.fromJson(_fixture());
      await _pumpResults(tester, q, 'en');
      expect(find.textContaining('De minimis'), findsOneWidget);

      final title = find.text('What if? (cost sensitivity)');
      await tester.scrollUntilVisible(title, 200);
      expect(find.text('Freight rate change'), findsNothing);
      await tester.tap(title);
      await settle(tester, frames: 5);
      await tester.scrollUntilVisible(find.text('Freight rate change'), 200);
      expect(find.text('Freight rate change'), findsOneWidget);
      expect(find.text('Exchange-rate change'), findsOneWidget);
      expect(find.text('Both combined'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('no sensitivity block when the server sent none', (tester) async {
      final j = _fixture();
      (j['options'] as List).first.remove('sensitivity');
      await _pumpResults(tester, LandedCostQuote.fromJson(j), 'ar');
      expect(find.text('ماذا لو؟ (حساسية الكلفة)'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('Arabic renders RTL with the what-if section (540x2400)', (tester) async {
      final q = LandedCostQuote.fromJson(_fixture());
      await _pumpResults(tester, q, 'ar');
      expect(
        Directionality.of(tester.element(find.byType(ResultsScreen))),
        TextDirection.rtl,
      );
      final title = find.text('ماذا لو؟ (حساسية الكلفة)');
      await tester.scrollUntilVisible(title, 200);
      expect(title, findsOneWidget);
      expect(find.text('What if? (cost sensitivity)'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });
}
