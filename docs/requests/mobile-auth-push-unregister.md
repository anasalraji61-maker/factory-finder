# mobile-auth: unregister FCM device on logout

Owner: apps/mobile auth (lib/features/auth). `PushRegistrationController` (lib/features/notify_prefs/push_registration.dart, provider `pushRegistrationProvider`) is ready but not wired.

- After a successful login / session restore: `ref.read(pushRegistrationProvider).onLogin(locale: ...)`, and set `pushPermissionProvider` to its result.
- In `AuthNotifier.logout()` / logout-all / forced sign-out: `await ref.read(pushRegistrationProvider).onLogout()` BEFORE clearing tokens (DELETE /v1/devices/{id} needs auth). It never throws.
- Replace `pushTokenSourceProvider` with a firebase_messaging-backed `PushTokenSource` once Firebase is configured (default is a no-op).

## Status: logout part DONE (2026-10-15)

- `AuthController.logout()` is now `Future<void>`: calls `unregisterPushDeviceBestEffort` (settings/session_cleanup.dart, 5 s timeout, never throws) BEFORE clearing tokens. `logoutAll()` unregisters before the server revoke and re-registers the device if the revoke fails. Forced expiry (`onExpired`) drops the local push token and listeners; the server DELETE can only be best-effort there because the tokens are already cleared by then.
- Account deletion (privacy_screen.dart) now calls `unregisterPushController` BEFORE `repo.deleteAccount` and `await auth.logout()`; if the delete fails (still signed in) the device is registered again. DONE (2026-10-15).
- `onLogin(prompt: false)` is wired after login, register and session restore through `registerPushDeviceBestEffort` (settings/session_cleanup.dart: fire-and-forget, 5 s timeout, never throws, no OS dialog, publishes `pushPermissionProvider`). DONE (2026-10-15). The OS permission prompt itself should be triggered from a user-facing place (e.g. the notification prefs screen) via `onLogin()` with the default `prompt: true`.
- Still open: the firebase_messaging-backed `PushTokenSource` (needs Firebase config).
- Tests: test/auth/session_test.dart, test/settings/session_cleanup_test.dart, test/privacy/privacy_test.dart.
