import 'package:factory_finder/features/assistant/screens/assistant_screen.dart';
import 'package:factory_finder/features/discover/widgets/assistant_entry_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

void main() {
  setUpWidgetTests();

  test('assistantRouteFor encodes the question and falls back to the bare route', () {
    expect(assistantRouteFor(null), '/assistant');
    expect(assistantRouteFor('  '), '/assistant');
    expect(assistantRouteFor('a b'), '/assistant?q=a+b');
  });

  testWidgets('Discover shows the assistant card and opens it prefilled', (tester) async {
    await pumpApp(tester, location: '/discover', logicalSize: const Size(540, 2400));
    expect(find.byKey(const ValueKey<String>('assistant-entry')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('feed-entry-card')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('feed-entry')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey<String>('assistant-example-discover.assistant.ex2')));
    await settle(tester);
    expect(find.widgetWithText(TextField, 'Where is my shipment now?'), findsOneWidget);
    await disposeApp(tester);
  });

  testWidgets('AssistantScreen prefills initialQuestion without sending', (tester) async {
    await tester.pumpWidget(const ProviderScope(
      child: MaterialApp(home: AssistantScreen(initialQuestion: ' hello ')),
    ));
    await settle(tester, frames: 2);
    expect(find.widgetWithText(TextField, 'hello'), findsOneWidget);
    await disposeApp(tester);
  });

  testWidgets('Discover feed card opens the feed', (tester) async {
    await pumpApp(tester, location: '/discover', logicalSize: const Size(540, 2400));
    await tester.tap(find.byKey(const ValueKey<String>('feed-entry-card')));
    await settle(tester);
    expect(find.byKey(const ValueKey<String>('assistant-entry')), findsNothing);
    await disposeApp(tester);
  });
}
