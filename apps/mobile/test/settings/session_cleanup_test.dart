import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/storage/persistence.dart';
import 'package:factory_finder/core/storage/read_cache.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:factory_finder/features/privacy/privacy_screen.dart';
import 'package:factory_finder/features/settings/session_cleanup.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

ProviderContainer _container(MemoryStore prefs) {
  final c = ProviderContainer(overrides: [
    keyValueStoreProvider.overrideWithValue(prefs),
  ]);
  addTearDown(c.dispose);
  return c;
}

Future<void> _wipe(ProviderContainer c) => clearSignedOutUserState(
      cache: c.read(readCacheProvider),
      destination: c.read(destinationProvider.notifier),
      currency: c.read(displayCurrencyProvider.notifier),
      role: c.read(userRoleProvider.notifier),
    );

void main() {
  group('sign-out wipe', () {
    test('clears read cache, destination, currency and role', () async {
      final prefs = MemoryStore();
      final c = _container(prefs);
      final cache = c.read(readCacheProvider);
      await cache.put(kSearchCacheSlot, 'q', {'a': 1});
      await cache.put(kHomeFeedCacheSlot, 'p1', {'b': 2});
      c.read(destinationProvider.notifier).state =
          const Location(countryCode: 'TR', city: 'Istanbul');
      c.read(displayCurrencyProvider.notifier).state = 'AED';
      c.read(userRoleProvider.notifier).state = UserRole.supplier;

      await _wipe(c);

      expect(await cache.get(kSearchCacheSlot, 'q'), isNull);
      expect(await cache.get(kHomeFeedCacheSlot, 'p1'), isNull);
      expect(prefs.data.containsKey(kSearchCacheSlot), isFalse);
      expect(prefs.data.containsKey(kHomeFeedCacheSlot), isFalse);
      expect(c.read(destinationProvider)?.city, 'Baghdad');
      expect(c.read(displayCurrencyProvider), kDefaultDisplayCurrency);
      expect(c.read(userRoleProvider), UserRole.buyer);
    });

    test('keeps device preferences and the onboarding flag', () async {
      final prefs = MemoryStore();
      final c = _container(prefs);
      c.read(settingsPersistenceProvider);
      c.read(onboardingCompletedProvider.notifier).state = true;
      c.read(localeProvider.notifier).state = const Locale('en');
      c.read(themeModeProvider.notifier).state = ThemeMode.dark;
      c.read(digitStyleProvider.notifier).state = DigitStyle.arabicIndic;
      await _wipe(c);
      await Future<void>.delayed(Duration.zero);

      expect(prefs.data[StorageKeys.onboardingDone], '1');
      expect(prefs.data[StorageKeys.locale], 'en');
      expect(prefs.data[StorageKeys.themeMode], 'dark');
      expect(prefs.data[StorageKeys.digitStyle], 'arabic');
    });

    test('persisted destination is reset too, so a restart shows no prior city',
        () async {
      final prefs = MemoryStore();
      final c1 = _container(prefs);
      c1.read(settingsPersistenceProvider);
      c1.read(destinationProvider.notifier).state =
          const Location(countryCode: 'TR', city: 'Ankara');
      await Future<void>.delayed(Duration.zero);
      await _wipe(c1);
      await Future<void>.delayed(Duration.zero);

      final s = await PersistedSettings.load(prefs);
      expect(s.destination?.city, 'Baghdad');
    });

    test('a failing store never throws', () async {
      final c = ProviderContainer(overrides: [
        keyValueStoreProvider.overrideWithValue(_ThrowingStore()),
      ]);
      addTearDown(c.dispose);
      await _wipe(c);
      expect(c.read(destinationProvider)?.city, 'Baghdad');
    });
  });

  group('account deletion key list', () {
    test('covers every persisted setting and cache slot', () {
      expect(kLocalStateKeys, containsAll(<String>[
        StorageKeys.onboardingDone,
        StorageKeys.locale,
        StorageKeys.currency,
        StorageKeys.destination,
        StorageKeys.themeMode,
        StorageKeys.digitStyle,
        StorageKeys.refreshToken,
        ...kReadCacheSlots,
      ]));
    });
  });
}

class _ThrowingStore extends MemoryStore {
  @override
  Future<void> remove(String key) => throw StateError('disk full');

  @override
  Future<String?> get(String key) => throw StateError('disk full');

  @override
  Future<void> set(String key, String value) => throw StateError('disk full');
}
