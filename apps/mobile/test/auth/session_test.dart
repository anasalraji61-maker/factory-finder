import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/storage/read_cache.dart';
import 'package:factory_finder/features/notify_prefs/push_registration.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:factory_finder/features/auth/password_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

class _Adapter implements HttpClientAdapter {
  _Adapter(this.handler);

  final ResponseBody Function(RequestOptions o) handler;
  final List<RequestOptions> calls = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(Object body, [int status = 200]) =>
    ResponseBody.fromString(jsonEncode(body), status, headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    });

ResponseBody _empty(int status) => ResponseBody.fromString('', status);

ApiClient _client(_Adapter a, TokenStore tokens) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = a;
  return ApiClient(
    baseUrl: 'http://fake',
    isMock: false,
    dio: dio,
    tokens: tokens,
  );
}

TokenStore _signedIn() {
  final t = TokenStore();
  t.set('old-access', 'old-refresh');
  return t;
}

class _GrantedSource extends NoopPushTokenSource {
  int deleted = 0;
  @override
  Future<PushPermission> permission() async => PushPermission.granted;
  @override
  Future<String?> token() async => 'tok_1';
  @override
  Future<void> deleteToken() async => deleted++;
}

/// Records unregister calls and the access token present at that moment.
class _RecordingDevices extends MockDeviceRepository {
  _RecordingDevices(this.tokens);
  final TokenStore tokens;
  final List<String> unregistered = [];
  final List<String?> accessAtUnregister = [];
  bool fail = false;

  @override
  Future<void> unregister(String deviceId) async {
    unregistered.add(deviceId);
    accessAtUnregister.add(tokens.accessToken);
    if (fail) throw ApiException(status: 500, code: 'x', message: 'x');
    return super.unregister(deviceId);
  }
}

String _ar(String key) => AppStrings.lookup('ar', key);

void main() {
  setUpWidgetTests();

  group('change password stores the new session', () {
    test('fresh token pair replaces the old one', () async {
      final tokens = _signedIn();
      final a = _Adapter((o) => _json(<String, dynamic>{
            'access_token': 'new-access',
            'refresh_token': 'new-refresh',
            'token_type': 'bearer',
            'expires_in': 900,
          }));
      final repo = PasswordRepository(_client(a, tokens));
      await repo.change(currentPassword: 'old', newPassword: 'newpass123');
      expect(tokens.accessToken, 'new-access');
      expect(tokens.refreshToken, 'new-refresh');
      expect(a.calls.single.headers['Authorization'], 'Bearer old-access');
    });

    test('an empty body leaves the tokens alone', () async {
      final tokens = _signedIn();
      final a = _Adapter((o) => _empty(204));
      final repo = PasswordRepository(_client(a, tokens));
      await repo.change(currentPassword: 'old', newPassword: 'newpass123');
      expect(tokens.accessToken, 'old-access');
      expect(tokens.refreshToken, 'old-refresh');
    });

    test('a failed change keeps the tokens', () async {
      final tokens = _signedIn();
      final a = _Adapter((o) => _json(<String, dynamic>{
            'error': {'code': 'reauth_failed', 'message': 'no'},
          }, 403));
      final repo = PasswordRepository(_client(a, tokens));
      await expectLater(
        repo.change(currentPassword: 'bad', newPassword: 'newpass123'),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 403)),
      );
      expect(tokens.accessToken, 'old-access');
    });
  });

  group('logout-all', () {
    test('any 2xx is success', () async {
      for (final status in <int>[200, 204]) {
        final a = _Adapter((o) => status == 204
            ? _empty(204)
            : _json(<String, dynamic>{'revoked': 3}));
        final repo = AuthRepository(_client(a, _signedIn()));
        await repo.logoutAll();
        expect(a.calls.single.path, '/v1/auth/logout-all');
        expect(a.calls.single.method, 'POST');
        expect(a.calls.single.headers['Authorization'], 'Bearer old-access');
      }
    });

    test('a dead session (401 and refresh rejected) counts as success',
        () async {
      final tokens = _signedIn();
      final a = _Adapter((o) => _json(<String, dynamic>{}, 401));
      final repo = AuthRepository(_client(a, tokens));
      await repo.logoutAll();
      expect(tokens.refreshToken, isNull);
    });

    test('a server error is surfaced and tokens are kept', () async {
      final tokens = _signedIn();
      final a = _Adapter((o) => _json(<String, dynamic>{}, 500));
      final repo = AuthRepository(_client(a, tokens));
      await expectLater(
        repo.logoutAll(),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 500)),
      );
      expect(tokens.refreshToken, 'old-refresh');
    });

    test('mock mode completes', () async {
      final repo =
          AuthRepository(ApiClient(baseUrl: 'http://fake', isMock: true));
      await repo.logoutAll();
    });
  });

  group('401 handling', () {
    test('one refresh then one retry; a second 401 does not loop', () async {
      final tokens = _signedIn();
      final a = _Adapter((o) {
        if (o.path == '/v1/auth/refresh') {
          return _json(<String, dynamic>{
            'access_token': 'new-access',
            'refresh_token': 'new-refresh',
          });
        }
        return _json(<String, dynamic>{}, 401);
      });
      final api = _client(a, tokens);
      await expectLater(
        api.get('/v1/me'),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 401)),
      );
      expect(a.calls.map((c) => c.path).toList(),
          <String>['/v1/me', '/v1/auth/refresh', '/v1/me']);
      expect(a.calls.last.headers['Authorization'], 'Bearer new-access');
    });

    test('a refresh token revoked by a password change signs out cleanly',
        () async {
      final tokens = _signedIn();
      var cleared = 0;
      tokens.onCleared = () => cleared++;
      final a = _Adapter((o) => _json(<String, dynamic>{
            'error': {'code': 'invalid_token', 'message': 'revoked'},
          }, 401));
      final api = _client(a, tokens);
      await expectLater(
        api.get('/v1/me'),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 401)),
      );
      expect(a.calls.length, 2);
      expect(tokens.accessToken, isNull);
      expect(tokens.refreshToken, isNull);
      expect(cleared, 1);
    });

    test('a rejected refresh fires onExpired once; transient failure and manual clear do not',
        () async {
      final tokens = _signedIn();
      var expired = 0;
      tokens.onExpired = () => expired++;
      final transient = _client(_Adapter((o) => _json(<String, dynamic>{}, o.path == '/v1/me' ? 401 : 503)), tokens);
      await expectLater(transient.get('/v1/me'), throwsA(isA<ApiException>()));
      expect(expired, 0);
      final rejected = _client(_Adapter((o) => _json(<String, dynamic>{}, 401)), tokens);
      await expectLater(rejected.get('/v1/me'), throwsA(isA<ApiException>()));
      expect(expired, 1);
      tokens.set('a', 'r');
      tokens.clear();
      expect(expired, 1);
    });

    test('session expired message exists in ar and en', () {
      expect(AppStrings.lookup('ar', 'auth.session_expired'), isNot('auth.session_expired'));
      expect(AppStrings.lookup('en', 'auth.session_expired'), contains('expired'));
    });

    test('a transient refresh failure keeps the session', () async {
      final tokens = _signedIn();
      final a = _Adapter((o) => _json(<String, dynamic>{}, o.path == '/v1/me' ? 401 : 503));
      final api = _client(a, tokens);
      await expectLater(
        api.get('/v1/me'),
        throwsA(isA<ApiException>()),
      );
      expect(tokens.refreshToken, 'old-refresh');
      expect(a.calls.length, 2);
    });

    test('concurrent 401s share a single refresh', () async {
      final tokens = _signedIn();
      final a = _Adapter((o) {
        if (o.path == '/v1/auth/refresh') {
          return _json(<String, dynamic>{
            'access_token': 'new-access',
            'refresh_token': 'new-refresh',
          });
        }
        final bearer = o.headers['Authorization'];
        if (bearer == 'Bearer new-access') return _json(<String, dynamic>{'ok': 1});
        return _json(<String, dynamic>{}, 401);
      });
      final api = _client(a, tokens);
      final results = await Future.wait<dynamic>([
        api.get('/v1/a'),
        api.get('/v1/b'),
      ]);
      expect(results.length, 2);
      expect(a.calls.where((c) => c.path == '/v1/auth/refresh').length, 1);
    });

    test('logout while a refresh is in flight is not resurrected', () async {
      final tokens = _signedIn();
      final a = _Adapter((o) {
        if (o.path == '/v1/auth/refresh') {
          tokens.clear(); // user logs out mid-refresh
          return _json(<String, dynamic>{
            'access_token': 'late-access',
            'refresh_token': 'late-refresh',
          });
        }
        return _json(<String, dynamic>{}, 401);
      });
      final api = _client(a, tokens);
      expect(await api.refreshSession(), isFalse);
      expect(tokens.accessToken, isNull);
      expect(tokens.refreshToken, isNull);
    });

    test('a rejected stale refresh does not clear a newer session', () async {
      final tokens = _signedIn();
      final a = _Adapter((o) {
        tokens.set('fresh-access', 'fresh-refresh'); // signed in again
        return _json(<String, dynamic>{}, 401);
      });
      final api = _client(a, tokens);
      expect(await api.refreshSession(), isFalse);
      expect(tokens.refreshToken, 'fresh-refresh');
      expect(tokens.accessToken, 'fresh-access');
    });

    test('429 on refresh keeps the session and does not loop', () async {
      final tokens = _signedIn();
      final a = _Adapter((o) =>
          _json(<String, dynamic>{}, o.path == '/v1/me' ? 401 : 429));
      final api = _client(a, tokens);
      await expectLater(api.get('/v1/me'), throwsA(isA<ApiException>()));
      expect(tokens.refreshToken, 'old-refresh');
      expect(a.calls.length, 2);
    });
  });

  group('sign-out wipes the previous user state', () {
    ProviderContainer build(MemoryStore prefs, _Adapter a) {
      final c = ProviderContainer(overrides: [
        keyValueStoreProvider.overrideWithValue(prefs),
        secureStoreProvider.overrideWithValue(MemoryStore()),
        apiClientProvider.overrideWith(
            (ref) => _client(a, ref.watch(tokenStoreProvider))),
      ]);
      addTearDown(c.dispose);
      return c;
    }

    Future<void> seed(ProviderContainer c) async {
      await c.read(readCacheProvider).put(kSearchCacheSlot, 'q', {'a': 1});
      c.read(destinationProvider.notifier).state =
          const Location(countryCode: 'TR', city: 'Istanbul');
      c.read(displayCurrencyProvider.notifier).state = 'AED';
      c.read(userRoleProvider.notifier).state = UserRole.supplier;
      c.read(localeProvider.notifier).state = const Locale('en');
    }

    Future<void> expectWiped(ProviderContainer c) async {
      expect(await c.read(readCacheProvider).get(kSearchCacheSlot, 'q'), isNull);
      expect(c.read(destinationProvider)?.city, 'Baghdad');
      expect(c.read(displayCurrencyProvider), 'IQD');
      expect(c.read(userRoleProvider), UserRole.buyer);
      expect(c.read(localeProvider), const Locale('en'));
    }

    test('forced expiry (refresh rejected) clears caches and choices', () async {
      final c = build(MemoryStore(), _Adapter((o) => _json(<String, dynamic>{}, 401)));
      final auth = c.read(authProvider.notifier);
      auth.state = const Me(id: 'usr_t', name: 'T');
      c.read(tokenStoreProvider).set('a', 'r');
      await seed(c);
      await expectLater(c.read(apiClientProvider).get('/v1/me'), throwsA(isA<ApiException>()));
      await Future<void>.delayed(Duration.zero);
      expect(c.read(sessionExpiredProvider), isTrue);
      expect(c.read(authProvider), isNull);
      await expectWiped(c);
    });

    test('plain logout clears them too', () async {
      final c = build(MemoryStore(), _Adapter((o) => _json(<String, dynamic>{}, 204)));
      c.read(authProvider.notifier).state = const Me(id: 'usr_t', name: 'T');
      c.read(tokenStoreProvider).set('a', 'r');
      await seed(c);
      await c.read(authProvider.notifier).logout();
      await Future<void>.delayed(Duration.zero);
      await expectWiped(c);
    });

    test('a transient refresh failure does not wipe anything', () async {
      final c = build(MemoryStore(),
          _Adapter((o) => _json(<String, dynamic>{}, o.path == '/v1/me' ? 401 : 503)));
      c.read(authProvider.notifier).state = const Me(id: 'usr_t', name: 'T');
      c.read(tokenStoreProvider).set('a', 'r');
      await seed(c);
      await expectLater(c.read(apiClientProvider).get('/v1/me'), throwsA(isA<ApiException>()));
      await Future<void>.delayed(Duration.zero);
      expect(c.read(destinationProvider)?.city, 'Istanbul');
      expect(await c.read(readCacheProvider).get(kSearchCacheSlot, 'q'), isNotNull);
    });
  });

  group('push device unregister on sign-out', () {
    late _GrantedSource source;
    late _RecordingDevices devices;

    Future<ProviderContainer> build(_Adapter a, {bool signedIn = true}) async {
      source = _GrantedSource();
      final tokens = TokenStore();
      devices = _RecordingDevices(tokens);
      final c = ProviderContainer(overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        secureStoreProvider.overrideWithValue(MemoryStore()),
        tokenStoreProvider.overrideWithValue(tokens),
        apiClientProvider.overrideWith((ref) => _client(a, tokens)),
        pushRegistrationProvider.overrideWith(
            (ref) => PushRegistrationController(source, devices)),
      ]);
      addTearDown(c.dispose);
      if (signedIn) {
        c.read(authProvider.notifier).state = const Me(id: 'usr_t', name: 'T');
        tokens.set('acc', 'ref');
        await c.read(pushRegistrationProvider).onLogin();
        expect(devices.devices, isNotEmpty);
      }
      return c;
    }

    test('logout unregisters before the tokens are cleared', () async {
      final c = await build(_Adapter((o) => _json(<String, dynamic>{}, 204)));
      await c.read(authProvider.notifier).logout();
      expect(devices.unregistered, ['dev_1']);
      expect(devices.accessAtUnregister, ['acc']);
      expect(source.deleted, 1);
      expect(c.read(tokenStoreProvider).accessToken, isNull);
      expect(c.read(authProvider), isNull);
    });

    test('a failing unregister is swallowed and sign-out completes', () async {
      final c = await build(_Adapter((o) => _json(<String, dynamic>{}, 204)));
      devices.fail = true;
      await c.read(authProvider.notifier).logout();
      expect(devices.unregistered, ['dev_1']);
      expect(c.read(authProvider), isNull);
      expect(c.read(tokenStoreProvider).accessToken, isNull);
      expect(source.deleted, 1);
    });

    test('forced expiry drops the push token and swallows errors', () async {
      final c = await build(_Adapter((o) => _json(<String, dynamic>{}, 401)));
      devices.fail = true;
      await expectLater(
          c.read(apiClientProvider).get('/v1/me'), throwsA(isA<ApiException>()));
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      expect(c.read(sessionExpiredProvider), isTrue);
      expect(c.read(authProvider), isNull);
      expect(source.deleted, 1);
    });

    test('logout-all unregisters before the server call', () async {
      final a = _Adapter((o) => _json(<String, dynamic>{}, 204));
      final c = await build(a);
      await c.read(authProvider.notifier).logoutAll();
      expect(devices.unregistered, ['dev_1']);
      expect(devices.accessAtUnregister.first, 'acc');
      expect(a.calls.map((o) => o.path), contains('/v1/auth/logout-all'));
      expect(c.read(authProvider), isNull);
    });

    test('logout-all failure keeps the session and re-registers the device',
        () async {
      final c = await build(_Adapter((o) => _json(<String, dynamic>{}, 500)));
      await expectLater(
          c.read(authProvider.notifier).logoutAll(), throwsA(isA<ApiException>()));
      expect(c.read(authProvider), isNotNull);
      expect(devices.unregistered, ['dev_1']);
      expect(devices.devices.values, ['tok_1']);
    });
  });

  group('restore', () {
    test('a 429 while restoring keeps the stored refresh token', () async {
      final secure = MemoryStore(<String, String>{kRefreshTokenKey: 'saved'});
      final a = _Adapter((o) => _json(<String, dynamic>{}, 429));
      final container = ProviderContainer(overrides: [
        secureStoreProvider.overrideWithValue(secure),
        apiClientProvider.overrideWith((ref) => _client(
              a,
              ref.watch(tokenStoreProvider),
            )),
      ]);
      addTearDown(container.dispose);
      await container.read(authProvider.notifier).restore();
      expect(container.read(authProvider), isNull);
      expect(container.read(tokenStoreProvider).refreshToken, 'saved');
      expect(secure.data[kRefreshTokenKey], 'saved');
    });

    test('a rejected refresh token is wiped from the secure store', () async {
      final secure = MemoryStore(<String, String>{kRefreshTokenKey: 'saved'});
      final a = _Adapter((o) => _json(<String, dynamic>{}, 401));
      final container = ProviderContainer(overrides: [
        secureStoreProvider.overrideWithValue(secure),
        apiClientProvider.overrideWith((ref) => _client(
              a,
              ref.watch(tokenStoreProvider),
            )),
      ]);
      addTearDown(container.dispose);
      await container.read(authProvider.notifier).restore();
      expect(container.read(authProvider), isNull);
      expect(secure.data.containsKey(kRefreshTokenKey), isFalse);
    });
  });

  group('settings: sign out of all devices', () {
    List<Override> signedIn() => [
          authProvider.overrideWith((ref) {
            final c = AuthController(ref);
            c.state = const Me(id: 'usr_t', name: 'Tester');
            return c;
          }),
        ];

    testWidgets('hidden when signed out', (tester) async {
      await pumpApp(tester, location: '/settings', logicalSize: const Size(540, 2400));
      expect(find.byKey(const ValueKey<String>('settings-logout-all')), findsNothing);
      await disposeApp(tester);
    });

    testWidgets('cancel keeps the session, confirm signs out', (tester) async {
      await pumpApp(
        tester,
        location: '/settings',
        logicalSize: const Size(540, 2400),
        overrides: signedIn(),
      );
      final tile = find.byKey(const ValueKey<String>('settings-logout-all'));
      expect(tile, findsOneWidget);

      await tester.ensureVisible(tile);
      await tester.tap(tile);
      await settle(tester, frames: 4);
      expect(find.text(_ar('auth.logout_all.body')), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey<String>('logout-all-cancel')));
      await settle(tester, frames: 4);
      expect(tile, findsOneWidget);

      await tester.tap(tile);
      await settle(tester, frames: 4);
      await tester.tap(find.byKey(const ValueKey<String>('logout-all-confirm')));
      await settle(tester, frames: 8);
      expect(tile, findsNothing);
      await disposeApp(tester);
    });
  });
}
