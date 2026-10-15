import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/storage/persistence.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:factory_finder/features/privacy/privacy_models.dart';
import 'package:factory_finder/features/privacy/privacy_repository.dart';
import 'package:factory_finder/features/privacy/privacy_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

String _raw(String name) => File('test/fixtures/live/$name.json').readAsStringSync();
dynamic _load(String name) => jsonDecode(_raw(name));

class _Adapter implements HttpClientAdapter {
  _Adapter(this.handler);
  final ResponseBody Function(RequestOptions) handler;
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

ResponseBody _resp(String body, [int status = 200, Map<String, List<String>>? h]) =>
    ResponseBody.fromString(body, status, headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
      ...?h,
    });

LivePrivacyRepository _live(_Adapter a) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
  dio.httpClientAdapter = a;
  return LivePrivacyRepository(ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio));
}

class _FakeAuth extends AuthController {
  _FakeAuth(Ref ref, Me? me) : super(ref) {
    state = me;
  }
}

/// Repo whose outcome the test controls.
class _FakeRepo implements PrivacyRepository {
  _FakeRepo({this.exportResult, this.deleteResult, this.error});
  final ExportResult? exportResult;
  final DeletionResult? deleteResult;
  final Object? error;
  final List<String?> passwords = [];

  @override
  Future<ExportResult> exportData() async {
    if (error != null) throw error!;
    return exportResult!;
  }

  @override
  Future<DeletionResult> deleteAccount({String? password, String? refreshToken}) async {
    passwords.add(password);
    if (error != null) throw error!;
    return deleteResult!;
  }
}

const _me = Me(id: 'usr_1', name: 'Buyer', email: 'buyer@example.com');

Future<void> _pump(
  WidgetTester tester,
  PrivacyRepository repo, {
  required MemoryStore store,
  required VoidCallback onGone,
  Me? me = _me,
  Locale locale = const Locale('ar'),
  double textScale = 1.0,
  Size size = const Size(360, 800),
}) async {
  tester.view.physicalSize = size * 2.0;
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(ProviderScope(
    overrides: [
      privacyRepositoryProvider.overrideWithValue(repo),
      keyValueStoreProvider.overrideWithValue(store),
      secureStoreProvider.overrideWithValue(MemoryStore()),
      authProvider.overrideWith((ref) => _FakeAuth(ref, me)),
      onboardingCompletedProvider.overrideWith((ref) => true),
    ],
    child: MaterialApp(
      locale: locale,
      supportedLocales: const [Locale('ar'), Locale('en')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(textScale)),
        child: child!,
      ),
      home: PrivacyScreen(onAccountGone: onGone),
    ),
  ));
  await settle(tester, frames: 2);
}

Finder _k(String key) => find.byKey(ValueKey<String>(key));

void main() {
  setUpWidgetTests();

  group('parsing', () {
    test('export bundle', () {
      final raw = _raw('me_export');
      final r = ExportResult.fromResponse(jsonDecode(raw));
      expect(r.partial, isFalse);
      expect(r.services.map((s) => s.name), ['gateway', 'rfq']);
      expect(r.failed, isEmpty);
      expect(r.sizeBytes, greaterThan(100));
      expect(r.generatedAt, '2026-10-15T09:00:00Z');
      expect(ExportResult.fromResponse(raw).sizeBytes, utf8.encode(raw).length);
    });

    test('partial export lists failed and truncated services', () {
      final r = ExportResult.fromResponse(_load('me_export_partial'));
      expect(r.partial, isTrue);
      expect(r.failed.single.name, 'messaging');
      expect(r.failed.single.error, 'timeout');
      expect(r.truncatedServices.single.name, 'rfq');
    });

    test('partial flag is derived when a service failed', () {
      final r = ExportResult.fromResponse({
        'services': {'a': {'status': 'error', 'error': 'unavailable'}},
      });
      expect(r.partial, isTrue);
      expect(() => ExportResult.fromResponse(42), throwsFormatException);
    });

    test('deletion statuses', () {
      final d = DeletionResult.fromJson(_load('me_delete_deleted'));
      expect(d.isDeleted, isTrue);
      expect(d.pendingServices, isEmpty);
      final p = DeletionResult.fromJson(_load('me_delete_partial'));
      expect(p.status, 'partial');
      expect(p.pendingServices, ['messaging', 'rfq']);
      final s = DeletionResult.fromJson(_load('me_delete_scheduled'));
      expect(s.scheduledDate, '2026-11-14');
      expect(DeletionResult.fromJson(null).status, 'partial');
      expect(DeletionResult.fromJson({'status': 'weird'}).status, 'partial');
    });

    test('byte sizes', () {
      expect(formatByteSize(10), '10 B');
      expect(formatByteSize(2048), '2.0 KB');
      expect(formatByteSize(5 * 1024 * 1024), '5.0 MB');
    });
  });

  group('live repo (fake Dio)', () {
    test('export GETs /v1/me/export', () async {
      final a = _Adapter((o) => _resp(_raw('me_export_partial')));
      final r = await _live(a).exportData();
      expect(a.calls.single.method, 'GET');
      expect(a.calls.single.path, '/v1/me/export');
      expect(r.partial, isTrue);
    });

    test('delete sends password body and parses 200', () async {
      final a = _Adapter((o) => _resp(_raw('me_delete_deleted')));
      final r = await _live(a).deleteAccount(password: 'secret123');
      expect(a.calls.single.method, 'DELETE');
      expect(a.calls.single.path, '/v1/me');
      expect(a.calls.single.data, {'password': 'secret123'});
      expect(r.isDeleted, isTrue);
    });

    test('delete with refresh token and 202 partial', () async {
      final a = _Adapter((o) => _resp(_raw('me_delete_partial'), 202));
      final r = await _live(a).deleteAccount(refreshToken: 'rt');
      expect(a.calls.single.data, {'refresh_token': 'rt'});
      expect(r.status, 'partial');
      expect(r.pendingServices, isNotEmpty);
    });

    test('403 reauth_failed maps to the password message', () async {
      final a = _Adapter((o) => _resp(_raw('error_privacy_reauth_failed'), 403));
      await expectLater(
        _live(a).deleteAccount(password: 'x'),
        throwsA(isA<ApiException>()
            .having((e) => e.code, 'code', 'reauth_failed')
            .having((e) => privacyErrorKey(e), 'key', 'privacy.err.reauth_failed')),
      );
    });

    test('429 carries Retry-After', () async {
      final a = _Adapter((o) => _resp(
            _raw('error_privacy_rate_limited'),
            429,
            {'retry-after': ['30']},
          ));
      try {
        await _live(a).exportData();
        fail('expected 429');
      } on ApiException catch (e) {
        expect(e.status, 429);
        expect(e.retryAfterSeconds, 30);
        expect(privacyErrorKey(e), 'privacy.err.rate_limited');
      }
    });
  });

  test('error mapping', () {
    expect(privacyErrorKey(ApiException(status: 403, code: 'forbidden', message: '')),
        'privacy.err.forbidden');
    expect(privacyErrorKey(ApiException(status: 401, code: 'x', message: '')),
        'privacy.err.session');
    expect(privacyErrorKey(ApiException(status: 422, code: 'x', message: '')),
        'privacy.err.invalid');
    expect(privacyErrorKey(ApiException(code: 'network_error', message: '')),
        'privacy.err.network');
    expect(privacyErrorKey(ApiException(code: 'timeout', message: '')),
        'privacy.err.network');
    expect(privacyErrorKey(ApiException(status: 503, code: 'http_503', message: '')),
        'privacy.err.server');
    expect(privacyErrorKey(StateError('x')), 'privacy.err.generic');
  });

  test('mock repo behaviors', () async {
    final m = MockPrivacyRepository();
    expect((await m.exportData()).partial, isFalse);
    expect((await m.deleteAccount(password: 'ok-password')).isDeleted, isTrue);
    expect((await m.deleteAccount(password: kMockPartialPassword)).status, 'partial');
    await expectLater(
      m.deleteAccount(password: kMockWrongPassword),
      throwsA(isA<ApiException>().having((e) => e.status, 'status', 403)),
    );
  });

  group('widgets', () {
    testWidgets('signed out shows sign-in note', (tester) async {
      await _pump(tester, _FakeRepo(), store: MemoryStore(), onGone: () {}, me: null);
      expect(_k('privacy-login-required'), findsOneWidget);
      expect(_k('privacy-export'), findsNothing);
    });

    testWidgets('export shows size, partial warning and copies summary', (tester) async {
      String? clip;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            clip = (call.arguments as Map)['text'] as String?;
          }
          return null;
        },
      );
      addTearDown(() => tester.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null));
      final repo = _FakeRepo(
          exportResult: ExportResult.fromResponse(_load('me_export_partial')));
      await _pump(tester, repo,
          store: MemoryStore(), onGone: () {}, locale: const Locale('en'));
      await tester.tap(_k('privacy-export'));
      await settle(tester, frames: 3);
      expect(_k('privacy-export-dialog'), findsOneWidget);
      expect(_k('privacy-export-size'), findsOneWidget);
      expect(_k('privacy-export-partial'), findsOneWidget);
      expect(find.text('messaging: timeout'), findsOneWidget);

      await tester.tap(_k('privacy-copy-summary'));
      await settle(tester, frames: 2);
      expect(_k('privacy-export-copied'), findsOneWidget);
      expect(clip, contains('messaging: error (timeout)'));
      expect(clip, contains('gateway: ok'));

      await tester.tap(_k('privacy-copy-json'));
      await settle(tester, frames: 2);
      expect(clip, contains('"format_version": 1'));

      await tester.tap(_k('privacy-export-close'));
      await settle(tester, frames: 3);
      expect(_k('privacy-export-dialog'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('export 429 shows rate-limit message with seconds', (tester) async {
      final repo = _FakeRepo(
          error: ApiException(
              status: 429, code: 'rate_limited', message: 'x', retryAfterSeconds: 30));
      await _pump(tester, repo,
          store: MemoryStore(), onGone: () {}, locale: const Locale('en'));
      await tester.tap(_k('privacy-export'));
      await settle(tester, frames: 3);
      expect(find.text('Too many attempts. Try again in 30s.'), findsOneWidget);
    });

    testWidgets('export network error', (tester) async {
      final repo = _FakeRepo(
          error: ApiException(code: 'network_error', message: 'x'));
      await _pump(tester, repo, store: MemoryStore(), onGone: () {});
      await tester.tap(_k('privacy-export'));
      await settle(tester, frames: 3);
      expect(_k('privacy-export-error'), findsOneWidget);
      expect(find.text('تعذّر الاتصال بالخادم. تحقق من الشبكة.'), findsOneWidget);
    });

    testWidgets('delete needs a password, then a final confirm', (tester) async {
      final repo = _FakeRepo(
          deleteResult: DeletionResult.fromJson(_load('me_delete_deleted')));
      var gone = 0;
      final store = MemoryStore({
        StorageKeys.locale: 'en',
        StorageKeys.onboardingDone: '1',
        StorageKeys.refreshToken: 'rt',
      });
      await _pump(tester, repo,
          store: store, onGone: () => gone++, locale: const Locale('en'));
      final btn = _k('privacy-delete');
      expect(tester.widget<FilledButton>(btn).onPressed, isNull);

      await tester.enterText(_k('privacy-password'), 'secret123');
      await tester.pump();
      expect(tester.widget<FilledButton>(btn).onPressed, isNotNull);

      // Cancel keeps everything.
      await tester.tap(btn);
      await settle(tester, frames: 3);
      await tester.tap(_k('privacy-confirm-cancel'));
      await settle(tester, frames: 3);
      expect(repo.passwords, isEmpty);
      expect(store.data, isNotEmpty);

      // Confirm deletes, clears state and routes away after the notice.
      await tester.tap(btn);
      await settle(tester, frames: 3);
      await tester.tap(_k('privacy-confirm-delete'));
      await settle(tester, frames: 3);
      expect(repo.passwords, ['secret123']);
      expect(find.text('Your account was deleted'), findsOneWidget);
      expect(gone, 0);
      expect(store.data, isEmpty);
      await tester.tap(_k('privacy-done'));
      await settle(tester, frames: 3);
      expect(gone, 1);
      expect(tester.takeException(), isNull);
    });

    testWidgets('partial 202 shows the pending notice', (tester) async {
      final repo = _FakeRepo(
          deleteResult: DeletionResult.fromJson(_load('me_delete_partial')));
      await _pump(tester, repo,
          store: MemoryStore(), onGone: () {}, locale: const Locale('en'));
      await tester.enterText(_k('privacy-password'), 'secret123');
      await tester.pump();
      await tester.tap(_k('privacy-delete'));
      await settle(tester, frames: 3);
      await tester.tap(_k('privacy-confirm-delete'));
      await settle(tester, frames: 3);
      expect(find.text('Deletion is in progress'), findsOneWidget);
      expect(find.textContaining('messaging, rfq'), findsOneWidget);
    });

    testWidgets('scheduled shows the date', (tester) async {
      final repo = _FakeRepo(
          deleteResult: DeletionResult.fromJson(_load('me_delete_scheduled')));
      await _pump(tester, repo,
          store: MemoryStore(), onGone: () {}, locale: const Locale('en'));
      await tester.enterText(_k('privacy-password'), 'secret123');
      await tester.pump();
      await tester.tap(_k('privacy-delete'));
      await settle(tester, frames: 3);
      await tester.tap(_k('privacy-confirm-delete'));
      await settle(tester, frames: 3);
      expect(find.textContaining('2026-11-14'), findsOneWidget);
    });

    testWidgets('403 reauth keeps the user signed in with an error', (tester) async {
      final repo = _FakeRepo(
          error: ApiException(status: 403, code: 'reauth_failed', message: 'x'));
      var gone = 0;
      final store = MemoryStore({StorageKeys.locale: 'ar'});
      await _pump(tester, repo, store: store, onGone: () => gone++);
      await tester.enterText(_k('privacy-password'), 'badpassword');
      await tester.pump();
      await tester.tap(_k('privacy-delete'));
      await settle(tester, frames: 3);
      await tester.tap(_k('privacy-confirm-delete'));
      await settle(tester, frames: 3);
      expect(_k('privacy-delete-error'), findsOneWidget);
      expect(find.text('كلمة المرور غير صحيحة'), findsOneWidget);
      expect(gone, 0);
      expect(store.data, isNotEmpty);
    });

    testWidgets('no overflow at text scale 2.0 on 360dp', (tester) async {
      final repo = _FakeRepo(
          exportResult: ExportResult.fromResponse(_load('me_export_partial')));
      await _pump(tester, repo,
          store: MemoryStore(), onGone: () {}, textScale: 2.0);
      expect(tester.takeException(), isNull);
      await tester.drag(find.byType(Scrollable).first, const Offset(0, -600));
      await tester.pump();
      expect(tester.takeException(), isNull);
      await tester.drag(find.byType(Scrollable).first, const Offset(0, 600));
      await tester.pump();
      await tester.tap(_k('privacy-export'));
      await settle(tester, frames: 3);
      expect(_k('privacy-export-dialog'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
