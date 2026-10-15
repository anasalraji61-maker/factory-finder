import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/freight/data/freight_prefill.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

ValueKey<String> k(String id) => ValueKey<String>(id);

const String _calc = 'احسب الكلفة';
const String _badHs = 'رمز HS يجب أن يكون من 6 إلى 10 أرقام';
const String _badVolume = 'الحجم غير صالح (رقم عشري مثل 2.5)';
const String _badWeight = 'الوزن يجب أن يكون رقماً أكبر من صفر';
const String _badValue = 'القيمة يجب أن تكون رقماً أكبر من صفر';
const String _results = 'نتائج التسعير';

class _FlakyRepo implements LogisticsRepository {
  _FlakyRepo(this.failures);

  int failures;
  int calls = 0;

  @override
  Future<LandedCostQuote> calculate(QuoteRequest r, {String lang = 'ar'}) async {
    calls++;
    if (failures > 0) {
      failures--;
      throw StateError('secret-internal-detail');
    }
    return MockQuoteGenerator.generate(r, lang: lang);
  }

  @override
  Future<ListingPrefill?> prefill(String listingId) async => null;
}

Finder _fields() => find.byType(TextField);

String _text(WidgetTester tester, int i) =>
    tester.widget<TextField>(_fields().at(i)).controller!.text;

Future<void> _fill(
  WidgetTester tester, {
  String price = '10',
  String qty = '100',
  String weight = '120',
  String volume = '0.5',
  String hs = '',
}) async {
  await tester.enterText(_fields().at(0), price);
  await tester.enterText(_fields().at(1), qty);
  await tester.enterText(_fields().at(2), weight);
  await tester.enterText(_fields().at(3), volume);
  if (hs.isNotEmpty) await tester.enterText(_fields().at(4), hs);
  await tester.pump();
}

Future<void> _calculate(WidgetTester tester) async {
  await tester.ensureVisible(find.text(_calc));
  await tester.tap(find.text(_calc));
  await settle(tester, frames: 3);
}

ProviderContainer _container(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(Scaffold).first));

void main() {
  setUpWidgetTests();

  testWidgets('HS code must be 6-10 digits: error shown, nothing sent', (tester) async {
    await pumpApp(tester, location: '/logistics/calculator');
    await _fill(tester, hs: '12345');
    await _calculate(tester);
    expect(find.text(_badHs), findsWidgets);
    expect(find.text(_results), findsNothing);
    expect(_container(tester).read(lastQuoteRequestProvider), isNull);

    // Editing the field clears the field error (the snackbar with the same
    // text is dismissed first so only the field error is being checked).
    ScaffoldMessenger.of(tester.element(find.byType(Scaffold).first)).clearSnackBars();
    await settle(tester, frames: 6);
    expect(find.text(_badHs), findsOneWidget);
    await tester.enterText(_fields().at(4), '123456');
    await tester.pump();
    expect(find.text(_badHs), findsNothing);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('invalid volume is reported instead of silently dropped', (tester) async {
    await pumpApp(tester, location: '/logistics/calculator');
    await _fill(tester, volume: '1.2.3');
    await _calculate(tester);
    expect(find.text(_badVolume), findsWidgets);
    expect(find.text(_results), findsNothing);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('empty form flags value and weight; zero is rejected', (tester) async {
    await pumpApp(tester, location: '/logistics/calculator');
    await _calculate(tester);
    expect(find.text(_badValue), findsOneWidget);
    expect(find.text(_badWeight), findsOneWidget);
    expect(find.text(_results), findsNothing);

    ScaffoldMessenger.of(tester.element(find.byType(Scaffold).first)).clearSnackBars();
    await settle(tester, frames: 6);
    await _fill(tester, price: '0', weight: '0');
    await _calculate(tester);
    expect(find.text(_results), findsNothing);
    expect(find.text(_badWeight), findsOneWidget);
    await disposeApp(tester);
  });

  testWidgets('decimals are sent exactly as typed (grouping, arabic digits, HS dots)', (tester) async {
    await pumpApp(tester, location: '/logistics/calculator');
    await _fill(tester, price: '0.1', qty: '3', weight: '١٫٢٥٠', volume: '0.00004', hs: '8518.30');
    await _calculate(tester);
    await settle(tester, frames: 12);
    expect(find.text(_results), findsOneWidget);

    final req = _container(tester).read(lastQuoteRequestProvider)!;
    final goods = req.toJson()['goods'] as Map;
    expect((goods['total_value'] as Map)['amount'], '0.30'); // 0.1 * 3, not 0.30000000000000004
    expect(goods['total_weight_kg'], '1.25');
    expect(goods['total_volume_m3'], '0.00004');
    expect(goods['hs_code'], '851830');
    await disposeApp(tester);
  });

  testWidgets('goods currency and incoterm reach the request', (tester) async {
    // Tall surface: the lazy ListView must have built the lower chips.
    await pumpApp(tester, location: '/logistics/calculator', logicalSize: const Size(540, 3000));
    await _fill(tester);
    await tester.ensureVisible(find.byKey(k('calc_goods_cur_EUR')));
    await tester.tap(find.byKey(k('calc_goods_cur_EUR')));
    await tester.pump();
    await tester.ensureVisible(find.text('DDP'));
    await tester.tap(find.text('DDP'));
    await tester.pump();
    await _calculate(tester);
    await settle(tester, frames: 12);
    final req = _container(tester).read(lastQuoteRequestProvider)!;
    expect(req.goodsCurrency, 'EUR');
    expect(req.incoterm, Incoterm.ddp);
    final json = req.toJson();
    expect(((json['goods'] as Map)['total_value'] as Map)['currency'], 'EUR');
    expect(json['supplier_incoterm'], 'DDP');
    await disposeApp(tester);
  });

  testWidgets('mode filter reaches the request and the quote', (tester) async {
    // Tall surface: the modes section is at the bottom of a lazy ListView.
    await pumpApp(tester, location: '/logistics/calculator', logicalSize: const Size(540, 3000));
    await _fill(tester);
    await tester.ensureVisible(find.text('جوي'));
    await tester.tap(find.text('جوي'));
    await tester.pump();
    await _calculate(tester);
    await settle(tester, frames: 12);
    final c = _container(tester);
    expect(c.read(lastQuoteRequestProvider)!.modes, {TransportMode.air});
    expect(c.read(lastQuoteProvider)!.options.map((o) => o.mode).toSet(), {TransportMode.air});
    await disposeApp(tester);
  });

  testWidgets('a failed calculation shows a friendly error with retry, never the raw exception', (tester) async {
    final repo = _FlakyRepo(1);
    await pumpApp(
      tester,
      location: '/logistics/calculator',
      overrides: [logisticsRepositoryProvider.overrideWithValue(repo)],
    );
    await _fill(tester);
    await _calculate(tester);
    expect(find.text('تعذّر حساب الكلفة. تحقق من الاتصال وأعد المحاولة.'), findsOneWidget);
    expect(find.textContaining('secret-internal-detail'), findsNothing);
    expect(find.text(_results), findsNothing);

    await tester.tap(find.text('إعادة المحاولة'));
    await settle(tester, frames: 10);
    expect(repo.calls, 2);
    expect(find.text(_results), findsOneWidget);
    await disposeApp(tester);
  });

  testWidgets('listing prefill fills exact totals and recomputes weight with quantity', (tester) async {
    await pumpApp(tester, location: '/logistics/calculator?listing_id=lst_001');
    await settle(tester, frames: 6);
    expect(_text(tester, 0), '5.5');
    expect(_text(tester, 1), '500');
    expect(_text(tester, 2), '30'); // 0.06 kg x 500
    expect(_text(tester, 3), '0.1'); // 0.0002 m3 x 500
    expect(_text(tester, 4), '851830');
    expect(find.byKey(k('calc_prefill_failed')), findsNothing);

    await tester.enterText(_fields().at(1), '3');
    await tester.pump();
    expect(_text(tester, 2), '0.18');
    expect(_text(tester, 3), '0.0006');
    await disposeApp(tester);
  });

  testWidgets('unknown listing keeps the form usable and tells the user', (tester) async {
    await pumpApp(tester, location: '/logistics/calculator?listing_id=does_not_exist');
    await settle(tester, frames: 6);
    expect(find.byKey(k('calc_prefill_failed')), findsOneWidget);
    expect(_text(tester, 0), '');
    await disposeApp(tester);
  });
}
