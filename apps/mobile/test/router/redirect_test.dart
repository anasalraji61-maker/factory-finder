import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/router/auth_gate.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../widgets/test_app.dart';

String _ar(String key) => AppStrings.lookup('ar', key);

class _Fake extends ChangeNotifier {
  bool signedIn = false;
  bool resolved = true;

  void update({bool? signedIn, bool? resolved}) {
    this.signedIn = signedIn ?? this.signedIn;
    this.resolved = resolved ?? this.resolved;
    notifyListeners();
  }

  AuthGate get gate => AuthGate(
        isSignedIn: () => signedIn,
        isResolved: () => resolved,
        refresh: this,
      );
}

String _loc(GoRouter r) => r.routerDelegate.currentConfiguration.uri.toString();

Future<GoRouter> _pump(WidgetTester tester, _Fake fake) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final router = createAppRouter(auth: fake.gate);
  await tester.pumpWidget(ProviderScope(
    overrides: [
      keyValueStoreProvider.overrideWithValue(MemoryStore()),
      secureStoreProvider.overrideWithValue(MemoryStore()),
    ],
    child: FactoryFinderApp(router: router),
  ));
  await settle(tester);
  return router;
}

void main() {
  setUpWidgetTests();

  group('sanitizeReturnPath', () {
    test('accepts internal paths', () {
      expect(sanitizeReturnPath('/deals'), '/deals');
      expect(sanitizeReturnPath('/deals/d1?x=1&y=2'), '/deals/d1?x=1&y=2');
      expect(sanitizeReturnPath('/listing/lst_001'), '/listing/lst_001');
    });

    test('rejects external, scheme-relative and malformed targets', () {
      for (final bad in <String?>[
        null,
        '',
        'deals',
        '//evil.com',
        '///evil.com',
        'https://evil.com',
        'javascript:alert(1)',
        '/\\evil.com',
        '/ /evil.com',
        '/\t/evil.com',
        '/%5Cevil.com',
        '/%2F%2Fevil.com',
        '/login',
        '/login?from=/deals',
        '/register',
        '/onboarding',
        '/%',
      ]) {
        expect(sanitizeReturnPath(bad), isNull, reason: '$bad');
      }
      expect(sanitizeReturnPath('/${'a' * 3000}'), isNull);
    });
  });

  group('appRedirect', () {
    String? r(String loc, {bool signedIn = false, bool resolved = true}) =>
        appRedirect(uri: Uri.parse(loc), signedIn: signedIn, resolved: resolved);

    test('protected + signed out goes to login with encoded from', () {
      expect(r('/deals'), '/login?from=%2Fdeals');
      expect(r('/deals/d1?x=1'), '/login?from=%2Fdeals%2Fd1%3Fx%3D1');
      expect(r('/settings/privacy/blocked'),
          '/login?from=%2Fsettings%2Fprivacy%2Fblocked');
    });

    test('public routes, tab roots and lookalikes are untouched', () {
      for (final p in [
        '/discover',
        '/messages',
        '/profile',
        '/login',
        '/settings',
        '/dealsx',
        '/listing/1',
      ]) {
        expect(r(p), isNull, reason: p);
      }
    });

    test('signed in or still restoring never redirects', () {
      expect(r('/deals', signedIn: true), isNull);
      expect(r('/deals', resolved: false), isNull);
    });
  });

  group('router', () {
    testWidgets('signed-out deep link to protected route lands on login',
        (tester) async {
      final fake = _Fake();
      final router = await _pump(tester, fake);
      router.go('/deals');
      await settle(tester);
      expect(_loc(router), '/login?from=%2Fdeals');
      expect(find.text(_ar('auth.login')), findsWidgets);
      await disposeApp(tester);
    });

    testWidgets('no redirect while the session is still being restored',
        (tester) async {
      final fake = _Fake()..resolved = false;
      final router = await _pump(tester, fake);
      router.go('/deals');
      await settle(tester);
      expect(_loc(router), '/deals');
      // Restore finishes signed out: now it bounces to login.
      fake.update(resolved: true);
      await settle(tester);
      expect(_loc(router), '/login?from=%2Fdeals');
      await disposeApp(tester);
    });

    testWidgets('session loss on a protected page redirects to login',
        (tester) async {
      final fake = _Fake()..signedIn = true;
      final router = await _pump(tester, fake);
      router.go('/watchlist');
      await settle(tester);
      expect(_loc(router), '/watchlist');
      fake.update(signedIn: false);
      await settle(tester);
      expect(_loc(router), '/login?from=%2Fwatchlist');
      await disposeApp(tester);
    });

    testWidgets('login restores the original path', (tester) async {
      final container = ProviderContainer(overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        secureStoreProvider.overrideWithValue(MemoryStore()),
      ]);
      addTearDown(container.dispose);
      container.read(authResolvedProvider.notifier).state = true;
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final router = createAppRouter(auth: AuthGate.fromContainer(container));
      await tester.pumpWidget(UncontrolledProviderScope(
        container: container,
        child: FactoryFinderApp(router: router),
      ));
      await settle(tester);

      router.go('/deals?tab=open');
      await settle(tester);
      expect(_loc(router), startsWith('/login?from='));

      final fields = find.byType(TextFormField);
      await tester.enterText(fields.at(0), 'buyer@example.com');
      await tester.enterText(fields.at(1), 'password123');
      await tester.tap(find.widgetWithText(FilledButton, _ar('auth.login')).first);
      await tester.pump(const Duration(milliseconds: 400));
      await settle(tester);
      expect(container.read(authProvider), isNotNull);
      expect(_loc(router), '/deals?tab=open');
      await disposeApp(tester);
    });

    testWidgets('malicious from is ignored after login', (tester) async {
      final container = ProviderContainer(overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        secureStoreProvider.overrideWithValue(MemoryStore()),
      ]);
      addTearDown(container.dispose);
      container.read(authResolvedProvider.notifier).state = true;
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final router = createAppRouter(auth: AuthGate.fromContainer(container));
      await tester.pumpWidget(UncontrolledProviderScope(
        container: container,
        child: FactoryFinderApp(router: router),
      ));
      await settle(tester);

      router.go('/login?from=${Uri.encodeQueryComponent('//evil.com')}');
      await settle(tester);
      final fields = find.byType(TextFormField);
      await tester.enterText(fields.at(0), 'buyer@example.com');
      await tester.enterText(fields.at(1), 'password123');
      await tester.tap(find.widgetWithText(FilledButton, _ar('auth.login')).first);
      await tester.pump(const Duration(milliseconds: 400));
      await settle(tester);
      expect(_loc(router), '/discover');
      await disposeApp(tester);
    });

    testWidgets('unknown route shows localized not-found with home button',
        (tester) async {
      final fake = _Fake();
      final router = await _pump(tester, fake);
      router.go('/definitely/not/a/route');
      await settle(tester);
      expect(find.text(_ar('common.not_found.title')), findsWidgets);
      expect(find.text(_ar('common.not_found.body')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey<String>('not-found-home')));
      await settle(tester);
      expect(_loc(router), '/discover');
      expect(find.byType(NavigationBar), findsOneWidget);
      await disposeApp(tester);
    });

    testWidgets('Android back from another tab root returns to Discover',
        (tester) async {
      final fake = _Fake();
      final router = await _pump(tester, fake);
      router.go('/profile');
      await settle(tester);
      expect(_loc(router), '/profile');
      await tester.binding.handlePopRoute();
      await settle(tester);
      expect(_loc(router), '/discover');
      await disposeApp(tester);
    });
  });
}
