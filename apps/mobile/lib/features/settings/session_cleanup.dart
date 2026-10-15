import 'dart:async';

import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/storage/read_cache.dart';
import 'package:factory_finder/features/notify_prefs/push_registration.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Destination used before the user picks one (mirrors `destinationProvider`).
const Location kDefaultDestination =
    Location(countryCode: 'IQ', city: 'Baghdad');

/// Default display currency (mirrors `displayCurrencyProvider`).
const String kDefaultDisplayCurrency = 'IQD';

/// Wipes everything that belongs to the person who just signed out, so the
/// next person on this device never sees it: the offline read cache (search
/// and home feed slots), the chosen destination, the display currency and the
/// onboarding role. Device display preferences (language, theme, digit style)
/// and the onboarding-completed flag are kept on a plain sign-out.
///
/// Never throws. Call after the auth state was cleared.
Future<void> clearSignedOutUserState({
  required ReadCache cache,
  required StateController<Location?> destination,
  required StateController<String> currency,
  required StateController<UserRole> role,
}) async {
  try {
    destination.state = kDefaultDestination;
    currency.state = kDefaultDisplayCurrency;
    role.state = UserRole.buyer;
  } catch (_) {
    // Provider scope already disposed.
  }
  try {
    await cache.clear();
  } catch (_) {
    // best effort
  }
}

/// Same wipe, reading the providers from a provider-side [ref]. Used by the
/// auth controller so forced expiry, logout, logout-all and account deletion
/// all clear the previous user's state even when no screen drives it. Never
/// throws (a disposed scope is ignored). Idempotent with the screen call sites.
Future<void> clearSignedOutUserStateFromRef(Ref ref) async {
  try {
    await clearSignedOutUserState(
      cache: ref.read(readCacheProvider),
      destination: ref.read(destinationProvider.notifier),
      currency: ref.read(displayCurrencyProvider.notifier),
      role: ref.read(userRoleProvider.notifier),
    );
  } catch (_) {
    // Provider scope already disposed.
  }
}

/// Convenience wrapper reading the providers from a widget [ref].
Future<void> clearSignedOutUserStateOf(WidgetRef ref) =>
    clearSignedOutUserState(
      cache: ref.read(readCacheProvider),
      destination: ref.read(destinationProvider.notifier),
      currency: ref.read(displayCurrencyProvider.notifier),
      role: ref.read(userRoleProvider.notifier),
    );

/// Longest a sign-out waits for the push-device cleanup.
const Duration kPushUnregisterTimeout = Duration(seconds: 5);

/// Unregisters this device's push token (server + local). Best effort: never
/// throws and never blocks longer than [timeout], so it cannot fail or stall
/// a sign-out. Call BEFORE the session tokens are cleared (the server DELETE
/// needs auth).
Future<void> unregisterPushDeviceBestEffort(
  Ref ref, {
  Duration timeout = kPushUnregisterTimeout,
}) async {
  try {
    await ref.read(pushRegistrationProvider).onLogout().timeout(timeout);
  } catch (_) {
    // Provider scope disposed, timeout or any failure: sign-out goes on.
  }
}
