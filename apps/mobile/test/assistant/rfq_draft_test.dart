import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/assistant/assistant_models.dart';
import 'package:factory_finder/features/assistant/assistant_repository.dart';
import 'package:factory_finder/features/assistant/widgets/assistant_card_view.dart';
import 'package:factory_finder/features/requests/data/rfq_prefill.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

Map<String, dynamic> _draftJson({Map<String, Object?>? refs}) => {
      'type': 'rfq_draft',
      'title': 'Purchase request draft',
      'title_ar': 'مسودة طلب شراء',
      'severity': 'warning',
      'rows': [
        {'key': 'product', 'label': 'Product', 'label_ar': 'المنتج', 'value': 'LED lights', 'value_ar': 'LED lights'},
        {'key': 'quantity', 'label': 'Quantity', 'label_ar': 'الكمية', 'value': null, 'value_ar': null},
      ],
      'refs': refs ??
          {
            'deep_link': '/requests/new',
            'draft': 'true',
            'missing': 'quantity,destination',
            'prefill_product': 'LED lights',
            'prefill_quantity': '500',
            'prefill_unit': 'kg',
            'prefill_destination': 'Istanbul',
            'prefill_target_price': '12.5 USD',
          },
    };

Future<void> _pumpCard(
  WidgetTester tester,
  AssistantCard card,
  String lang,
  List<String> routes,
) async {
  await tester.pumpWidget(
    MaterialApp(
      locale: Locale(lang),
      supportedLocales: const [Locale('ar'), Locale('en')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
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

  group('model parse', () {
    test('rfq_draft is a known type and offers the form route', () {
      final c = AssistantCard.tryParse(_draftJson())!;
      expect(c.isKnownType, isTrue);
      expect(c.rows[1].value, isNull);
      final route = c.actions.single.route;
      final uri = Uri.parse(route);
      expect(uri.path, '/requests/new');
      expect(uri.queryParameters, {
        'title': 'LED lights',
        'qty': '500',
        'unit': 'kg',
        'price': '12.5',
        'currency': 'USD',
        'dest': 'TR',
        'city': 'Istanbul',
      });
    });

    test('wrong deep link or empty refs give no unsafe route', () {
      final bad = AssistantCard.tryParse(_draftJson(refs: {'deep_link': 'https://evil.example'}))!;
      expect(bad.actions, isEmpty);
      final empty = AssistantCard.tryParse(_draftJson(refs: {'deep_link': '/requests/new'}))!;
      expect(empty.actions.single.route, '/requests/new');
    });

    test('invalid prefill values are dropped', () {
      final p = RfqPrefill.fromRefs({
        'prefill_product': 'x',
        'prefill_quantity': '-3',
        'prefill_unit': 'bananas',
        'prefill_destination': 'Atlantis',
        'prefill_target_price': 'abc USD',
      });
      expect(p.isEmpty, isTrue);
    });

    test('meter alias, Arabic destination and query round trip', () {
      final p = RfqPrefill.fromRefs({
        'prefill_product': 'Steel pipes',
        'prefill_quantity': '20',
        'prefill_unit': 'meter',
        'prefill_destination': 'بغداد',
      });
      expect(p.unit, 'm');
      expect(p.destination!.countryCode, 'IQ');
      expect(p.destination!.city, 'Baghdad');
      final back = RfqPrefill.fromQuery(p.toQuery());
      expect(back.title, 'Steel pipes');
      expect(back.destination!.city, 'Baghdad');
    });

    test('unknown card type still parses', () {
      final c = AssistantCard.tryParse({'type': 'future_thing', 'refs': {'a': 1}})!;
      expect(c.isKnownType, isFalse);
      expect(c.actions, isEmpty);
    });

    test('mock answer carries a draft card', () {
      final a = mockAssistantAnswer('make a purchase request', lang: 'en');
      expect(a.intent, 'create_rfq_draft');
      expect(a.cards.single.type, 'rfq_draft');
      expect(a.cards.single.actions, hasLength(1));
    });
  });

  group('card widget', () {
    testWidgets('button navigates in Arabic and English', (tester) async {
      final card = AssistantCard.tryParse(_draftJson())!;
      final routes = <String>[];
      await _pumpCard(tester, card, 'en', routes);
      expect(find.text('Purchase request draft'), findsOneWidget);
      await tester.tap(find.text('Open request form'));
      expect(routes.single, startsWith('/requests/new?'));
      await _pumpCard(tester, card, 'ar', routes);
      expect(find.text('فتح نموذج الطلب'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('prefill applied to form', () {
    testWidgets('query params seed the fields, nothing is submitted', (tester) async {
      final route = AssistantCard.tryParse(_draftJson())!.actions.single.route;
      await pumpApp(tester, logicalSize: const Size(540, 2400), location: route);
      expect(find.text('LED lights'), findsOneWidget);
      expect(find.text('500'), findsOneWidget);
      expect(find.text('12.5'), findsOneWidget);
      expect(
        find.byWidgetPredicate((w) => w is CountryFlag && w.countryCode == 'TR'),
        findsOneWidget,
      );
      final selected = tester
          .widgetList<ChoiceChip>(find.byType(ChoiceChip))
          .where((c) => c.selected)
          .map((c) => (c.label as Text).data)
          .toList();
      expect(selected.any((t) => t == 'kg' || t == 'كغم'), isTrue);
      expect(selected, contains('USD'));
      await disposeApp(tester);
    });
  });
}
