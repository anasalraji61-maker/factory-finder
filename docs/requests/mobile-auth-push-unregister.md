# mobile-auth: unregister FCM device on logout

Owner: apps/mobile auth (lib/features/auth). `PushRegistrationController` (lib/features/notify_prefs/push_registration.dart, provider `pushRegistrationProvider`) is ready but not wired.

- After a successful login / session restore: `ref.read(pushRegistrationProvider).onLogin(locale: ...)`, and set `pushPermissionProvider` to its result.
- In `AuthNotifier.logout()` / logout-all / forced sign-out: `await ref.read(pushRegistrationProvider).onLogout()` BEFORE clearing tokens (DELETE /v1/devices/{id} needs auth). It never throws.
- Replace `pushTokenSourceProvider` with a firebase_messaging-backed `PushTokenSource` once Firebase is configured (default is a no-op).
