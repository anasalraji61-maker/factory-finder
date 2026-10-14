import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_models.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_repository.dart';
import 'package:flutter_test/flutter_test.dart';

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

void main() {
  test('verification state mapping', () {
    expect(digestEmailState(NotifyPrefs.fromJson(<String, Object>{})), DigestEmailState.none);
    expect(
      digestEmailState(NotifyPrefs.fromJson(<String, Object>{
        'digest_email': 'a@b.co',
        'digest_email_verified': true,
      })),
      DigestEmailState.verified,
    );
    final pending = NotifyPrefs.fromJson(<String, Object?>{
      'digest_email': null,
      'digest_email_verified': false,
      'digest_email_pending': 'a***@e***.com',
    });
    expect(digestEmailState(pending), DigestEmailState.pending);
    expect(pending.digestEmailPending, 'a***@e***.com');
    // Legacy response with only `email`.
    expect(
      digestEmailState(NotifyPrefs.fromJson(<String, Object>{'email': 'a@b.co'})),
      DigestEmailState.verified,
    );
    // Flag false and an address present: not verified.
    expect(
      digestEmailState(NotifyPrefs.fromJson(<String, Object>{
        'digest_email': 'a@b.co',
        'digest_email_verified': false,
      })),
      DigestEmailState.none,
    );
  });

  test('digest email to send, code format, masking', () {
    expect(digestEmailToSend(input: 'a@b.co', baseline: 'a@b.co'), isNull);
    expect(digestEmailToSend(input: ' new@b.co ', baseline: 'a@b.co'), 'new@b.co');
    expect(digestEmailToSend(input: '', baseline: 'a@b.co'), '');
    expect(digestEmailToSend(input: '', baseline: ''), isNull);
    expect(isValidVerificationCode('123456'), isTrue);
    expect(isValidVerificationCode('12345'), isFalse);
    expect(isValidVerificationCode('12345a'), isFalse);
    expect(maskEmail('anas@example.com'), 'a***@e***.com');
    final body = const NotifyPrefs().toUpdateJson(digestEmail: 'x@y.co');
    expect(body['digest_email'], 'x@y.co');
    expect(const NotifyPrefs().toUpdateJson().containsKey('digest_email'), isFalse);
  });

  test('resend cooldown is a pure function', () {
    final t0 = DateTime(2026, 1, 1, 12);
    expect(resendCooldownRemaining(null, t0), 0);
    expect(resendCooldownRemaining(t0, t0), 60);
    expect(resendCooldownRemaining(t0, t0.add(const Duration(seconds: 25))), 35);
    expect(resendCooldownRemaining(t0, t0.add(const Duration(seconds: 60))), 0);
    expect(resendCooldownRemaining(t0, t0.add(const Duration(minutes: 5))), 0);
  });

  test('error mapping', () {
    ApiException e(int s, String c) => ApiException(status: s, code: c, message: '');
    expect(digestEmailErrorKey(e(422, 'invalid_code')), 'notifyprefs.err.invalid_code');
    expect(digestEmailErrorKey(e(422, 'code_expired')), 'notifyprefs.err.code_expired');
    expect(digestEmailErrorKey(e(409, 'no_pending')), 'notifyprefs.err.no_pending');
    expect(digestEmailErrorKey(e(429, 'locked')), 'notifyprefs.err.locked');
    expect(digestEmailErrorKey(e(429, 'send_limit')), 'notifyprefs.err.send_limit');
    expect(digestEmailErrorKey(e(409, 'email_disabled')), 'notifyprefs.err.email_disabled');
    expect(digestEmailErrorKey(e(500, 'boom')), 'notifyprefs.err.generic');
    expect(digestEmailErrorKey(StateError('x')), 'notifyprefs.err.generic');
  });

  test('live repo: verify and resend call the right endpoints', () async {
    final a = _Adapter((o) => ResponseBody.fromString(
          jsonEncode(<String, Object?>{
            'digest_email': 'a@b.co',
            'digest_email_verified': true,
            'digest_email_pending': null,
          }),
          200,
          headers: <String, List<String>>{
            Headers.contentTypeHeader: <String>[Headers.jsonContentType],
          },
        ));
    final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
    dio.httpClientAdapter = a;
    final repo = LiveNotifyPrefsRepository(
      ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio),
    );
    final p = await repo.verifyEmail('123456');
    expect(a.calls.last.path, '/v1/notification-prefs/verify-email');
    expect((a.calls.last.data as Map)['code'], '123456');
    expect(digestEmailState(p), DigestEmailState.verified);
    await repo.resendCode();
    expect(a.calls.last.path, '/v1/notification-prefs/resend-code');
    await repo.save(const NotifyPrefs(), digestEmail: 'n@e.co');
    expect(a.calls.last.method, 'PUT');
    expect((a.calls.last.data as Map)['digest_email'], 'n@e.co');
  });

  test('mock repo: pending, wrong code, right code', () async {
    final repo = MockNotifyPrefsRepository();
    var p = await repo.get();
    expect(digestEmailState(p), DigestEmailState.none);
    await expectLater(repo.verifyEmail('123456'), throwsA(isA<ApiException>()));
    p = await repo.save(p, digestEmail: 'user@example.com');
    expect(digestEmailState(p), DigestEmailState.pending);
    expect(p.digestEmailPending, 'u***@e***.com');
    await expectLater(repo.verifyEmail('000000'), throwsA(isA<ApiException>()));
    p = await repo.verifyEmail(MockNotifyPrefsRepository.mockCode);
    expect(digestEmailState(p), DigestEmailState.verified);
    expect(p.email, 'user@example.com');
  });
}
