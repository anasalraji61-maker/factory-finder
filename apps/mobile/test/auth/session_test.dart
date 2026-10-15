import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
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
