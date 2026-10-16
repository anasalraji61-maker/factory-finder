import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/router/auth_gate.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/onboarding/intro_state.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../widgets/test_app.dart';

String _ar(String key) => AppStrings.lookup('ar', key);
String _en(String key) => AppStrings.lookup('en', key);
String _loc(GoRouter r) => r.routerDelegate.currentConfiguration.uri.toString();

/// Fresh install: gate enabled, intro not done.
Future<(GoRouter, ProviderContainer, MemoryStore)> _pumpFresh(
  WidgetTester tester, {
  bool introDone = false,
  bool onboardingDone = true,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final store = MemoryStore();
  final container = ProviderContainer(overrides: [
    keyValueStoreProvider.overrideWithValue(store),
    secureStoreProvider.overrideWithValue(MemoryStore()),
    introDoneProvider.overrideWith((ref) => introDone),
    onboardingCompletedProvider.overrideWith((ref) => onboardingDone),
  ]);
  addTearDown(container.dispose);
  final router = createAppRouter(
    showOnboarding: !onboardingDone,
    auth: AuthGate.fromContainer(container),
  );
  await tester.pumpWidget(UncontrolledProviderScope(
    container: container,
    child: FactoryFinderApp(router: router),
  ));
  await settle(tester);
  return (router, container, store);
}

void main() {
  setUpWidgetTests();

  test('loadIntroDone reads the persisted flag', () async {
    expect(await loadIntroDone(MemoryStore()), isFalse);
    expect(await loadIntroDone(MemoryStore({kIntroDoneKey: '1'})), isTrue);
    expect(kIntroDoneKey, 'onboarding.v1.done');
  });

  testWidgets('fresh install lands on page 1 in Arabic, before login', (tester) async {
    final (router, _, _) = await _pumpFresh(tester);
    expect(_loc(router), '/intro');
    expect(find.text(_ar('intro.p1.title')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('intro-dots')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('intro-skip')), findsOneWidget);
    // Deep link to a protected page is still held at the intro.
    router.go('/deals');
    await settle(tester);
    expect(_loc(router), '/intro');
    await disposeApp(tester);
  });

  testWidgets('three pages, estimate label, Get started persists the flag', (tester) async {
    final (router, container, store) = await _pumpFresh(tester);
    await tester.tap(find.byKey(const ValueKey<String>('intro-next')));
    await settle(tester);
    expect(find.text(_ar('intro.p2.title')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('intro-estimate-chip')), findsOneWidget);
    expect(find.text(_ar('intro.p2.estimate_note')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey<String>('intro-next')));
    await settle(tester);
    expect(find.text(_ar('intro.p3.title')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('intro-next')), findsNothing);

    await tester.tap(find.byKey(const ValueKey<String>('intro-start')));
    await settle(tester, frames: 12);
    expect(container.read(introDoneProvider), isTrue);
    expect(store.data[kIntroDoneKey], '1');
    expect(_loc(router), '/discover');
    expect(find.byType(NavigationBar), findsOneWidget);
    await disposeApp(tester);
  });

  testWidgets('Skip finishes the intro and never shows it again', (tester) async {
    final (router, container, store) = await _pumpFresh(tester);
    await tester.tap(find.byKey(const ValueKey<String>('intro-skip')));
    await settle(tester, frames: 12);
    expect(store.data[kIntroDoneKey], '1');
    expect(_loc(router), '/discover');
    container.read(authResolvedProvider.notifier).state = true;
    // Navigating to protected content now hits the auth gate, not the intro.
    router.go('/deals');
    await settle(tester);
    expect(_loc(router), startsWith('/login'));
    expect(container.read(introDoneProvider), isTrue);
    await disposeApp(tester);
  });

  testWidgets('fresh install continues into the preferences flow', (tester) async {
    final (router, _, _) = await _pumpFresh(tester, onboardingDone: false);
    expect(_loc(router), '/intro');
    await tester.tap(find.byKey(const ValueKey<String>('intro-skip')));
    await settle(tester, frames: 12);
    expect(_loc(router), '/onboarding');
    await disposeApp(tester);
  });

  testWidgets('language toggle switches the app language', (tester) async {
    final (_, container, _) = await _pumpFresh(tester);
    expect(container.read(localeProvider).languageCode, 'ar');
    await tester.tap(find.byKey(const ValueKey<String>('intro-lang')));
    await settle(tester);
    expect(container.read(localeProvider).languageCode, 'en');
    expect(find.text(_en('intro.p1.title')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey<String>('intro-lang')));
    await settle(tester);
    expect(container.read(localeProvider).languageCode, 'ar');
    await disposeApp(tester);
  });

  testWidgets('settings About replays the intro and returns', (tester) async {
    await pumpApp(
      tester,
      location: '/settings',
      logicalSize: const Size(540, 4000),
    );
    final tile = find.byKey(const ValueKey<String>('settings-replay-intro'));
    await tester.ensureVisible(tile);
    expect(find.text(_ar('intro.replay')), findsOneWidget);
    await tester.tap(tile);
    await settle(tester, frames: 12);
    expect(find.text(_ar('intro.p1.title')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey<String>('intro-skip')));
    await settle(tester, frames: 12);
    expect(find.text(_ar('intro.p1.title')), findsNothing);
    expect(find.text(_ar('settings.title')), findsWidgets);
    await disposeApp(tester);
  });
}
