import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/auth/auth_validators.dart';
import 'package:factory_finder/features/auth/password_repository.dart';
import 'package:flutter/material.dart';
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

ResponseBody _json(Object body, [int status = 200, Map<String, List<String>>? h]) =>
    ResponseBody.fromString(jsonEncode(body), status, headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
      ...?h,
    });

PasswordRepository _live(_Adapter a) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = a;
  return PasswordRepository(
    ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio),
  );
}

PasswordRepository _mock() =>
    PasswordRepository(ApiClient(baseUrl: 'http://fake', isMock: true));

String _ar(String key) => AppStrings.lookup('ar', key);

Future<void> _tapText(WidgetTester tester, String text) async {
  final f = find.text(text);
  await tester.ensureVisible(f.first);
  await tester.tap(f.first);
  await settle(tester, frames: 6);
}

Future<void> _tapPrimary(WidgetTester tester) async {
  final f = find.byType(PrimaryButton);
  await tester.ensureVisible(f.first);
  await tester.tap(f.first);
  await settle(tester, frames: 6);
}

Future<void> _enter(WidgetTester tester, String key, String text) async {
  await tester.enterText(find.byKey(ValueKey<String>(key)), text);
  await tester.pump();
}

void main() {
  setUpWidgetTests();

  group('validators', () {
    test('new password policy matches registration', () {
      expect(validateNewPassword('short'), 'auth.err.password');
      expect(validateNewPassword(null), 'auth.err.password');
      expect(validateNewPassword('12345678'), isNull);
      expect(validatePassword('12345678'), isNull);
      expect(validateNewPassword('abcdefgh', current: 'abcdefgh'),
          'auth.err.password_same');
      expect(validateNewPassword('abcdefgh', current: ''), isNull);
      expect(validateNewPassword('abcdefgh', current: 'zzzzzzzz'), isNull);
    });

    test('confirm, current and token', () {
      expect(validatePasswordConfirm('a', 'b'), 'auth.err.password_mismatch');
      expect(validatePasswordConfirm('abc', 'abc'), isNull);
      expect(validateCurrentPassword(''), 'auth.err.current_password');
      expect(validateCurrentPassword('x'), isNull);
      expect(validateResetToken('  '), 'auth.err.token');
      expect(validateResetToken(' tok '), isNull);
    });

    test('every new key has distinct ar and en text', () {
      for (final k in [
        'auth.err.password_same',
        'auth.err.password_mismatch',
        'auth.err.current_password',
        'auth.err.token',
        'auth.password_hint',
        'error.rate_limited',
        'error.rate_limited_wait',
        'error.invalid_token',
        'error.invalid_current_password',
        'error.weak_password',
      ]) {
        final ar = AppStrings.lookup('ar', k);
        final en = AppStrings.lookup('en', k);
        expect(ar, isNot(k), reason: k);
        expect(en, isNot(k), reason: k);
        expect(ar, isNot(en), reason: k);
      }
    });
  });

  group('repository JSON', () {
    test('forgot posts the email without auth', () async {
      final a = _Adapter((o) => _json(<String, dynamic>{}, 202));
      await _live(a).forgot(' a@b.co ');
      final c = a.calls.single;
      expect(c.method, 'POST');
      expect(c.path, '/v1/auth/password/forgot');
      expect(c.data, <String, dynamic>{'email': 'a@b.co'});
      expect(c.headers.containsKey('Authorization'), isFalse);
    });

    test('reset posts token and new_password', () async {
      final a = _Adapter((o) => _json(<String, dynamic>{}, 200));
      await _live(a).reset(token: ' tok ', newPassword: 'newpass123');
      expect(a.calls.single.path, '/v1/auth/password/reset');
      expect(a.calls.single.data,
          <String, dynamic>{'token': 'tok', 'new_password': 'newpass123'});
    });

    test('change posts current and new password', () async {
      final a = _Adapter((o) => _json(<String, dynamic>{}, 200));
      await _live(a).change(currentPassword: 'old', newPassword: 'newpass123');
      expect(a.calls.single.path, '/v1/me/password');
      expect(a.calls.single.data, <String, dynamic>{
        'current_password': 'old',
        'new_password': 'newpass123',
      });
    });

    test('429 keeps Retry-After and maps to a localized key', () async {
      final a = _Adapter((o) => _json(
            <String, dynamic>{
              'error': {'code': 'rate_limited', 'message': 'slow down'},
            },
            429,
            {
              'retry-after': ['120'],
            },
          ));
      await expectLater(
        _live(a).forgot('a@b.co'),
        throwsA(isA<ApiException>()
            .having((e) => e.status, 'status', 429)
            .having((e) => e.retryAfterSeconds, 'retry', 120)),
      );
    });

    test('error keys: codes, 429 and 422 fallbacks', () {
      expect(passwordErrorKey(ApiException(status: 429, code: 'http_429', message: 'x')),
          'error.rate_limited');
      expect(passwordErrorKey(ApiException(status: 422, code: 'http_422', message: 'x')),
          'error.weak_password');
      expect(passwordErrorKey(ApiException(status: 400, code: 'invalid_token', message: 'x')),
          'error.invalid_token');
      expect(passwordErrorKey(ApiException(status: 500, code: 'boom', message: 'x')), isNull);
      expect(passwordErrorKey(StateError('x')), isNull);
    });

    test('mock mode behaves deterministically', () async {
      final m = _mock();
      await m.forgot('anyone@example.com');
      await m.reset(token: 'abc', newPassword: 'newpass123');
      await m.change(currentPassword: 'old', newPassword: 'newpass123');
      await expectLater(
        m.reset(token: kMockInvalidResetToken, newPassword: 'newpass123'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'invalid_token')),
      );
      await expectLater(
        m.change(currentPassword: kMockWrongPassword, newPassword: 'newpass123'),
        throwsA(isA<ApiException>()
            .having((e) => e.code, 'code', 'invalid_current_password')),
      );
      await expectLater(
        m.forgot(kMockRateLimitedEmail),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 429)),
      );
    });
  });

  group('widget flows', () {
    testWidgets('login screen links to forgot password; neutral confirmation',
        (tester) async {
      await pumpApp(tester, location: '/login', logicalSize: const Size(540, 1600));
      await tester.tap(find.byKey(const ValueKey<String>('login-forgot')));
      await settle(tester);
      expect(find.byKey(const ValueKey<String>('forgot-email')), findsOneWidget);

      await _enter(tester, 'forgot-email', 'nobody@example.com');
      await _tapText(tester, _ar('auth.forgot.send'));
      expect(find.byKey(const ValueKey<String>('forgot-sent')), findsOneWidget);
      expect(find.text(_ar('auth.forgot.sent')), findsOneWidget);
      await disposeApp(tester);
    });

    testWidgets('forgot rejects an invalid email', (tester) async {
      await pumpApp(tester,
          location: '/forgot-password', logicalSize: const Size(540, 1600));
      await _enter(tester, 'forgot-email', 'nope');
      await _tapText(tester, _ar('auth.forgot.send'));
      expect(find.text(_ar('auth.err.email')), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('forgot-sent')), findsNothing);
      await disposeApp(tester);
    });

    testWidgets('forgot shows the 429 message', (tester) async {
      await pumpApp(tester,
          location: '/forgot-password', logicalSize: const Size(540, 1600));
      await _enter(tester, 'forgot-email', kMockRateLimitedEmail);
      await _tapText(tester, _ar('auth.forgot.send'));
      expect(find.text(AppStrings.lookup('ar', 'error.rate_limited_wait', {'n': '1'})),
          findsOneWidget);
      expect(find.byKey(const ValueKey<String>('forgot-sent')), findsNothing);
      await disposeApp(tester);
    });

    testWidgets('reset validates, shows invalid token, then succeeds',
        (tester) async {
      await pumpApp(tester,
          location: '/reset-password', logicalSize: const Size(540, 1600));
      await _tapText(tester, _ar('auth.reset.submit'));
      expect(find.text(_ar('auth.err.token')), findsOneWidget);

      await _enter(tester, 'reset-token', kMockInvalidResetToken);
      await _enter(tester, 'reset-password', 'newpass123');
      await _enter(tester, 'reset-confirm', 'different1');
      await _tapText(tester, _ar('auth.reset.submit'));
      expect(find.text(_ar('auth.err.password_mismatch')), findsOneWidget);

      await _enter(tester, 'reset-confirm', 'newpass123');
      await _tapText(tester, _ar('auth.reset.submit'));
      expect(find.text(_ar('error.invalid_token')), findsOneWidget);

      await _enter(tester, 'reset-token', 'good-token');
      await _tapText(tester, _ar('auth.reset.submit'));
      // Success navigates to the login screen.
      expect(find.byKey(const ValueKey<String>('login-forgot')), findsOneWidget);
      await disposeApp(tester);
    });

    testWidgets('reset prefills the token from the link', (tester) async {
      await pumpApp(tester,
          location: '/reset-password?token=abc123',
          logicalSize: const Size(540, 1600));
      expect(find.text('abc123'), findsOneWidget);
      await disposeApp(tester);
    });

    testWidgets('change password: validation, wrong current, success',
        (tester) async {
      await pumpApp(tester,
          location: '/settings/change-password',
          logicalSize: const Size(540, 1600));
      await _enter(tester, 'change-current', kMockWrongPassword);
      await _enter(tester, 'change-password', 'short');
      await _enter(tester, 'change-confirm', 'short');
      await _tapPrimary(tester);
      expect(find.text(_ar('auth.err.password')), findsOneWidget);

      await _enter(tester, 'change-password', 'newpass123');
      await _enter(tester, 'change-confirm', 'newpass123');
      await _tapPrimary(tester);
      expect(find.text(_ar('error.invalid_current_password')), findsOneWidget);
      await disposeApp(tester);
    });

    testWidgets('settings hides the change-password tile when signed out',
        (tester) async {
      await pumpApp(tester, location: '/settings', logicalSize: const Size(540, 4000));
      expect(find.byKey(const ValueKey<String>('settings-change-password')),
          findsNothing);
      await disposeApp(tester);
    });

    testWidgets('settings shows the change-password tile when signed in',
        (tester) async {
      await pumpApp(
        tester,
        location: '/settings',
        logicalSize: const Size(540, 4000),
        overrides: [
          authProvider.overrideWith((ref) {
            final c = AuthController(ref);
            c.state = const Me(id: 'usr_t', name: 'Tester');
            return c;
          }),
        ],
      );
      expect(find.byKey(const ValueKey<String>('settings-change-password')),
          findsOneWidget);
      await disposeApp(tester);
    });
  });
}
