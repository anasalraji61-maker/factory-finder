import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/assistant/assistant_models.dart';
import 'package:factory_finder/features/assistant/assistant_repository.dart';
import 'package:factory_finder/features/assistant/screens/assistant_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

class _FakeAssistantRepository extends AssistantRepository {
  _FakeAssistantRepository({this.error}) : super(ApiClient(baseUrl: 'http://localhost', isMock: true));

  final Object? error;
  final List<String> asked = [];

  @override
  Future<AssistantAnswer> ask(String text, {String lang = 'ar', Location? destination}) async {
    asked.add(text);
    if (error != null) throw error!;
    return const AssistantAnswer(intent: 'help', text: 'Canned reply');
  }
}

Future<void> _pump(WidgetTester tester, AssistantRepository repo) async {
  tester.view.physicalSize = const Size(360, 2400) * 2.0;
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [assistantRepositoryProvider.overrideWithValue(repo)],
      child: const MaterialApp(home: AssistantScreen()),
    ),
  );
  await settle(tester, frames: 2);
}

Future<void> _dispose(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(milliseconds: 100));
}

void main() {
  setUpWidgetTests();

  testWidgets('starts with the empty state', (tester) async {
    await _pump(tester, _FakeAssistantRepository());
    expect(find.text('How can I help?'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);
    await _dispose(tester);
  });

  testWidgets('sending a question shows it and the reply', (tester) async {
    final repo = _FakeAssistantRepository();
    await _pump(tester, repo);
    await tester.enterText(find.byType(TextField), '  track my shipment  ');
    await tester.tap(find.byIcon(Icons.send_rounded));
    await settle(tester, frames: 3);
    expect(repo.asked, ['track my shipment']);
    expect(find.text('track my shipment'), findsOneWidget);
    expect(find.text('Canned reply'), findsOneWidget);
    expect(find.text('How can I help?'), findsNothing);
    await _dispose(tester);
  });

  testWidgets('blank input is not sent', (tester) async {
    final repo = _FakeAssistantRepository();
    await _pump(tester, repo);
    await tester.enterText(find.byType(TextField), '   ');
    await tester.tap(find.byIcon(Icons.send_rounded));
    await settle(tester, frames: 2);
    expect(repo.asked, isEmpty);
    expect(find.text('How can I help?'), findsOneWidget);
    await _dispose(tester);
  });

  testWidgets('quota error shows the localized limit message', (tester) async {
    final repo = _FakeAssistantRepository(
      error: ApiException(
          status: 429, code: 'quota_exceeded', message: 'x', retryAfterSeconds: 120),
    );
    await _pump(tester, repo);
    await tester.enterText(find.byType(TextField), 'hello');
    await tester.tap(find.byIcon(Icons.send_rounded));
    await settle(tester, frames: 3);
    expect(find.text('You have reached the assistant daily limit. Try again in 2 min.'),
        findsOneWidget);
    await _dispose(tester);
  });

  testWidgets('generic error shows the fallback message', (tester) async {
    await _pump(tester, _FakeAssistantRepository(error: StateError('x')));
    await tester.enterText(find.byType(TextField), 'hello');
    await tester.tap(find.byIcon(Icons.send_rounded));
    await settle(tester, frames: 3);
    expect(find.text('Could not get an answer. Please try again.'), findsOneWidget);
    await _dispose(tester);
  });
}
