import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/my_products/media/image_pick_service.dart';
import 'package:factory_finder/features/my_products/media/media_logic.dart';
import 'package:factory_finder/features/my_products/media/media_models.dart';
import 'package:factory_finder/features/my_products/media/media_repository.dart';
import 'package:factory_finder/features/trust/verification_models.dart';
import 'package:factory_finder/features/trust/verification_repository.dart';
import 'package:factory_finder/features/trust/verification_thumbnails.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

const String _id = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

class _CountingRepo extends MockMediaRepository {
  int ttl = 300;

  @override
  Future<SignedUrl> signFile(String id) async {
    final base = await super.signFile(id);
    return SignedUrl(url: base.url, ttlSeconds: ttl);
  }
}

void main() {
  setUpWidgetTests();

  group('media helpers', () {
    test('mediaIdFromRef', () {
      expect(mediaIdFromRef('/v1/media/private/$_id.jpg'), _id);
      expect(mediaIdFromRef('http://h/v1/media/files/$_id.png?w=200'), _id);
      expect(mediaIdFromRef('/v1/media/private/short.jpg'), isNull);
      expect(mediaIdFromRef(''), isNull);
    });

    test('SignedUrl parses the contract fixture', () {
      final j = jsonDecode(File('test/fixtures/live/media_signed_url.json').readAsStringSync());
      final s = SignedUrl.fromJson(j);
      expect(s.ttlSeconds, 300);
      expect(s.url, contains('/v1/media/private/$_id.jpg?'));
      expect(SignedUrl.fromJson(null).url, '');
    });

    test('mock: verification uploads are private, others public', () async {
      final img = PickedImage(
        bytes: Uint8List.fromList([1, 2, 3]),
        filename: 'a.png',
        mime: 'image/png',
      );
      final repo = MockMediaRepository();
      final v = await repo.uploadImage(img, kind: 'verification');
      expect(v.url, startsWith('/v1/media/private/'));
      expect(mediaIdFromRef(v.url), v.id);
      final l = await repo.uploadImage(img);
      expect(l.url, startsWith('/v1/media/files/'));
    });

    test('live repository signs via POST /v1/media/files/{id}/sign', () async {
      final calls = <RequestOptions>[];
      final dio = Dio(BaseOptions(baseUrl: 'http://h'))
        ..httpClientAdapter = _Adapter((o) {
          calls.add(o);
          return ResponseBody.fromString(
            File('test/fixtures/live/media_signed_url.json').readAsStringSync(),
            200,
            headers: {
              Headers.contentTypeHeader: ['application/json'],
            },
          );
        });
      final api = ApiClient(baseUrl: 'http://h', isMock: false, dio: dio);
      final s = await LiveMediaRepository(api).signFile(_id);
      expect(calls.single.method, 'POST');
      expect(calls.single.path, '/v1/media/files/$_id/sign');
      expect(s.ttlSeconds, 300);
    });
  });

  group('SignedUrlCache', () {
    test('caches for the TTL minus margin, then re-signs', () async {
      var now = DateTime.utc(2026, 10, 1);
      final repo = _CountingRepo();
      final cache = SignedUrlCache(repo, now: () => now);
      expect(await cache.urlFor(_id), isNotNull);
      expect(await cache.urlFor(_id), isNotNull);
      expect(repo.signCalls, 1);
      now = now.add(const Duration(seconds: 269));
      await cache.urlFor(_id);
      expect(repo.signCalls, 1);
      now = now.add(const Duration(seconds: 2)); // 271s > 300 - 30
      await cache.urlFor(_id);
      expect(repo.signCalls, 2);
    });

    test('concurrent calls share one request; forget re-signs', () async {
      final repo = _CountingRepo();
      final cache = SignedUrlCache(repo);
      await Future.wait([cache.urlFor(_id), cache.urlFor(_id)]);
      expect(repo.signCalls, 1);
      cache.forget(_id);
      await cache.urlFor(_id);
      expect(repo.signCalls, 2);
    });

    test('failures yield null and are not cached', () async {
      final repo = _CountingRepo()
        ..signError = ApiException(status: 404, code: 'not_found', message: 'x');
      final cache = SignedUrlCache(repo);
      expect(await cache.urlFor(_id), isNull);
      repo.signError = null;
      expect(await cache.urlFor(_id), isNotNull);
      expect(repo.signCalls, 2);
    });
  });

  group('mock verification repo', () {
    test('rejects public media refs with file_url_not_allowed', () async {
      final repo = MockVerificationRepository();
      final draft = VerificationDraft(
        docType: 'business_license',
        country: 'IQ',
        number: 'LIC-99999',
        consent: true,
        files: const ['/v1/media/files/$_id.jpg'],
      );
      await expectLater(
        repo.submit(draft),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'file_url_not_allowed')),
      );
      expect(
        verificationErrorKey(ApiException(status: 422, code: 'file_url_not_allowed', message: 'm')),
        'ver.err.file_url',
      );
      for (final lang in ['ar', 'en']) {
        expect(AppStrings.lookup(lang, 'ver.err.file_url'), isNot('ver.err.file_url'));
      }
    });
  });

  group('VerificationThumb widget', () {
    Future<void> pump(WidgetTester tester, MediaRepository repo, {double scale = 1}) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [mediaRepositoryProvider.overrideWithValue(repo)],
          child: MaterialApp(
            locale: const Locale('en'),
            supportedLocales: const [Locale('ar'), Locale('en')],
            localizationsDelegates: GlobalMaterialLocalizations.delegates,
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
              child: child!,
            ),
            home: const Scaffold(
              body: VerificationThumb(fileRef: '/v1/media/private/$_id.jpg', index: 1),
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
    }

    testWidgets('signs on demand and shows the image widget', (tester) async {
      final repo = _CountingRepo();
      await pump(tester, repo, scale: 2.0);
      expect(repo.signCalls, 1);
      expect(find.byKey(const ValueKey<String>('ver-thumb-image')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('sign failure shows a placeholder and retry signs again', (tester) async {
      final repo = _CountingRepo()
        ..signError = ApiException(status: 404, code: 'not_found', message: 'x');
      await pump(tester, repo);
      expect(find.byKey(const ValueKey<String>('ver-thumb-image')), findsNothing);
      expect(find.byKey(const ValueKey<String>('ver-thumb-retry')), findsOneWidget);
      repo.signError = null;
      await tester.tap(find.byKey(const ValueKey<String>('ver-thumb-retry')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(repo.signCalls, 2);
      expect(find.byKey(const ValueKey<String>('ver-thumb-image')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}

class _Adapter implements HttpClientAdapter {
  _Adapter(this.handler);
  final ResponseBody Function(RequestOptions) handler;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async =>
      handler(options);

  @override
  void close({bool force = false}) {}
}
