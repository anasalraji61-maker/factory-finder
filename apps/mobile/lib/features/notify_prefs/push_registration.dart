import 'dart:async';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// OS-level push permission as the app understands it.
enum PushPermission { unknown, granted, denied }

/// Platform seam (firebase_messaging lives behind this; tests use a fake).
abstract class PushTokenSource {
  /// 'android' | 'ios' (the only platforms in the contract).
  String get platform;
  Future<PushPermission> permission();

  /// Shows the OS prompt when still undecided.
  Future<PushPermission> requestPermission();
  Future<String?> token();

  /// Invalidates the token locally so this install stops receiving pushes.
  Future<void> deleteToken();
  Stream<String> get onTokenRefresh;
}

/// Default until Firebase is wired: never grants, never yields a token.
class NoopPushTokenSource implements PushTokenSource {
  @override
  String get platform => 'android';
  @override
  Future<PushPermission> permission() async => PushPermission.unknown;
  @override
  Future<PushPermission> requestPermission() async => PushPermission.unknown;
  @override
  Future<String?> token() async => null;
  @override
  Future<void> deleteToken() async {}
  @override
  Stream<String> get onTokenRefresh => const Stream<String>.empty();
}

/// /v1/devices (contracts/openapi/notifications.yaml).
abstract class DeviceRepository {
  /// Upsert by token; returns the device id.
  Future<String> register({
    required String platform,
    required String token,
    required String locale,
  });
  Future<void> unregister(String deviceId);
}

class LiveDeviceRepository implements DeviceRepository {
  LiveDeviceRepository(this._api);
  final ApiClient _api;

  @override
  Future<String> register({
    required String platform,
    required String token,
    required String locale,
  }) async {
    final r = await _api.post('/v1/devices', body: <String, dynamic>{
      'platform': platform,
      'token': token,
      'locale': locale == 'en' ? 'en' : 'ar',
    });
    final id = r is Map ? r['id'] : null;
    if (id is! String || id.isEmpty) {
      throw ApiException(status: 502, code: 'bad_response', message: 'No device id');
    }
    return id;
  }

  @override
  Future<void> unregister(String deviceId) async {
    await _api.delete('/v1/devices/${Uri.encodeComponent(deviceId)}');
  }
}

class MockDeviceRepository implements DeviceRepository {
  final Map<String, String> devices = {}; // id -> token
  int _n = 0;

  @override
  Future<String> register({
    required String platform,
    required String token,
    required String locale,
  }) async {
    for (final e in devices.entries) {
      if (e.value == token) return e.key;
    }
    final id = 'dev_${++_n}';
    devices[id] = token;
    return id;
  }

  @override
  Future<void> unregister(String deviceId) async {
    devices.remove(deviceId);
  }
}

/// Owns the FCM token lifecycle: register after login, re-register on token
/// refresh, unregister on logout. Never throws to callers (push is
/// best-effort and must not block auth flows).
class PushRegistrationController {
  PushRegistrationController(this._source, this._devices);
  final PushTokenSource _source;
  final DeviceRepository _devices;

  String? _deviceId;
  String? _registeredToken;
  int _generation = 0; // bumped on logout so late registrations are dropped
  StreamSubscription<String>? _refreshSub;
  PushPermission _permission = PushPermission.unknown;

  /// Server device id while registered.
  String? get deviceId => _deviceId;
  PushPermission get permission => _permission;
  bool get isRegistered => _deviceId != null;

  /// Call after a successful login / session restore. When [prompt] is false
  /// the OS dialog is not shown (only an existing grant registers).
  Future<PushPermission> onLogin({String locale = 'ar', bool prompt = true}) async {
    final gen = ++_generation;
    try {
      var perm = await _source.permission();
      if (perm == PushPermission.unknown && prompt) {
        perm = await _source.requestPermission();
      }
      if (gen != _generation) return _permission;
      _permission = perm;
      if (perm != PushPermission.granted) {
        // Denied: make sure nothing stays registered for this user.
        await _unregisterServerSide();
        return perm;
      }
      await _refreshSub?.cancel();
      _refreshSub = _source.onTokenRefresh.listen((t) {
        unawaited(_register(t, locale, gen));
      });
      final t = await _source.token();
      if (t != null && t.isNotEmpty) await _register(t, locale, gen);
    } catch (_) {
      // Best-effort.
    }
    return _permission;
  }

  Future<void> _register(String token, String locale, int gen) async {
    if (gen != _generation || token.isEmpty || token == _registeredToken) return;
    try {
      final id = await _devices.register(
        platform: _source.platform,
        token: token,
        locale: locale,
      );
      if (gen != _generation) {
        // Logged out while the request was in flight: undo it.
        try {
          await _devices.unregister(id);
        } catch (_) {}
        return;
      }
      final old = _deviceId;
      _deviceId = id;
      _registeredToken = token;
      if (old != null && old != id) {
        // Rotated token: drop the stale registration.
        try {
          await _devices.unregister(old);
        } catch (_) {}
      }
    } catch (_) {
      // Retried on next login / token refresh.
    }
  }

  Future<void> _unregisterServerSide() async {
    final id = _deviceId;
    if (id == null) return;
    try {
      await _devices.unregister(id);
    } on ApiException catch (e) {
      // Already gone is success; anything else keeps nothing locally.
      if (e.status != 404 && e.status != 401) rethrow;
    }
    _deviceId = null;
    _registeredToken = null;
  }

  /// Call BEFORE the session tokens are cleared (the DELETE needs auth).
  /// Always cancels listeners and deletes the local token, even if the server
  /// call fails.
  Future<void> onLogout() async {
    _generation++;
    final sub = _refreshSub;
    _refreshSub = null;
    await sub?.cancel();
    try {
      await _unregisterServerSide();
    } catch (_) {
      // Server cleanup failed: the local token is still invalidated below,
      // so the stale registration receives nothing once FCM rejects it.
    }
    _deviceId = null;
    _registeredToken = null;
    try {
      await _source.deleteToken();
    } catch (_) {}
  }
}

final pushTokenSourceProvider = Provider<PushTokenSource>((ref) => NoopPushTokenSource());

final pushRegistrationProvider = Provider<PushRegistrationController>((ref) {
  // Intentionally not watching apiClientProvider (it is rebuilt on auth epoch
  // changes, which would drop the device id right when logout needs it).
  final api = ref.read(apiClientProvider);
  final repo =
      api.isMock ? MockDeviceRepository() : LiveDeviceRepository(api);
  return PushRegistrationController(ref.watch(pushTokenSourceProvider), repo);
});

/// Latest known OS permission, for the prefs screen banner.
final pushPermissionProvider = StateProvider<PushPermission>((ref) => PushPermission.unknown);
