import 'dart:convert';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class StorageKeys {
  static const onboardingDone = 'onboarding_done';
  static const locale = 'locale';
  static const currency = 'display_currency';
  static const destination = 'destination';
  static const serverUrl = 'server_url';
  static const refreshToken = 'refresh_token';
}

/// Settings read once before `runApp`.
class PersistedSettings {
  const PersistedSettings({
    this.onboardingDone = false,
    this.locale,
    this.currency,
    this.destination,
    this.hasDestination = false,
    this.serverUrl,
  });

  final bool onboardingDone;
  final String? locale;
  final String? currency;

  /// Stored destination; [hasDestination] distinguishes "user cleared it"
  /// (stored as empty string) from "never stored".
  final Location? destination;
  final bool hasDestination;
  final String? serverUrl;

  static Future<PersistedSettings> load(KeyValueStore store) async {
    Future<String?> safe(String k) async {
      try {
        return await store.get(k);
      } catch (_) {
        return null;
      }
    }

    final loc = await safe(StorageKeys.locale);
    final dest = await safe(StorageKeys.destination);
    Location? destination;
    var hasDest = false;
    if (dest != null) {
      hasDest = true;
      if (dest.isNotEmpty) {
        try {
          destination = Location.fromJson(
              Map<String, dynamic>.from(jsonDecode(dest) as Map));
        } catch (_) {
          hasDest = false;
        }
      }
    }
    return PersistedSettings(
      onboardingDone: await safe(StorageKeys.onboardingDone) == '1',
      locale: (loc == 'ar' || loc == 'en') ? loc : null,
      currency: await safe(StorageKeys.currency),
      destination: destination,
      hasDestination: hasDest,
      serverUrl: await safe(StorageKeys.serverUrl),
    );
  }

  /// Provider overrides that seed initial state from these settings.
  List<Override> overrides() => [
        onboardingCompletedProvider.overrideWith((ref) => onboardingDone),
        if (locale != null)
          localeProvider.overrideWith((ref) => Locale(locale!)),
        if (currency != null && currency!.isNotEmpty)
          displayCurrencyProvider.overrideWith((ref) => currency!),
        if (hasDestination)
          destinationProvider.overrideWith((ref) => destination),
        if (serverUrl != null && serverUrl!.isNotEmpty)
          serverUrlProvider.overrideWith((ref) => serverUrl!),
      ];
}

/// Writes setting changes to the store. Watched by the root widget.
final settingsPersistenceProvider = Provider<void>((ref) {
  final store = ref.watch(keyValueStoreProvider);

  void write(String key, String? value) {
    final f = value == null ? store.remove(key) : store.set(key, value);
    f.catchError((Object _) {});
  }

  ref.listen<bool>(onboardingCompletedProvider, (_, v) {
    write(StorageKeys.onboardingDone, v ? '1' : null);
  });
  ref.listen<Locale>(localeProvider, (_, v) {
    write(StorageKeys.locale, v.languageCode);
  });
  ref.listen<String>(displayCurrencyProvider, (_, v) {
    write(StorageKeys.currency, v);
  });
  ref.listen<Location?>(destinationProvider, (_, v) {
    write(StorageKeys.destination, v == null ? '' : jsonEncode(v.toJson()));
  });
  ref.listen<String>(serverUrlProvider, (_, v) {
    write(StorageKeys.serverUrl, v);
  });
});
