import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/trust/verification_models.dart';
import 'package:factory_finder/features/trust/verification_repository.dart';
import 'package:flutter_test/flutter_test.dart';

dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

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

ResponseBody _json(Object body, [int status = 200, Map<String, List<String>>? headers]) =>
    ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>[Headers.jsonContentType],
        ...?headers,
      },
    );

ApiClient _client(_Adapter a) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
  dio.httpClientAdapter = a;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

const VerificationDraft _validDraft = VerificationDraft(
  docType: 'business_license',
  country: 'iq',
  number: ' LIC-12345 ',
  expiresOn: '2031-01-31',
  consent: true,
  files: ['/v1/media/private/ffffffffffffffffffffffffffffffff.jpg'],
);

void main() {
  group('parsing', () {
    test('document list fixture', () {
      final list = VerificationList.fromJson(_load('verification_documents'));
      expect(list.level, 'basic');
      expect(list.items, hasLength(4));
      final byId = {for (final d in list.items) d.id: d};
      final ok = byId['vdoc_0001']!;
      expect(ok.docType, 'business_license');
      expect(ok.numberMasked, '****5678');
      expect(ok.expiresOn, '2030-12-31');
      expect(ok.files, hasLength(1));
      expect(effectiveDocStatus(ok), 'approved');
      expect(canWithdraw(ok), isTrue);
      final rejected = byId['vdoc_0002']!;
      expect(rejected.reason, 'The document is not legible');
      expect(effectiveDocStatus(rejected), 'rejected');
      expect(canWithdraw(rejected), isFalse);
      expect(rejected.files, hasLength(2));
      final expired = byId['vdoc_0003']!;
      expect(expired.isExpired, isTrue);
      expect(effectiveDocStatus(expired), 'expired');
      final pending = byId['vdoc_0004']!;
      expect(pending.numberMasked, isNull);
      expect(pending.reviewedAt, isNull);
      expect(effectiveDocStatus(pending), 'pending');
      expect(pending.createdAt, isNotNull);
    });

    test('tolerates odd payloads', () {
      expect(VerificationList.fromJson(null).items, isEmpty);
      expect(VerificationList.fromJson(null).level, 'none');
      final odd = VerificationList.fromJson({
        'items': [
          'x',
          {'no_id': true},
          {'id': 'a', 'status': 'WITHDRAWN', 'files': ['f', 3], 'reason': '  '},
        ],
        'verification_level': 'platinum',
      });
      expect(odd.level, 'none');
      expect(odd.items.single.status, 'withdrawn');
      expect(odd.items.single.files, ['f']);
      expect(odd.items.single.reason, isNull);
      expect(canWithdraw(odd.items.single), isFalse);
    });

    test('public badge fixture and fallbacks', () {
      final v = PublicVerification.fromJson(_load('verification_public'));
      expect(v.level, 'documented');
      expect(v.isVerified, isTrue);
      expect(v.validTypes, ['business_license', 'iso_certificate']);
      expect(v.display('ar'), 'نشاط موثّق بالمستندات');
      expect(v.display('en'), 'Verified business (documented)');
      final none = PublicVerification.fromJson({'supplier_id': 's'});
      expect(none.level, 'none');
      expect(none.isVerified, isFalse);
      expect(none.display('ar'), '');
    });
  });

  group('validation', () {
    final today = DateTime(2026, 10, 15);

    test('valid draft passes and serialises', () {
      expect(validateVerificationDraft(_validDraft, today: today), isEmpty);
      final json = _validDraft.toJson();
      expect(json['doc_type'], 'business_license');
      expect(json['issuing_country'], 'IQ');
      expect(json['number'], 'LIC-12345');
      expect(json['expires_on'], '2031-01-31');
      expect(json['consent'], true);
      expect(json['files'], hasLength(1));
    });

    test('empty draft reports every required field', () {
      final e = validateVerificationDraft(const VerificationDraft(), today: today);
      expect(e.keys.toSet(), {'type', 'country', 'number', 'files', 'consent'});
      expect(e['consent'], 'ver.err.consent');
    });

    test('country, number, expiry and files rules', () {
      VerificationDraft d({
        String country = 'IQ',
        String number = 'ABCD',
        String expiresOn = '',
        List<String> files = const ['/v1/media/private/a.jpg'],
      }) =>
          VerificationDraft(
            docType: 'export_license',
            country: country,
            number: number,
            expiresOn: expiresOn,
            consent: true,
            files: files,
          );
      Map<String, String> v(VerificationDraft x) =>
          validateVerificationDraft(x, today: today);
      expect(v(d()), isEmpty);
      expect(v(d(country: 'I'))['country'], 'ver.err.country');
      expect(v(d(country: 'I1'))['country'], 'ver.err.country');
      expect(v(d(number: 'ABC'))['number'], 'ver.err.number');
      expect(v(d(number: 'A' * 65))['number'], 'ver.err.number');
      expect(v(d(number: 'A' * 64)), isEmpty);
      expect(v(d(expiresOn: '31/01/2031'))['expiry'], 'ver.err.expiry_format');
      expect(v(d(expiresOn: '2027-02-30'))['expiry'], 'ver.err.expiry_format');
      expect(v(d(expiresOn: '2026-10-14'))['expiry'], 'ver.err.expiry_past');
      expect(v(d(expiresOn: '2026-10-15')), isEmpty);
      expect(v(d(files: const []))['files'], 'ver.err.files');
      expect(
        v(d(files: List<String>.generate(11, (i) => '/v1/media/private/$i.jpg')))['files'],
        'ver.err.files',
      );
    });

    test('factory photos carry no number', () {
      const d = VerificationDraft(
        docType: 'factory_photos',
        country: 'CN',
        number: 'IGNORED-123',
        consent: true,
        files: ['/v1/media/private/a.jpg'],
      );
      expect(validateVerificationDraft(d), isEmpty);
      expect(d.toJson().containsKey('number'), isFalse);
      expect(d.toJson().containsKey('expires_on'), isFalse);
      expect(docTypeNeedsNumber('factory_photos'), isFalse);
      expect(docTypeNeedsNumber('iso_certificate'), isTrue);
    });

    test('date helpers', () {
      expect(parseIsoDate('2028-02-29'), isNotNull);
      expect(parseIsoDate('2027-02-29'), isNull);
      expect(parseIsoDate('2027-2-9'), isNull);
      expect(formatIsoDate(DateTime(2027, 3, 4)), '2027-03-04');
    });
  });

  group('error mapping', () {
    ApiException ex(int status, String code, {int? retry}) =>
        ApiException(status: status, code: code, message: 'm', retryAfterSeconds: retry);

    test('contract codes', () {
      expect(verificationErrorKey(ex(401, 'supplier_required')), 'ver.err.supplier_required');
      expect(verificationErrorKey(ex(403, 'supplier_verification_required')),
          'ver.err.supplier_required');
      expect(verificationErrorKey(ex(422, 'consent_required')), 'ver.err.consent');
      expect(verificationErrorKey(ex(422, 'already_expired')), 'ver.err.expiry_past');
      expect(verificationErrorKey(ex(422, 'number_required')), 'ver.err.number');
      expect(verificationErrorKey(ex(422, 'number_not_allowed')), 'ver.err.number_not_allowed');
      expect(verificationErrorKey(ex(422, 'invalid_files')), 'ver.err.files');
      expect(verificationErrorKey(ex(422, 'file_url_not_allowed')), 'ver.err.file_url');
      expect(verificationErrorKey(ex(422, 'invalid_doc_type')), 'ver.err.type');
      expect(verificationErrorKey(ex(409, 'duplicate_document')), 'ver.err.duplicate');
      expect(verificationErrorKey(ex(409, 'document_limit_reached')), 'ver.err.limit');
      expect(verificationErrorKey(ex(409, 'document_type_limit_reached')), 'ver.err.type_limit');
      expect(verificationErrorKey(ex(409, 'invalid_transition')), 'ver.err.transition');
      expect(verificationErrorKey(ex(404, 'document_not_found')), 'ver.err.not_found');
      expect(verificationErrorKey(ex(503, 'capacity_reached')), 'ver.err.capacity');
      expect(verificationErrorKey(ex(0, 'timeout')), 'ver.err.network');
      expect(verificationErrorKey(ex(500, 'http_500')), 'ver.err.generic');
      expect(verificationErrorKey(StateError('x')), 'ver.err.generic');
    });

    test('status fallbacks and rate limit wait', () {
      expect(verificationErrorKey(ex(401, 'http_401')), 'ver.err.supplier_required');
      expect(verificationErrorKey(ex(404, 'http_404')), 'ver.err.not_found');
      expect(verificationErrorKey(ex(429, 'http_429')), 'ver.err.rate_limited');
      expect(verificationErrorKey(ex(429, 'rate_limited', retry: 125)),
          'ver.err.rate_limited_wait');
      expect(verificationErrorArgs(ex(429, 'rate_limited', retry: 125)), {'n': '3'});
      expect(verificationErrorArgs(ex(429, 'rate_limited', retry: 1)), {'n': '1'});
      expect(verificationErrorArgs(ex(429, 'rate_limited')), isEmpty);
      expect(verificationErrorArgs(StateError('x')), isEmpty);
    });
  });

  group('live repository over a fake Dio', () {
    test('list, submit, withdraw and public badge paths', () async {
      final a = _Adapter((o) {
        if (o.path == '/v1/trust/verification/documents' && o.method == 'GET') {
          return _json(_load('verification_documents') as Object);
        }
        if (o.path == '/v1/trust/verification/documents' && o.method == 'POST') {
          return _json(_load('verification_document_created') as Object, 201);
        }
        if (o.method == 'DELETE') {
          final d = Map<String, dynamic>.from(
              (_load('verification_document_created') as Map).cast<String, dynamic>());
          d['status'] = 'withdrawn';
          return _json(d);
        }
        return _json(_load('verification_public') as Object);
      });
      final repo = LiveVerificationRepository(_client(a));

      final list = await repo.listMine();
      expect(list.items, hasLength(4));
      expect(a.calls.last.method, 'GET');

      final created = await repo.submit(_validDraft);
      expect(created.id, 'vdoc_0005');
      expect(created.status, 'pending');
      expect(created.numberMasked, '****4321');
      expect(a.calls.last.method, 'POST');
      final body = a.calls.last.data as Map;
      expect(body['doc_type'], 'business_license');
      expect(body['issuing_country'], 'IQ');
      expect(body['number'], 'LIC-12345');
      expect(body['expires_on'], '2031-01-31');
      expect(body['consent'], true);
      expect(body['files'], ['/v1/media/private/ffffffffffffffffffffffffffffffff.jpg']);

      final w = await repo.withdraw('vdoc_0005');
      expect(w.status, 'withdrawn');
      expect(a.calls.last.method, 'DELETE');
      expect(a.calls.last.path, '/v1/trust/verification/documents/vdoc_0005');

      final badge = await repo.publicBadge('sup_cn_018');
      expect(badge.level, 'documented');
      expect(a.calls.last.path, '/v1/trust/suppliers/sup_cn_018/verification');
      expect(a.calls.last.headers.containsKey('Authorization'), isFalse);
    });

    test('errors map to ApiException with codes and Retry-After', () async {
      final a = _Adapter((o) {
        if (o.method == 'POST') {
          if ((o.data as Map)['number'] == 'DUP-0001') {
            return _json(_load('error_verification_duplicate') as Object, 409);
          }
          return _json(_load('error_verification_rate_limited') as Object, 429, {
            'retry-after': ['125'],
          });
        }
        if (o.method == 'DELETE') {
          return _json(_load('error_verification_withdraw_conflict') as Object, 409);
        }
        return _json(_load('error_supplier_verification_required') as Object, 403);
      });
      final repo = LiveVerificationRepository(_client(a));

      Future<ApiException> catching(Future<Object?> Function() f) async {
        try {
          await f();
        } on ApiException catch (e) {
          return e;
        }
        throw StateError('expected ApiException');
      }

      final limited = await catching(() => repo.submit(_validDraft));
      expect(limited.status, 429);
      expect(limited.retryAfterSeconds, 125);
      expect(verificationErrorKey(limited), 'ver.err.rate_limited_wait');

      final dup = await catching(() => repo.submit(const VerificationDraft(
            docType: 'business_license',
            country: 'IQ',
            number: 'DUP-0001',
            consent: true,
            files: ['/v1/media/private/a.jpg'],
          )));
      expect(verificationErrorKey(dup), 'ver.err.duplicate');

      final conflict = await catching(() => repo.withdraw('vdoc_0002'));
      expect(verificationErrorKey(conflict), 'ver.err.transition');

      final gated = await catching(repo.listMine);
      expect(verificationErrorKey(gated), 'ver.err.supplier_required');
    });
  });

  group('mock repository', () {
    test('lists seeded documents and the level', () async {
      final repo = MockVerificationRepository();
      final list = await repo.listMine();
      expect(list.items.map((d) => d.status), containsAll(['approved', 'rejected']));
      expect(list.level, 'basic');
    });

    test('submit adds a pending document with a masked number', () async {
      final repo = MockVerificationRepository();
      final d = await repo.submit(_validDraft);
      expect(d.status, 'pending');
      expect(d.issuingCountry, 'IQ');
      expect(d.numberMasked, '****2345');
      expect((await repo.listMine()).items.first.id, d.id);
    });

    test('duplicate, rate limit, withdraw rules', () async {
      final repo = MockVerificationRepository(maxSubmissions: 1);
      final d = await repo.submit(_validDraft);
      await expectLater(
        repo.submit(_validDraft),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 429)),
      );
      final repo2 = MockVerificationRepository();
      await repo2.submit(_validDraft);
      await expectLater(
        repo2.submit(_validDraft),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'duplicate_document')),
      );
      final w = await repo.withdraw(d.id);
      expect(w.status, 'withdrawn');
      await expectLater(
        repo.withdraw(d.id),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'invalid_transition')),
      );
      await expectLater(
        repo.withdraw('nope'),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 404)),
      );
      await expectLater(
        repo.withdraw('vdoc_mock_2'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'invalid_transition')),
      );
    });

    test('public badge is deterministic and uses valid levels', () async {
      final repo = MockVerificationRepository();
      final a = await repo.publicBadge('sup_cn_018');
      final b = await repo.publicBadge('sup_cn_018');
      expect(a.level, b.level);
      expect(kVerificationLevels, contains(a.level));
    });
  });
}
