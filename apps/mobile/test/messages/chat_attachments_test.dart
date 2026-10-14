import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/messages/data/chat_logic.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:flutter_test/flutter_test.dart';

const String _myId = 'usr_21403c1febf04074ad43675c33496143';

Map<String, dynamic> _obj(String name) => Map<String, dynamic>.from(
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync()) as Map);

class _Adapter implements HttpClientAdapter {
  final List<RequestOptions> calls = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return ResponseBody.fromString(
      File('test/fixtures/live/message_send.json').readAsStringSync(),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  final t0 = DateTime(2026, 10, 14, 12);

  group('parsing', () {
    test('messages fixture with attachments[]', () {
      final page = _obj('messages_attachments');
      final msgs = [
        for (final m in page['items'] as List)
          ChatMessage.fromJson(Map<String, dynamic>.from(m as Map), myUserId: _myId),
      ];
      final a = msgs.first;
      expect(a.isMine, isFalse);
      expect(a.body, '');
      // The entry without a url is skipped, the rest keep their fields.
      expect(a.attachments, hasLength(2));
      expect(a.attachments[0].isImage, isTrue);
      expect(a.attachments[0].url, startsWith('/v1/media/files/'));
      expect(a.attachments[0].size, 48213);
      expect(a.attachments[0].name, 'sample.jpg');
      expect(a.attachments[1].kind, AttachmentKind.document);
      expect(a.attachments[1].size, isNull);
      expect(msgs.last.attachments, isEmpty);
      expect(msgs.last.body, 'hello there');
    });

    test('copyWith keeps attachments; toJson round trip', () {
      final m = ChatMessage.fromJson({
        'id': 'm1',
        'conversation_id': 'c',
        'sender_id': 'x',
        'type': 'text',
        'attachments': [
          {'url': '/v1/media/files/a.jpg', 'kind': 'image'},
        ],
        'created_at': '2026-10-13T18:35:00Z',
      });
      expect(m.copyWith(status: SendStatus.failed).attachments, hasLength(1));
      final again = ChatMessage.fromJson(m.toJson());
      expect(again.attachments.single.url, '/v1/media/files/a.jpg');
    });

    test('conversation preview placeholders', () {
      final page = _obj('conversations_attachment_preview');
      final list = [
        for (final c in page['items'] as List)
          Conversation.fromJson(Map<String, dynamic>.from(c as Map), myUserId: _myId),
      ];
      expect(list[0].lastMessage, '[image]');
      expect(previewKeyOf(list[0].lastMessage), 'messages.preview.image');
      expect(previewKeyOf(list[1].lastMessage), 'messages.preview.document');
      String t(String k) => '<$k>';
      expect(localizedPreview('[image]', t), '<messages.preview.image>');
      expect(localizedPreview('[document] see attached', t),
          '<messages.preview.document> see attached');
      expect(localizedPreview('[attachment]', t), '<messages.preview.attachment>');
      expect(localizedPreview('hello', t), 'hello');
    });

    test('localPreview mirrors the server placeholders', () {
      const img = MessageAttachment(url: '/a.jpg');
      const doc = MessageAttachment(url: '/a.pdf', kind: AttachmentKind.document);
      expect(localPreview('hi', const [img]), 'hi');
      expect(localPreview('', const [img, img]), '[image]');
      expect(localPreview('', const [doc]), '[document]');
      expect(localPreview('', const [img, doc]), '[attachment]');
      expect(localPreview(' x ', const []), 'x');
    });
  });

  group('errors', () {
    test('422 attachment codes map to strings', () {
      ApiException e(String code) => ApiException(status: 422, code: code, message: 'm');
      expect(sendErrorKey(e('too_many_attachments')), 'messages.err.too_many');
      expect(sendErrorKey(e('attachment_url_not_allowed')), 'messages.err.invalid_attachment');
      expect(sendErrorKey(e('invalid_attachment')), 'messages.err.invalid_attachment');
      expect(sendErrorKey(e('validation_error')), isNull);
      expect(sendErrorKey(Exception('x')), isNull);
    });
  });

  group('mock repository', () {
    test('send with attachments updates preview and thumbnails', () async {
      final repo = MockMessagingRepository(clock: () => t0, autoReply: false);
      const att = [
        MessageAttachment(url: '/v1/media/files/a.jpg', size: 10, name: 'a.jpg'),
        MessageAttachment(url: '/v1/media/files/b.jpg', size: 11, name: 'b.jpg'),
      ];
      final sent = await repo.send('cnv_002', '', attachments: att);
      expect(sent.attachments, hasLength(2));
      final conv = (await repo.conversations()).firstWhere((c) => c.id == 'cnv_002');
      expect(conv.lastMessage, '[image]');
      expect(conv.lastAttachments, hasLength(2));
      final msgs = await repo.messages('cnv_002');
      expect(msgs.last.attachments, hasLength(2));
      await repo.send('cnv_002', 'caption', attachments: att);
      final conv2 = (await repo.conversations()).firstWhere((c) => c.id == 'cnv_002');
      expect(conv2.lastMessage, 'caption');
    });

    test('rejects more than five attachments and empty messages', () async {
      final repo = MockMessagingRepository(clock: () => t0, autoReply: false);
      final six = List<MessageAttachment>.generate(
          6, (i) => MessageAttachment(url: '/v1/media/files/$i.jpg'));
      await expectLater(
        repo.send('cnv_001', 'x', attachments: six),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'too_many_attachments')),
      );
      await expectLater(
        repo.send('cnv_001', '  '),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 422)),
      );
    });

    test('fixture conversation has a mid-thread attachment message', () async {
      final repo = MockMessagingRepository(clock: () => t0);
      final msgs = await repo.messages('cnv_004');
      expect(msgs.where((m) => m.attachments.isNotEmpty), hasLength(1));
      expect(msgs.last.attachments, isEmpty);
    });
  });

  group('live repository', () {
    test('send body carries attachments and omits empty text', () async {
      final adapter = _Adapter();
      final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = adapter;
      final api = ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
      final repo = LiveMessagingRepository(api, () => _myId);
      await repo.send('conv_1', '', attachments: const [
        MessageAttachment(url: '/v1/media/files/a.jpg', size: 5, name: 'a.jpg'),
      ]);
      var body = adapter.calls.single.data as Map;
      expect(adapter.calls.single.path, '/v1/conversations/conv_1/messages');
      expect(body['type'], 'text');
      expect(body.containsKey('text'), isFalse);
      expect(body['attachments'], [
        {'url': '/v1/media/files/a.jpg', 'kind': 'image', 'size': 5, 'name': 'a.jpg'},
      ]);

      await repo.send('conv_1', 'hello');
      body = adapter.calls.last.data as Map;
      expect(body['text'], 'hello');
      expect(body.containsKey('attachments'), isFalse);
    });
  });
}
