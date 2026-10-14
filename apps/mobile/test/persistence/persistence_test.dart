import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/storage/persistence.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

class FakeAuth implements AuthRepository {
  FakeAuth({this.result, this.error});
  final Me? result;
  final Object? error;
  int restoreCalls = 0;

  @override
  Future<Me?> restoreSession() async {
    restoreCalls++;
    if (error != null) throw error!;
    return result;
  }

  @override
  void logout() {}

  @override
  Future<Me> login({String? email, String? phone, required String password}) =>
      throw UnimplementedError();

  @override
  Future<Me> register({
    String? email,
    String? phone,
    required String password,
    required String name,
  }) =>
      throw UnimplementedError();

  @override
  Future<Me> claimSupplier(Me current, String? supplierId) =>
      throw UnimplementedError();
}

ProviderContainer makeContainer(
  MemoryStore prefs,
  MemoryStore secure, {
  AuthRepository? auth,
  List<Override> extra = const [],
}) {
  final c = ProviderContainer(overrides: [
    keyValueStoreProvider.overrideWithValue(prefs),
    secureStoreProvider.overrideWithValue(secure),
    if (auth != null) authRepositoryProvider.overrideWithValue(auth),
    ...extra,
  ]);
  addTearDown(c.dispose);
  return c;
}

void main() {
  test('settings round trip through the store', () async {
    final prefs = MemoryStore();
    final c1 = makeContainer(prefs, MemoryStore());
    c1.read(settingsPersistenceProvider);
    c1.read(localeProvider.notifier).state = const Locale('en');
    c1.read(displayCurrencyProvider.notifier).state = 'EUR';
    c1.read(destinationProvider.notifier).state =
        const Location(countryCode: 'TR', city: 'Istanbul');
    c1.read(serverUrlProvider.notifier).state = 'https://api.example.com';
    c1.read(onboardingCompletedProvider.notifier).state = true;
    await Future<void>.delayed(Duration.zero);

    final s = await PersistedSettings.load(prefs);
    expect(s.onboardingDone, isTrue);
    expect(s.locale, 'en');
    expect(s.currency, 'EUR');
    expect(s.destination?.city, 'Istanbul');

    final c2 = makeContainer(prefs, MemoryStore(), extra: s.overrides());
    expect(c2.read(localeProvider).languageCode, 'en');
    expect(c2.read(displayCurrencyProvider), 'EUR');
    expect(c2.read(destinationProvider)?.countryCode, 'TR');
    expect(c2.read(serverUrlProvider), 'https://api.example.com');
    expect(c2.read(onboardingCompletedProvider), isTrue);
  });

  test('cleared destination persists as null; empty store keeps defaults',
      () async {
    final prefs = MemoryStore();
    final c1 = makeContainer(prefs, MemoryStore());
    c1.read(settingsPersistenceProvider);
    c1.read(destinationProvider.notifier).state = null;
    await Future<void>.delayed(Duration.zero);
    final s = await PersistedSettings.load(prefs);
    final c2 = makeContainer(prefs, MemoryStore(), extra: s.overrides());
    expect(c2.read(destinationProvider), isNull);

    final empty = await PersistedSettings.load(MemoryStore());
    final c3 = makeContainer(MemoryStore(), MemoryStore(), extra: empty.overrides());
    expect(c3.read(localeProvider).languageCode, 'ar');
    expect(c3.read(destinationProvider)?.city, 'Baghdad');
    expect(c3.read(onboardingCompletedProvider), isFalse);
  });

  test('refresh token is written to the secure store and removed on logout',
      () async {
    final secure = MemoryStore();
    final c = makeContainer(MemoryStore(), secure);
    c.read(tokenStoreProvider).set('a', 'r1');
    await Future<void>.delayed(Duration.zero);
    expect(secure.data[kRefreshTokenKey], 'r1');
    c.read(authProvider.notifier).logout();
    await Future<void>.delayed(Duration.zero);
    expect(secure.data.containsKey(kRefreshTokenKey), isFalse);
  });

  test('session restore success', () async {
    final secure = MemoryStore({kRefreshTokenKey: 'r1'});
    final fake = FakeAuth(result: const Me(id: 'u1', name: 'Ann'));
    final c = makeContainer(MemoryStore(), secure, auth: fake);
    await c.read(authProvider.notifier).restore();
    expect(fake.restoreCalls, 1);
    expect(c.read(authProvider)?.id, 'u1');
    expect(c.read(tokenStoreProvider).refreshToken, 'r1');
  });

  test('session restore failure clears tokens', () async {
    for (final fake in [
      FakeAuth(result: null),
      FakeAuth(error: ApiException(status: 401, code: 'x', message: 'no')),
    ]) {
      final secure = MemoryStore({kRefreshTokenKey: 'r1'});
      final c = makeContainer(MemoryStore(), secure, auth: fake);
      await c.read(authProvider.notifier).restore();
      await Future<void>.delayed(Duration.zero);
      expect(c.read(authProvider), isNull);
      expect(c.read(tokenStoreProvider).refreshToken, isNull);
      expect(secure.data.containsKey(kRefreshTokenKey), isFalse);
    }
  });

  test('no stored token: restore does nothing', () async {
    final fake = FakeAuth(result: const Me(id: 'u1', name: 'Ann'));
    final c = makeContainer(MemoryStore(), MemoryStore(), auth: fake);
    await c.read(authProvider.notifier).restore();
    expect(fake.restoreCalls, 0);
    expect(c.read(authProvider), isNull);
  });

  group('onboarding gate', () {
    setUpAll(() {
      registerFeatureStrings();
      GoogleFonts.config.allowRuntimeFetching = false;
      debugDisableNetworkImages = true;
    });
    tearDownAll(() => debugDisableNetworkImages = false);

    Future<String> startPath(WidgetTester tester, MemoryStore prefs) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final s = await PersistedSettings.load(prefs);
      final router = createAppRouter(showOnboarding: !s.onboardingDone);
      await tester.pumpWidget(ProviderScope(
        overrides: [
          keyValueStoreProvider.overrideWithValue(prefs),
          secureStoreProvider.overrideWithValue(MemoryStore()),
          ...s.overrides(),
        ],
        child: FactoryFinderApp(router: router),
      ));
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      final path = router.routeInformationProvider.value.uri.path;
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 100));
      return path;
    }

    testWidgets('shown when flag unset', (tester) async {
      expect(await startPath(tester, MemoryStore()), '/onboarding');
    });

    testWidgets('skipped when flag set', (tester) async {
      final path = await startPath(
          tester, MemoryStore({StorageKeys.onboardingDone: '1'}));
      expect(path, '/discover');
    });
  });
}
