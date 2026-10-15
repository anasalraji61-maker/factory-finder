import 'package:factory_finder/features/messages/data/chat_logic.dart';
import 'package:factory_finder/features/messages/data/chat_socket.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:flutter_test/flutter_test.dart';

ChatMessage _echo(String id, String body, String? cid, {String sender = currentUserId}) =>
    ChatMessage.fromJson({
      'id': id,
      'conversation_id': 'c1',
      'sender_id': sender,
      'type': 'text',
      'text': body,
      'created_at': '2026-10-15T10:00:00Z',
      if (cid != null) 'client_id': cid,
    });

void main() {
  group('client_id', () {
    test('generated ids satisfy the contract pattern and are unique', () {
      final ids = {for (var i = 0; i < 200; i++) newClientId()};
      expect(ids.length, 200);
      for (final id in ids) {
        expect(RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(id), isTrue, reason: id);
      }
    });

    test('tolerant parsing: absent, empty or malformed is null', () {
      expect(_echo('m1', 'x', null).clientId, isNull);
      expect(_echo('m1', 'x', '').clientId, isNull);
      expect(_echo('m1', 'x', 'bad id!').clientId, isNull);
      expect(_echo('m1', 'x', 'a' * 65).clientId, isNull);
      expect(_echo('m1', 'x', 'ok_1-A').clientId, 'ok_1-A');
    });

    test('echo with the same client_id replaces the optimistic copy even if the body differs', () {
      final local = optimisticMessage(
        conversationId: 'c1',
        text: 'hello',
        now: DateTime.utc(2026, 10, 15, 9),
        seq: 1,
        clientId: 'cid_1',
      );
      final list = appendIncoming([local], _echo('srv_1', 'hello (masked)', 'cid_1'));
      expect(list.length, 1);
      expect(list.single.id, 'srv_1');
      expect(list.single.status, SendStatus.sent);
    });

    test('two identical-body messages with different client_ids stay separate', () {
      final a = optimisticMessage(
          conversationId: 'c1', text: 'ok', now: DateTime.utc(2026, 10, 15, 9), seq: 1, clientId: 'a');
      final b = optimisticMessage(
          conversationId: 'c1', text: 'ok', now: DateTime.utc(2026, 10, 15, 9, 1), seq: 2, clientId: 'b');
      final list = appendIncoming([a, b], _echo('srv_2', 'ok', 'b'));
      expect(list.map((m) => m.id), containsAll(['local_1', 'srv_2']));
      expect(list.length, 2);
    });

    test('a repeated echo after the REST reply does not duplicate', () {
      final local = optimisticMessage(
          conversationId: 'c1', text: 'hi', now: DateTime.utc(2026, 10, 15, 9), seq: 1, clientId: 'c');
      final sent = _echo('srv_1', 'hi', 'c');
      var list = confirmSent([local], 'local_1', sent);
      list = appendIncoming(list, _echo('srv_9', 'hi', 'c'));
      expect(list.length, 1);
    });

    test('echo without client_id still falls back to body matching', () {
      final local = optimisticMessage(
          conversationId: 'c1', text: 'hi', now: DateTime.utc(2026, 10, 15, 9), seq: 1);
      final list = appendIncoming([local], _echo('srv_1', 'hi', null));
      expect(list.length, 1);
      expect(list.single.id, 'srv_1');
    });

    test('mergeServer drops a local pending copy whose client_id the server has', () {
      final local = optimisticMessage(
          conversationId: 'c1', text: 'hi', now: DateTime.utc(2026, 10, 15, 9), seq: 1, clientId: 'c');
      final merged = mergeServer([local], [_echo('srv_1', 'hi', 'c')]);
      expect(merged.map((m) => m.id), ['srv_1']);
    });

    test('retry reuses the client_id; the mock replays idempotently and echoes it', () async {
      final repo = MockMessagingRepository();
      final conv = (await repo.conversations()).first;
      final cid = newClientId();
      final first = await repo.send(conv.id, 'hello', clientId: cid);
      final retry = await repo.send(conv.id, 'hello', clientId: cid);
      expect(first.clientId, cid);
      expect(retry.id, first.id);
      final all = await repo.messages(conv.id);
      expect(all.where((m) => m.clientId == cid).length, 1);
    });

    test('toJson/fromJson round-trips client_id', () {
      final m = _echo('m1', 'x', 'cid_9');
      expect(ChatMessage.fromJson(m.toJson()).clientId, 'cid_9');
    });
  });
}
