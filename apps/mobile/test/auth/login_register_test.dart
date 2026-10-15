import 'dart:async';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/auth/auth_errors.dart';
import 'package:factory_finder/features/auth/auth_validators.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

class _FakeAuthRepo extends AuthRepository {
  _FakeAuthRepo(this.onRegister)
      : super(ApiClient(baseUrl: 'http://fake', isMock: true));

  final Future<Me> Function() onRegister;
  final List<Map<String, String?>> registerCalls = [];

  @override
  Future<Me> register({
    String? email,
    String? phone,
    required String password,
    required String name,
  }) {
    registerCalls.add({'email': email, 'phone': phone, 'name': name});
    return onRegister();
  }
}

ApiException _api(int status, String code, {int? retry}) => ApiException(
      status: status,
      code: code,
      message: 'raw english message',
      retryAfterSeconds: retry,
    );

String _ar(String key, [Map<String, String> p = const {}]) =>
    AppStrings.lookup('ar', key, p);

Future<void> _enter(WidgetTester tester, String key, String text) async {
  await tester.enterText(find.byKey(ValueKey<String>(key)), text);
  await tester.pump();
}

Future<void> _submit(WidgetTester tester) async {
  final f = find.byType(PrimaryButton);
  await tester.ensureVisible(f.first);
  await tester.tap(f.first, warnIfMissed: false);
  await settle(tester, frames: 4);
}

/// Lets the current snackbar expire so the next one can show.
Future<void> _expireSnack(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 5));
  await settle(tester, frames: 4);
}

Future<void> _fillRegister(WidgetTester tester, {String phone = ''}) async {
  await _enter(tester, 'register-name', 'Ali');
  await _enter(tester, 'register-email', 'ali@example.com');
  await _enter(tester, 'register-phone', phone);
  await _enter(tester, 'register-password', 'password123');
}

bool _obscured(WidgetTester tester, String key) => tester
    .widget<TextField>(find.descendant(
      of: find.byKey(ValueKey<String>(key)),
      matching: find.byType(TextField),
    ))
    .obscureText;

void main() {
  setUpWidgetTests();

  group('validators', () {
    test('password limit is 72 UTF-8 bytes, not characters', () {
      expect(validatePassword('a' * 72), isNull);
      expect(validatePassword('a' * 73), 'auth.err.password_long');
      // Arabic letters take 2 bytes: 36 fit, 37 do not.
      expect(validatePassword('ب' * 36), isNull);
      expect(validatePassword('ب' * 37), 'auth.err.password_long');
      expect(validateNewPassword('ب' * 37), 'auth.err.password_long');
      expect(validatePassword('short'), 'auth.err.password');
    });

    test('Arabic-Indic digits are normalized', () {
      expect(normalizeDigits('٠٧٧٠١٢٣٤٥٦٧'), '07701234567');
      expect(normalizeDigits('۰۷۷۰۱۲۳۴۵۶۷'), '07701234567');
    });

    test('Iraqi phone numbers normalize to E.164', () {
      const e164 = '+9647701234567';
      expect(normalizePhone('07701234567'), e164);
      expect(normalizePhone('0770 123 4567'), e164);
      expect(normalizePhone('٠٧٧٠١٢٣٤٥٦٧'), e164);
      expect(normalizePhone('+964 770-123-4567'), e164);
      expect(normalizePhone('009647701234567'), e164);
      expect(normalizePhone('9647701234567'), e164);
      expect(normalizePhone('+٩٦٤٧٧٠١٢٣٤٥٦٧'), e164);
      expect(normalizePhone('+1 (415) 555-0132'), '+14155550132');
    });

    test('invalid phones are rejected, empty is allowed', () {
      expect(validatePhone(''), isNull);
      expect(validatePhone('   '), isNull);
      expect(validatePhone(null), isNull);
      expect(validatePhone('07701234567'), isNull);
      expect(validatePhone('12345'), 'auth.err.phone');
      expect(validatePhone('abc'), 'auth.err.phone');
      expect(validatePhone('0770123'), 'auth.err.phone');
      expect(validatePhone('+96477012345678901'), 'auth.err.phone');
      expect(normalizePhone('4155550132'), isNull);
    });

    test('every new key has distinct ar and en text', () {
      for (final k in [
        'auth.err.password_long',
        'auth.err.phone',
        'auth.err.account_exists',
        'auth.err.invalid_credentials',
        'auth.err.invalid_input',
        'auth.show_password',
        'auth.hide_password',
      ]) {
        final ar = AppStrings.lookup('ar', k);
        final en = AppStrings.lookup('en', k);
        expect(ar, isNot(k), reason: k);
        expect(en, isNot(k), reason: k);
        expect(ar, isNot(en), reason: k);
      }
    });

    test('error keys: 409, 401 credentials, 422', () {
      expect(authErrorKey(_api(409, 'account_exists')), 'auth.err.account_exists');
      expect(authErrorKey(_api(401, 'invalid_credentials')),
          'auth.err.invalid_credentials');
      expect(authErrorKey(_api(422, 'validation_error')), 'auth.err.invalid_input');
      expect(authErrorKey(_api(500, 'boom')), isNull);
      expect(authErrorKey(StateError('x')), isNull);
    });
  });

  group('screens', () {
    testWidgets('password toggle shows and hides the text', (tester) async {
      await pumpApp(tester, location: '/login', logicalSize: const Size(540, 1600));
      expect(_obscured(tester, 'login-password'), isTrue);
      expect(find.byTooltip(_ar('auth.show_password')), findsOneWidget);

      await tester.tap(find.byTooltip(_ar('auth.show_password')));
      await tester.pump();
      expect(_obscured(tester, 'login-password'), isFalse);
      expect(find.byTooltip(_ar('auth.hide_password')), findsOneWidget);

      await tester.tap(find.byTooltip(_ar('auth.hide_password')));
      await tester.pump();
      expect(_obscured(tester, 'login-password'), isTrue);
      await disposeApp(tester);
    });

    testWidgets('register validates phone and the 72-byte password limit',
        (tester) async {
      final repo = _FakeAuthRepo(() async => const Me(id: 'u', name: 'Ali'));
      await pumpApp(
        tester,
        location: '/register',
        logicalSize: const Size(540, 1600),
        overrides: [authRepositoryProvider.overrideWithValue(repo)],
      );
      await _fillRegister(tester, phone: '12345');
      await _enter(tester, 'register-password', 'ب' * 37);
      await _submit(tester);
      expect(find.text(_ar('auth.err.phone')), findsOneWidget);
      expect(find.text(_ar('auth.err.password_long')), findsOneWidget);
      expect(repo.registerCalls, isEmpty);
      await disposeApp(tester);
    });

    testWidgets('register maps 409 and 429 to localized messages', (tester) async {
      var next = _api(409, 'account_exists');
      final repo = _FakeAuthRepo(() async => throw next);
      await pumpApp(
        tester,
        location: '/register',
        logicalSize: const Size(540, 1600),
        overrides: [authRepositoryProvider.overrideWithValue(repo)],
      );
      await _fillRegister(tester);
      await _submit(tester);
      expect(find.text(_ar('auth.err.account_exists')), findsOneWidget);
      expect(find.text('raw english message'), findsNothing);

      await _expireSnack(tester);
      next = _api(429, 'rate_limited', retry: 1800);
      await _submit(tester);
      expect(find.text(_ar('error.rate_limited_wait', {'n': '30'})), findsOneWidget);

      await _expireSnack(tester);
      next = _api(429, 'http_429');
      await _submit(tester);
      expect(find.text(_ar('error.rate_limited')), findsOneWidget);
      expect(repo.registerCalls, hasLength(3));
      await disposeApp(tester);
    });

    testWidgets('register sends the normalized phone', (tester) async {
      final repo = _FakeAuthRepo(() async => throw _api(409, 'account_exists'));
      await pumpApp(
        tester,
        location: '/register',
        logicalSize: const Size(540, 1600),
        overrides: [authRepositoryProvider.overrideWithValue(repo)],
      );
      await _fillRegister(tester, phone: '٠٧٧٠١٢٣٤٥٦٧');
      await _submit(tester);
      expect(repo.registerCalls.single['phone'], '+9647701234567');
      await disposeApp(tester);
    });

    testWidgets('register button is disabled while loading (no double submit)',
        (tester) async {
      final gate = Completer<Me>();
      final repo = _FakeAuthRepo(() => gate.future);
      await pumpApp(
        tester,
        location: '/register',
        logicalSize: const Size(540, 1600),
        overrides: [authRepositoryProvider.overrideWithValue(repo)],
      );
      await _fillRegister(tester);
      await _submit(tester);
      final button = find.descendant(
        of: find.byType(PrimaryButton),
        matching: find.byType(FilledButton),
      );
      expect(tester.widget<FilledButton>(button).onPressed, isNull);

      await _submit(tester);
      expect(repo.registerCalls, hasLength(1));

      gate.completeError(_api(409, 'account_exists'));
      await settle(tester);
      expect(tester.widget<FilledButton>(button).onPressed, isNotNull);
      await disposeApp(tester);
    });
  });
}
