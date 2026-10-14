import 'dart:convert';
import 'dart:io';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/assistant/assistant_models.dart';
import 'package:factory_finder/features/assistant/assistant_repository.dart';
import 'package:factory_finder/features/assistant/assistant_strings.dart';
import 'package:factory_finder/features/assistant/widgets/assistant_card_view.dart';
import 'package:factory_finder/features/tracking/screens/tracking_detail_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

AssistantAnswer _answer() =>
    AssistantAnswer.fromJson(Map<String, dynamic>.from(_load('assistant_cards') as Map));

Future<void> _pumpCard(
  WidgetTester tester,
  AssistantCard card,
  String lang,
  List<String> routes,
) async {
  await tester.pumpWidget(
    MaterialApp(
      locale: Locale(lang),
      home: Scaffold(
        body: SingleChildScrollView(
          child: AssistantCardView(card: card, onNavigate: routes.add),
        ),
      ),
    ),
  );
  await settle(tester, frames: 2);
}

void main() {
  setUpWidgetTests();

  group('parsing', () {
    test('cards, unknown types and malformed entries', () {
      final a = _answer();
      expect(a.intent, 'shipment_status');
      expect(a.textFiltered, isTrue);
      // The bare string is dropped; the unknown type is kept.
      expect(a.cards.map((c) => c.type), [
        'shipment_status',
        'listing_comparison',
        'hologram',
        'notice',
        'deal_status',
      ]);
      expect(a.cards[2].isKnownType, isFalse);
      // Deal card: missing title_ar/value, a non-map row is skipped.
      final deal = a.cards.last;
      expect(deal.rows, hasLength(1));
      expect(deal.rows.first.valueFor('ar'), isNull);
      expect(deal.titleFor('ar'), 'Deal');
    });

    test('locale-aware labels with fallback', () {
      final c = _answer().cards.first;
      expect(c.titleFor('ar'), 'الشحنة MSKU1234567');
      expect(c.titleFor('en'), 'Shipment MSKU1234567');
      expect(c.rows[0].valueFor('ar'), 'في الطريق');
      expect(c.rows[0].valueFor('en'), 'In transit');
      // No value_ar: Arabic falls back to the English value.
      expect(c.rows[1].valueFor('ar'), '2026-10-26');
      final cmp = _answer().cards[1];
      expect(cmp.columns[1].label('ar'), 'Watch');
      expect(cmp.rows.first.values, ['USD 5', 'USD 12']);
      expect(cmp.rows.first.highlight, 0);
    });

    test('actions only for plain ids', () {
      final a = _answer();
      expect(a.cards[0].actions.single.route, '/logistics/tracking/shp_1a2b');
      // listing_b "../evil" is rejected.
      expect(a.cards[1].actions.map((x) => x.route), ['/listing/lst_1']);
      expect(a.cards[2].actions, isEmpty);
      expect(a.cards[3].actions.single.route, '/login');
      expect(a.cards[4].actions.single.route, '/deals');
    });

    test('response without cards/warnings still parses', () {
      final a = AssistantAnswer.fromJson({'intent': 'help', 'answer_text': 'hi'});
      expect(a.cards, isEmpty);
      expect(a.warnings, isEmpty);
      expect(a.textFiltered, isFalse);
    });

    test('mock answers carry cards', () {
      expect(mockAssistantAnswer('track my shipment', lang: 'en').cards.single.type,
          'shipment_status');
      expect(mockAssistantAnswer('قارن العرضين').cards.single.type, 'listing_comparison');
      expect(mockAssistantAnswer('hello').cards, isEmpty);
    });
  });

  group('quota error', () {
    final e = _load('error_assistant_quota') as Map;
    final ex = ApiException(
      status: 429,
      code: (e['error'] as Map)['code'] as String,
      message: 'x',
      retryAfterSeconds: 5400,
    );

    test('429 maps to a localized message with the wait', () {
      expect(isQuotaError(ex), isTrue);
      expect(assistantErrorText(ex, 'en'), contains('daily limit'));
      expect(assistantErrorText(ex, 'en'), contains('2 h'));
      expect(assistantErrorText(ex, 'ar'), contains('الحد اليومي'));
      expect(assistantErrorText(ex, 'ar'), contains('2 ساعة'));
    });

    test('without Retry-After and for other errors', () {
      final noWait = ApiException(status: 429, code: 'http_429', message: 'x');
      expect(assistantErrorText(noWait, 'en'), contains('Try again in a while'));
      expect(assistantErrorText(StateError('boom'), 'en'), contains('Could not get an answer'));
      expect(isQuotaError(StateError('x')), isFalse);
    });
  });

  group('card widget', () {
    testWidgets('renders Arabic and English, buttons navigate', (tester) async {
      final card = _answer().cards.first;
      final routes = <String>[];
      await _pumpCard(tester, card, 'ar', routes);
      expect(find.text('الشحنة MSKU1234567'), findsOneWidget);
      expect(find.text('في الطريق'), findsOneWidget);
      expect(find.text('البيانات قد تكون قديمة.'), findsOneWidget);
      await tester.ensureVisible(find.text('فتح الشحنة'));
      await tester.tap(find.text('فتح الشحنة'));
      expect(routes, ['/logistics/tracking/shp_1a2b']);

      await _pumpCard(tester, card, 'en', routes);
      expect(find.text('Shipment MSKU1234567'), findsOneWidget);
      expect(find.text('In transit'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('comparison and unknown cards render without errors', (tester) async {
      final a = _answer();
      final routes = <String>[];
      await _pumpCard(tester, a.cards[1], 'en', routes);
      expect(find.text('Earbuds'), findsOneWidget);
      expect(find.text('USD 12'), findsOneWidget);
      expect(find.text('View listing 1'), findsOneWidget);
      expect(find.text('View listing 2'), findsNothing);
      await tester.tap(find.text('View listing 1'));
      expect(routes, ['/listing/lst_1']);

      await _pumpCard(tester, a.cards[2], 'ar', routes);
      expect(find.text('بطاقة مستقبلية'), findsOneWidget);
      await _pumpCard(tester, const AssistantCard(type: 'x'), 'ar', routes);
      expect(tester.takeException(), isNull);
    });
  });

  testWidgets('chat: ask, see a card, open the shipment', (tester) async {
    await pumpApp(tester, location: '/assistant');
    expect(find.text('المساعد الذكي'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'تتبع شحنتي');
    await tester.tap(find.byIcon(Icons.send_rounded));
    await settle(tester, frames: 12);
    expect(find.text('الشحنة MSKU1234567'), findsOneWidget);

    await tester.ensureVisible(find.text('فتح الشحنة'));
    await tester.tap(find.text('فتح الشحنة'));
    await settle(tester, frames: 10);
    expect(find.byType(TrackingDetailScreen), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
