import 'dart:async';
import 'dart:convert';

import 'package:factory_finder/features/messages/data/chat_socket.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:flutter_test/flutter_test.dart';

String frame(String id, {String conv = 'c1', String sender = 'u2', String at = '2026-10-13T10:00:00Z'}) =>
    jsonEncode({
      'type': 'message.created',
      'message': {
        'id': id,
        'conversation_id': conv,
        'sender_id': sender,
        'type': 'text',
        'text': 'hi $id',
        'created_at': at,
      },
    });

class FakeChannel implements ChatChannel {
  final StreamController<dynamic> c = StreamController<dynamic>();
  final List<String> sent = [];
  @override
  int? closeCode;
  @override
  Stream<dynamic> get incoming => c.stream;
  @override
  void add(String data) => sent.add(data);
  @override
  Future<void> close() async {}
  void serverClose(int code) {
    closeCode = code;
    c.close();
  }
}

void main() {
  test('frame parsing', () {
    final m = parseMessageFrame(frame('m1'), myUserId: 'u2', conversationId: 'c1');
    expect(m, isNotNull);
    expect(m!.id, 'm1');
    expect(m.body, 'hi m1');
    expect(m.isMine, isTrue);
    expect(parseMessageFrame(frame('m1', conv: 'other'), conversationId: 'c1'), isNull);
    expect(parseMessageFrame('{"type":"typing","user_id":"u"}'), isNull);
    expect(parseMessageFrame('not json'), isNull);
    expect(parseMessageFrame('{"type":"message.created"}'), isNull);
  });

  test('appendIncoming dedupes by id and keeps order', () {
    final a = parseMessageFrame(frame('a', at: '2026-10-13T10:00:00Z'))!;
    final b = parseMessageFrame(frame('b', at: '2026-10-13T09:00:00Z'))!;
    var list = appendIncoming(const <ChatMessage>[], a);
    list = appendIncoming(list, a);
    expect(list.length, 1);
    list = appendIncoming(list, b);
    expect(list.map((m) => m.id), ['b', 'a']);
  });

  test('backoff schedule', () {
    expect([for (var i = 0; i < 8; i++) backoffDelay(i).inSeconds], [1, 2, 4, 8, 16, 30, 30, 30]);
    expect(backoffDelay(-1).inSeconds, 1);
  });

  test('uri uses ws scheme and ticket', () {
    final u = chatSocketUri('https://api.example.com/', 'c1', 'tok');
    expect(u.toString(), 'wss://api.example.com/v1/ws/conversations/c1?ticket=tok');
    final d = chatSocketUri('http://10.0.2.2:8000', 'c1', 't');
    expect(d.scheme, 'ws');
    expect(d.port, 8000);
  });

  test('fatal codes and 4401 refresh-once', () async {
    expect(isFatalCloseCode(4403), isTrue);
    expect(isFatalCloseCode(4404), isTrue);
    expect(isFatalCloseCode(4401), isFalse);

    final channels = <FakeChannel>[];
    var refreshes = 0;
    final s = LiveChatSocket(
      baseUrl: 'http://h',
      conversationId: 'c1',
      accessToken: () => 'tok',
      refreshSession: () async {
        refreshes++;
        return true;
      },
      ticketProvider: () async => 'wst_x',
      connector: (uri) async {
        final ch = FakeChannel();
        channels.add(ch);
        return ch;
      },
    );
    final got = <String>[];
    s.messages.listen((m) => got.add(m.id));
    s.connect();
    await Future<void>.delayed(Duration.zero);
    expect(s.status, ChatSocketStatus.connected);
    channels[0].c.add(frame('m1'));
    await Future<void>.delayed(Duration.zero);
    expect(got, ['m1']);

    channels[0].serverClose(4401);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(refreshes, 1);
    expect(channels.length, 2);
    expect(s.status, ChatSocketStatus.connected);

    channels[1].serverClose(4403);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(s.status, ChatSocketStatus.failed);
    expect(channels.length, 2);
    await s.close();
  });

  test('ticket uri uses ticket param, not token', () {
    final u = chatSocketUri('https://api.example.com', 'c1', 'wst_abc');
    expect(u.toString(), 'wss://api.example.com/v1/ws/conversations/c1?ticket=wst_abc');
    expect(u.queryParameters.containsKey('token'), isFalse);
  });

  test('uses the ticket from ticketProvider', () async {
    final uris = <Uri>[];
    final s = LiveChatSocket(
      baseUrl: 'http://h',
      conversationId: 'c1',
      accessToken: () => 'tok',
      refreshSession: () async => true,
      ticketProvider: () async => 'wst_1',
      connector: (uri) async {
        uris.add(uri);
        return FakeChannel();
      },
    );
    s.connect();
    await Future<void>.delayed(const Duration(milliseconds: 5));
    expect(uris.single.queryParameters, {'ticket': 'wst_1'});
    expect(uris.single.toString().contains('tok'), isFalse);
    await s.close();
  });

  for (final mode in ['null', 'throws']) {
    test('ticket failure ($mode) never dials with the token; backs off then recovers', () async {
      final uris = <Uri>[];
      var calls = 0;
      var refreshes = 0;
      final s = LiveChatSocket(
        baseUrl: 'http://h',
        conversationId: 'c1',
        accessToken: () => 'secret-access-token',
        refreshSession: () async {
          refreshes++;
          return false;
        },
        ticketProvider: () async {
          calls++;
          if (calls == 1) {
            if (mode == 'throws') throw Exception('boom');
            return null;
          }
          return 'wst_ok';
        },
        connector: (uri) async {
          uris.add(uri);
          return FakeChannel();
        },
      );
      s.connect();
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(uris, isEmpty);
      expect(s.status, ChatSocketStatus.reconnecting);
      expect(refreshes, 1);
      // First backoff step is 1s.
      await Future<void>.delayed(const Duration(milliseconds: 1200));
      expect(uris.single.toString().contains('secret-access-token'), isFalse);
      expect(uris.single.queryParameters, {'ticket': 'wst_ok'});
      expect(s.status, ChatSocketStatus.connected);
      await s.close();
    });
  }

  test('connect twice while opening opens a single socket', () async {
    var calls = 0;
    final gate = Completer<void>();
    final s = LiveChatSocket(
      baseUrl: 'http://h',
      conversationId: 'c1',
      accessToken: () => 'tok',
      refreshSession: () async => true,
      ticketProvider: () async => 'wst_x',
      connector: (uri) async {
        calls++;
        await gate.future;
        return FakeChannel();
      },
    );
    s.connect();
    s.connect();
    await Future<void>.delayed(Duration.zero);
    gate.complete();
    await Future<void>.delayed(const Duration(milliseconds: 5));
    s.connect();
    expect(calls, 1);
    await s.close();
  });

  test('handshake failure refreshes the session once and retries', () async {
    var token = 'old';
    var refreshes = 0;
    final seen = <String?>[];
    final s = LiveChatSocket(
      baseUrl: 'http://h',
      conversationId: 'c1',
      accessToken: () => token,
      refreshSession: () async {
        refreshes++;
        token = 'new';
        return true;
      },
      ticketProvider: () async => 'wst_$token',
      connector: (uri) async {
        seen.add(uri.queryParameters['ticket']);
        if (uri.queryParameters['ticket'] == 'wst_old') throw Exception('401');
        return FakeChannel();
      },
    );
    s.connect();
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(refreshes, 1);
    expect(seen, ['wst_old', 'wst_new']);
    expect(s.status, ChatSocketStatus.connected);
    await s.close();
  });
}
