import 'dart:convert';

import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/freight/data/freight_prefill.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:factory_finder/features/logistics/data/saved_quotes.dart';
import 'package:factory_finder/features/logistics/screens/results_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

final DateTime _now = DateTime.utc(2026, 10, 15, 12);

ValueKey<String> k(String id) => ValueKey<String>(id);

QuoteRequest _req({Incoterm incoterm = Incoterm.fob, String currency = 'USD'}) => QuoteRequest(
      goodsValue: 10000,
      weightKg: 2000,
      volumeM3: 8,
      origin: const Location(countryCode: 'CN', city: 'Guangzhou'),
      destination: const Location(countryCode: 'IQ', city: 'Baghdad'),
      incoterm: incoterm,
      displayCurrency: currency,
    );

LandedCostQuote _gen(QuoteRequest r, {String lang = 'en'}) =>
    MockQuoteGenerator.generate(r, lang: lang, now: _now);

/// Repository whose first [failures] calculations throw.
class _FlakyRepo implements LogisticsRepository {
  _FlakyRepo(this.failures);

  int failures;
  int calls = 0;

  @override
  Future<LandedCostQuote> calculate(QuoteRequest r, {String lang = 'ar'}) async {
    calls++;
    await Future<void>.delayed(const Duration(milliseconds: 200));
    if (failures > 0) {
      failures--;
      throw StateError('boom');
    }
    return MockQuoteGenerator.generate(r, lang: lang, now: _now);
  }

  @override
  Future<ListingPrefill?> prefill(String listingId) async => null;
}

Future<ProviderContainer> _pump(
  WidgetTester tester, {
  required LandedCostQuote quote,
  QuoteRequest? request,
  List<Override> overrides = const [],
  String lang = 'en',
}) async {
  tester.view.physicalSize = const Size(1080, 14000);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        lastQuoteProvider.overrideWith((ref) => quote),
        lastQuoteRequestProvider.overrideWith((ref) => request),
        ...overrides,
      ],
      child: MaterialApp(locale: Locale(lang), home: const ResultsScreen()),
    ),
  );
  await settle(tester, frames: 3);
  return ProviderScope.containerOf(tester.element(find.byType(ResultsScreen)));
}

void main() {
  setUpWidgetTests();

  testWidgets('every estimated option shows estimate, confidence, as-of and the range note', (tester) async {
    final q = _gen(_req());
    await _pump(tester, quote: q, request: _req());
    final n = q.options.length;
    expect(find.byKey(k('est_badge')), findsNWidgets(n));
    expect(find.byKey(k('est_confidence')), findsNWidgets(n));
    expect(find.byKey(k('est_as_of')), findsNWidgets(n));
    expect(find.text('Confidence: low'), findsNWidgets(n));
    expect(find.text('As of 2026-10'), findsNWidgets(n));
    expect(find.byKey(k('est_range_note')), findsNWidgets(n));
    expect(find.textContaining('not a quote'), findsNWidgets(n));
    expect(find.text('Landed cost (estimate)'), findsNWidgets(n));
    expect(find.byKey(k('est_exact')), findsNothing);
    // The total is a range, never a lone number.
    expect(find.text(q.options.first.total.format()), findsWidgets);
    expect(q.options.first.total.format(), contains('–'));
    expect(tester.takeException(), isNull);
  });

  testWidgets('unlabelled estimates say confidence is not stated instead of inventing one', (tester) async {
    final base = _gen(_req());
    final o = base.options.first;
    final bare = LandedCostQuote(
      id: 'q_bare',
      currency: base.currency,
      createdAt: _now,
      options: [
        LandedCostOption(
          mode: o.mode,
          lines: o.lines,
          total: o.total,
          transitDays: o.transitDays,
        ),
      ],
    );
    await _pump(tester, quote: bare);
    expect(find.text('Confidence: not stated (treat as low)'), findsOneWidget);
    expect(find.byKey(k('est_as_of')), findsNothing);
    expect(find.byKey(k('est_badge')), findsOneWidget);
  });

  testWidgets('an all-exact option is labelled exact, not estimate', (tester) async {
    final q = LandedCostQuote(
      id: 'q_exact',
      currency: 'USD',
      createdAt: _now,
      options: const [
        LandedCostOption(
          mode: TransportMode.air,
          lines: [
            CostLine(
              stage: 'main_leg',
              description: 'forwarder',
              amount: Money(amount: '100.00', currency: 'USD'),
              estimate: false,
              quoted: true,
            ),
          ],
          total: MoneyRange(
            min: Money(amount: '100.00', currency: 'USD'),
            max: Money(amount: '100.00', currency: 'USD'),
          ),
          transitDays: DayRange(min: 2, max: 3),
        ),
      ],
    );
    await _pump(tester, quote: q);
    expect(find.byKey(k('est_exact')), findsOneWidget);
    expect(find.byKey(k('est_badge')), findsNothing);
    expect(find.text('Landed cost'), findsOneWidget);
  });

  testWidgets('incoterm header and "included in supplier price" instead of a fake zero', (tester) async {
    final req = _req(incoterm: Incoterm.cif);
    final q = _gen(req);
    await _pump(tester, quote: q, request: req);
    expect(find.text('Supplier incoterm: CIF'), findsOneWidget);
    await tester.tap(find.text('Cost details').first);
    await settle(tester, frames: 4);
    expect(find.byKey(k('line_included_origin_inland')), findsOneWidget);
    expect(find.byKey(k('line_included_main_leg')), findsOneWidget);
    expect(find.byKey(k('line_included_insurance')), findsOneWidget);
    // Not covered by CIF: the buyer pays it, so the amount is shown.
    expect(find.byKey(k('line_included_duties')), findsNothing);
    expect(find.byKey(k('line_included_destination_inland')), findsNothing);
  });

  testWidgets('FOB: main leg is paid by the buyer and shown with an amount', (tester) async {
    final req = _req();
    await _pump(tester, quote: _gen(req), request: req);
    await tester.tap(find.text('Cost details').first);
    await settle(tester, frames: 4);
    expect(find.byKey(k('line_included_main_leg')), findsNothing);
    expect(find.byKey(k('line_included_origin_handling')), findsOneWidget);
  });

  testWidgets('currency switch recomputes with the same inputs', (tester) async {
    final req = _req();
    final q = _gen(req);
    final c = await _pump(tester, quote: q, request: req);
    expect(find.byKey(k('results_cur_EUR')), findsOneWidget);

    await tester.tap(find.byKey(k('results_cur_EUR')));
    await tester.pump();
    expect(find.byKey(k('results_recalc_progress')), findsOneWidget);
    expect(find.text('Recalculating…'), findsOneWidget);
    await settle(tester, frames: 12);

    expect(find.byKey(k('results_recalc_progress')), findsNothing);
    final next = c.read(lastQuoteProvider)!;
    expect(next.currency, 'EUR');
    expect(c.read(lastQuoteRequestProvider)!.displayCurrency, 'EUR');
    expect(c.read(lastQuoteRequestProvider)!.weightKg, 2000);
    expect(next.options.first.total.min.currency, 'EUR');
    expect(next.options.first.total.format(), isNot(q.options.first.total.format()));
    expect(find.text(next.options.first.total.format()), findsWidgets);
    expect(tester.widget<ChoiceChip>(find.byKey(k('results_cur_EUR'))).selected, isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('failed recompute keeps the old figures, shows an error and retries', (tester) async {
    final repo = _FlakyRepo(1);
    final req = _req();
    final q = _gen(req);
    final c = await _pump(
      tester,
      quote: q,
      request: req,
      overrides: [logisticsRepositoryProvider.overrideWithValue(repo)],
    );
    await tester.tap(find.byKey(k('results_cur_EUR')));
    await settle(tester, frames: 6);
    expect(find.byKey(k('results_recalc_error')), findsOneWidget);
    expect(c.read(lastQuoteProvider)!.currency, 'USD');
    expect(c.read(lastQuoteRequestProvider)!.displayCurrency, 'USD');
    expect(find.textContaining('boom'), findsNothing); // no raw exception text

    await tester.tap(find.byKey(k('results_recalc_retry')));
    await settle(tester, frames: 6);
    expect(repo.calls, 2);
    expect(find.byKey(k('results_recalc_error')), findsNothing);
    expect(c.read(lastQuoteProvider)!.currency, 'EUR');
  });

  testWidgets('without the original request the currency cannot be switched', (tester) async {
    await _pump(tester, quote: _gen(_req()));
    expect(find.byKey(k('results_cur_EUR')), findsNothing);
    // A stale request for another currency is ignored too.
    await _pump(tester, quote: _gen(_req()), request: _req(currency: 'IQD'));
    expect(find.byKey(k('results_cur_EUR')), findsNothing);
  });

  testWidgets('copy summary puts the disclaimer on the clipboard', (tester) async {
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied = (call.arguments as Map)['text'] as String?;
      }
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    final req = _req(incoterm: Incoterm.fca);
    await _pump(tester, quote: _gen(req), request: req);
    await tester.tap(find.byKey(k('results_copy')));
    await settle(tester, frames: 3);
    expect(copied, isNotNull);
    expect(copied, contains('FCA'));
    expect(copied, contains('Confidence: low'));
    expect(copied, contains('As of 2026-10'));
    expect(copied, contains('not a binding quote'));
    expect(find.text('Summary copied'), findsOneWidget);
  });

  testWidgets('save quote persists it and flips the bookmark', (tester) async {
    final store = MemoryStore();
    final req = _req();
    final q = _gen(req);
    final c = await _pump(
      tester,
      quote: q,
      request: req,
      overrides: [keyValueStoreProvider.overrideWithValue(store)],
    );
    expect(find.byIcon(Icons.bookmark_border), findsOneWidget);
    await tester.tap(find.byKey(k('results_save')));
    await settle(tester, frames: 3);
    expect(c.read(savedQuotesProvider).single.quote.id, q.id);
    expect(c.read(savedQuotesProvider).single.incoterm, Incoterm.fob);
    expect(store.data.containsKey(kSavedQuotesKey), isTrue);
    expect(find.byIcon(Icons.bookmark), findsOneWidget);
    expect(find.text('Quote saved'), findsOneWidget);
  });

  testWidgets('a saved quote opens with an age note and no currency switch', (tester) async {
    final q = _gen(_req());
    final store = MemoryStore({
      kSavedQuotesKey: jsonEncode([
        SavedQuote(quote: q, savedAt: DateTime.utc(2026, 9, 1, 12), incoterm: Incoterm.fob).toJson(),
      ]),
    });
    await _pump(
      tester,
      quote: q,
      overrides: [keyValueStoreProvider.overrideWithValue(store)],
    );
    await settle(tester, frames: 3);
    expect(find.textContaining('Saved quote from 2026-09-01'), findsOneWidget);
    expect(find.byKey(k('results_cur_EUR')), findsNothing);
    expect(find.text('Supplier incoterm: FOB'), findsOneWidget);
    expect(find.byKey(k('est_badge')), findsWidgets);
  });

  testWidgets('arabic: estimate wording and numbers render without overflow', (tester) async {
    final q = _gen(_req(), lang: 'ar');
    await _pump(tester, quote: q, request: _req(), lang: 'ar');
    expect(find.text('الكلفة الإجمالية (تقدير)'), findsWidgets);
    expect(find.text('مستوى الثقة: منخفض'), findsWidgets);
    expect(tester.takeException(), isNull);
  });
}
