import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/storage/persistence.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:factory_finder/core/widgets/offline.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

ProviderContainer _container(MemoryStore prefs, {List<Override> extra = const []}) {
  final c = ProviderContainer(overrides: [
    keyValueStoreProvider.overrideWithValue(prefs),
    ...extra,
  ]);
  addTearDown(c.dispose);
  return c;
}

void main() {
  group('digits', () {
    test('western leaves text untouched', () {
      expect(localizeDigits('12 days', DigitStyle.western), '12 days');
      expect(localizeNumber(r'$1,234.50', DigitStyle.western), r'$1,234.50');
    });

    test('arabic-indic converts digits and amount separators', () {
      expect(localizeDigits('5–10 days', DigitStyle.arabicIndic), '٥–١٠ days');
      expect(localizeNumber(r'$1,234.50', DigitStyle.arabicIndic), r'$١٬٢٣٤٫٥٠');
      expect(localizeDigits('', DigitStyle.arabicIndic), '');
    });
  });

  group('settings persistence', () {
    test('defaults: IQD, system theme, western digits, Baghdad', () async {
      final s = await PersistedSettings.load(MemoryStore());
      final c = _container(MemoryStore(), extra: s.overrides());
      expect(c.read(displayCurrencyProvider), 'IQD');
      expect(c.read(themeModeProvider), ThemeMode.system);
      expect(c.read(digitStyleProvider), DigitStyle.western);
      expect(c.read(destinationProvider)?.city, 'Baghdad');
    });

    test('theme, digits, currency and city round trip', () async {
      final prefs = MemoryStore();
      final c1 = _container(prefs);
      c1.read(settingsPersistenceProvider);
      c1.read(themeModeProvider.notifier).state = ThemeMode.dark;
      c1.read(digitStyleProvider.notifier).state = DigitStyle.arabicIndic;
      c1.read(displayCurrencyProvider.notifier).state = 'AED';
      c1.read(destinationProvider.notifier).state =
          const Location(countryCode: 'IQ', city: 'Erbil');
      await Future<void>.delayed(Duration.zero);

      expect(prefs.data[StorageKeys.themeMode], 'dark');
      expect(prefs.data[StorageKeys.digitStyle], 'arabic');

      final s = await PersistedSettings.load(prefs);
      final c2 = _container(MemoryStore(), extra: s.overrides());
      expect(c2.read(themeModeProvider), ThemeMode.dark);
      expect(c2.read(digitStyleProvider), DigitStyle.arabicIndic);
      expect(c2.read(displayCurrencyProvider), 'AED');
      expect(c2.read(destinationProvider)?.city, 'Erbil');
    });

    test('garbage stored values fall back to defaults', () async {
      final s = await PersistedSettings.load(MemoryStore({
        StorageKeys.themeMode: 'purple',
        StorageKeys.digitStyle: '???',
      }));
      expect(s.themeMode, isNull);
      expect(s.digitStyle, isNull);
    });
  });

  group('isNetworkError', () {
    test('network and timeout ApiExceptions without a status', () {
      expect(isNetworkError(ApiException(code: 'network_error', message: 'x')), isTrue);
      expect(isNetworkError(ApiException(code: 'timeout', message: 'x')), isTrue);
    });

    test('HTTP errors and other objects are not network errors', () {
      expect(
        isNetworkError(ApiException(status: 500, code: 'http_500', message: 'x')),
        isFalse,
      );
      expect(
        isNetworkError(ApiException(status: 404, code: 'not_found', message: 'x')),
        isFalse,
      );
      expect(isNetworkError(StateError('boom')), isFalse);
    });
  });
}
