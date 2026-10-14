import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/my_products/media/image_pick_service.dart';
import 'package:factory_finder/features/my_products/media/media_logic.dart';
import 'package:factory_finder/features/my_products/media/media_repository.dart';
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

ResponseBody _json(Object body, int status, {Map<String, List<String>>? headers}) =>
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

PickedImage _img() => PickedImage(
      bytes: Uint8List.fromList(<int>[1, 2, 3, 4, 5]),
      filename: 'lamp.png',
      mime: 'image/png',
    );

final Map<String, Object> _ok = <String, Object>{
  'id': 'a' * 32,
  'url': '/v1/media/files/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png',
  'width': 640,
  'height': 480,
  'bytes': 5,
  'content_type': 'image/png',
  'kind': 'listing',
  'widths': <int>[200, 400],
};

void main() {
  test('multipart request: field file + kind, bearer token, parsed response', () async {
    final a = _Adapter((o) => _json(_ok, 201));
    final api = _client(a);
    api.tokens.set('tok', null);
    final up = await LiveMediaRepository(api).uploadImage(_img());

    final call = a.calls.single;
    expect(call.method, 'POST');
    expect(call.path, '/v1/media/images');
    expect(call.headers['Authorization'], 'Bearer tok');
    final form = call.data as FormData;
    expect(form.files.single.key, 'file');
    expect(form.files.single.value.filename, 'lamp.png');
    expect(form.files.single.value.length, 5);
    expect(form.fields.any((e) => e.key == 'kind' && e.value == 'listing'), isTrue);
    expect(up.url, startsWith('/v1/media/files/'));
    expect(up.width, 640);
    expect(up.contentType, 'image/png');
  });

  test('upload errors map to ApiException and i18n keys', () async {
    Future<Object> failWith(int status, {Map<String, List<String>>? headers}) async {
      final a = _Adapter((o) => _json(
            <String, Object>{
              'error': <String, Object>{'code': 'x', 'message': 'm'},
            },
            status,
            headers: headers,
          ));
      try {
        await LiveMediaRepository(_client(a)).uploadImage(_img());
      } catch (e) {
        return e;
      }
      throw StateError('expected failure');
    }

    expect(mediaErrorKey(await failWith(401)), 'myp.media.err.auth');
    expect(mediaErrorKey(await failWith(413)), 'myp.media.err.too_large');
    expect(mediaErrorKey(await failWith(415)), 'myp.media.err.type');
    expect(mediaErrorKey(await failWith(422)), 'myp.media.err.corrupt');
    expect(mediaErrorKey(await failWith(429)), 'myp.media.err.quota');
    final limited = await failWith(429, headers: <String, List<String>>{
      'retry-after': <String>['30'],
    });
    expect((limited as ApiException).retryAfterSeconds, 30);
    expect(mediaErrorKey(limited), 'myp.media.err.quota_wait');
    expect(mediaErrorKey(await failWith(500)), 'myp.media.err.generic');
    expect(mediaErrorKey(StateError('x')), 'myp.media.err.generic');
  });

  test('client-side size and type check', () {
    expect(checkImageFile(bytes: 10, mime: 'image/png'), isNull);
    expect(checkImageFile(bytes: kMaxImageBytes, mime: 'image/webp'), isNull);
    expect(checkImageFile(bytes: kMaxImageBytes + 1, mime: 'image/jpeg'), 'myp.media.err.too_large');
    expect(checkImageFile(bytes: 10, mime: 'image/gif'), 'myp.media.err.type');
    expect(checkImageFile(bytes: 0, mime: 'image/png'), 'myp.media.err.empty');
    expect(inferImageMime('a.JPG', null), 'image/jpeg');
    expect(inferImageMime('a.bin', 'image/png'), 'image/png');
    expect(inferImageMime('a.webp', 'application/octet-stream'), 'image/webp');
    expect(inferImageMime('a.gif', null), '');
  });

  test('reorder logic', () {
    const l = <String>['a', 'b', 'c'];
    expect(moveItem(l, 0, 1), <String>['b', 'a', 'c']);
    expect(moveItem(l, 2, -1), <String>['a', 'c', 'b']);
    expect(moveItem(l, 0, -1), l);
    expect(moveItem(l, 2, 1), l);
    expect(moveItem(l, 5, -1), l);
    expect(l, <String>['a', 'b', 'c']);
  });

  test('url resolution and thumbnails', () {
    expect(resolveMediaUrl('http://h:8000', '/v1/media/files/x.jpg'), 'http://h:8000/v1/media/files/x.jpg');
    expect(resolveMediaUrl('http://h:8000/', '/v1/media/files/x.jpg'), 'http://h:8000/v1/media/files/x.jpg');
    expect(resolveMediaUrl('http://h', 'https://cdn.com/a.jpg'), 'https://cdn.com/a.jpg');
    expect(mediaThumbUrl('http://h', '/v1/media/files/x.jpg'), 'http://h/v1/media/files/x.jpg?w=200');
    expect(mediaThumbUrl('http://h', 'https://cdn.com/a.jpg'), 'https://cdn.com/a.jpg');
  });

  test('mock repo returns a fake local url', () async {
    final up = await MockMediaRepository().uploadImage(_img());
    expect(up.url, startsWith('/v1/media/files/'));
  });
}
