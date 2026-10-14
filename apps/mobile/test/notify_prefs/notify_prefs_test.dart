import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_models.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_repository.dart';
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

void main() {
  test('parses the live fixture', () {
    final p = NotifyPrefs.fromJson(_load('notification_prefs'));
    expect(p.isOn('price_drop', 'push'), isTrue);
    expect(p.isOn('price_drop', 'email'), isFalse);
    expect(p.isOn('below_target', 'email'), isTrue);
    expect(p.quietStart, '22:00');
    expect(p.quietEnd, '07:00');
    expect(p.timezone, 'Asia/Baghdad');
    expect(p.language, 'ar');
    expect(p.email, 'buyer@example.com');
  });

  test('tolerant parsing and defaults', () {
    final p = NotifyPrefs.fromJson({
      'channels': {'x': ['push', 'sms'], 'y': 'bad'},
      'quiet_hours': {'start': '25:00', 'end': '07:00'},
      'language': 'fr',
      'timezone': '',
    });
    expect(p.channels['x'], {'push'});
    expect(p.channels.containsKey('y'), isFalse);
    expect(p.hasQuietHours, isFalse);
    expect(p.language, isNull);
    expect(p.timezone, kDefaultTimezone);
    expect(NotifyPrefs.fromJson(null).email, isNull);
    // Unknown alert type defaults to in_app only.
    expect(p.isOn('new_results', 'in_app'), isTrue);
    expect(p.isOn('new_results', 'push'), isFalse);
  });

  test('update body: channels, quiet hours, clear flag, email', () {
    final base = NotifyPrefs.fromJson(_load('notification_prefs'));
    final body = base.withChannel('price_drop', 'email', true).toUpdateJson();
    expect((body['channels'] as Map)['price_drop'], ['email', 'in_app', 'push']);
    expect(body['quiet_hours'], {'start': '22:00', 'end': '07:00'});
    expect(body.containsKey('clear_quiet_hours'), isFalse);
    expect(body.containsKey('digest_email'), isFalse);
    expect(base.toUpdateJson(digestEmail: 'n@e.co')['digest_email'], 'n@e.co');

    final cleared = base.copyWith(clearQuiet: true).toUpdateJson();
    expect(cleared['clear_quiet_hours'], isTrue);
    expect(cleared.containsKey('quiet_hours'), isFalse);
    expect(cleared.containsKey('digest_email'), isFalse);
  });

  test('time and email helpers', () {
    expect(parseHhmm('07:05')?.hour, 7);
    expect(parseHhmm('7:05')?.minute, 5);
    expect(parseHhmm('24:00'), isNull);
    expect(parseHhmm('12:60'), isNull);
    expect(parseHhmm(null), isNull);
    expect(parseHhmm('abc'), isNull);
    expect(formatHhmm(7, 5), '07:05');
    expect(validateDigestEmail(''), isNull);
    expect(validateDigestEmail(null), isNull);
    expect(validateDigestEmail('a@b.co'), isNull);
    expect(validateDigestEmail('a@b'), 'notifyprefs.err_email');
    expect(validateDigestEmail('a b@c.com'), 'notifyprefs.err_email');
  });

  test('live repo: GET then PUT', () async {
    final a = _Adapter((o) => ResponseBody.fromString(
          jsonEncode(_load('notification_prefs')),
          200,
          headers: {
            Headers.contentTypeHeader: [Headers.jsonContentType],
          },
        ));
    final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
    dio.httpClientAdapter = a;
    final repo = LiveNotifyPrefsRepository(
      ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio),
    );
    final p = await repo.get();
    expect(a.calls.first.path, '/v1/notification-prefs');
    final saved = await repo.save(p.copyWith(timezone: 'UTC'));
    expect(a.calls.last.method, 'PUT');
    expect((a.calls.last.data as Map)['timezone'], 'UTC');
    expect(saved.language, 'ar');
  });
}
