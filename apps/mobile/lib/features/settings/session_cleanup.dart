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
    await unregisterPushController(ref.read(pushRegistrationProvider),
        timeout: timeout);
  } catch (_) {
    // Provider scope disposed: sign-out goes on.
  }
}

/// Same as [unregisterPushDeviceBestEffort] for a controller captured earlier
/// (widgets that must not touch `ref` after an await).
Future<void> unregisterPushController(
  PushRegistrationController push, {
  Duration timeout = kPushUnregisterTimeout,
}) async {
  try {
    await push.onLogout().timeout(timeout);
  } catch (_) {
    // Timeout or any failure: sign-out goes on.
  }
}

/// Registers this device for push after a login / session restore without
/// showing the OS permission dialog (only an existing grant registers) and
/// publishes the resulting permission. Best effort: never throws and never
/// blocks longer than [timeout]. Callers must not await it on the login path.
Future<void> registerPushDeviceBestEffort(
  Ref ref, {
  Duration timeout = kPushUnregisterTimeout,
}) async {
  try {
    final perm = await registerPushController(
      ref.read(pushRegistrationProvider),
      locale: ref.read(localeProvider).languageCode,
      timeout: timeout,
    );
    if (perm != null) ref.read(pushPermissionProvider.notifier).state = perm;
  } catch (_) {
    // Provider scope disposed: nothing to publish.
  }
}

/// Controller-level variant of [registerPushDeviceBestEffort]. Returns the
/// permission, or null on timeout / failure.
Future<PushPermission?> registerPushController(
  PushRegistrationController push, {
  required String locale,
  Duration timeout = kPushUnregisterTimeout,
}) async {
  try {
    return await push.onLogin(locale: locale, prompt: false).timeout(timeout);
  } catch (_) {
    return null;
  }
}
