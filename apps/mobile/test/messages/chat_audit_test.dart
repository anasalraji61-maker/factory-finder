import 'package:factory_finder/features/messages/data/chat_logic.dart';
import 'package:factory_finder/features/messages/data/chat_socket.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final t0 = DateTime(2026, 10, 13, 12, 0);

  ChatMessage mk(
    String id, {
    DateTime? at,
    String sender = 'peer',
    String body = '',
    SendStatus status = SendStatus.sent,
    List<MessageAttachment> attachments = const <MessageAttachment>[],
  }) =>
      ChatMessage(
        id: id,
        conversationId: 'c',
        senderId: sender,
        body: body.isEmpty ? id : body,
        createdAt: at ?? t0,
        status: status,
        attachments: attachments,
      );

  group('ordering', () {
    test('equal timestamps keep their original order (stable)', () {
      final list = [for (var i = 0; i < 30; i++) mk('m$i')];
      final out = sortedByTime(list.reversed.toList().reversed);
      expect([for (final m in out) m.id], [for (final m in list) m.id]);
    });

    test('older messages sort first', () {
      final out = sortedByTime([
        mk('b', at: t0.add(const Duration(seconds: 5))),
        mk('a', at: t0),
      ]);
      expect([for (final m in out) m.id], ['a', 'b']);
    });
  });

  group('optimistic send + server echo', () {
    test('REST reply replaces the local copy', () {
      final local = optimisticMessage(
          conversationId: 'c', text: ' hi ', now: t0, seq: 1);
      expect(local.body, 'hi');
      final out = confirmSent([local], local.id,
          mk('srv1', sender: currentUserId, body: 'hi', at: t0));
      expect(out.length, 1);
      expect(out.single.id, 'srv1');
      expect(out.single.status, SendStatus.sent);
    });

    test('socket echo before REST reply does not duplicate', () {
      final local = optimisticMessage(
          conversationId: 'c', text: 'hi', now: t0, seq: 1);
      final echo = mk('srv1', sender: currentUserId, body: 'hi', at: t0);
      final afterWs = appendIncoming([local], echo);
      expect(afterWs.length, 1);
      expect(afterWs.single.id, 'srv1');
      final afterRest = confirmSent(afterWs, local.id, echo);
      expect(afterRest.length, 1);
      expect(afterRest.single.id, 'srv1');
    });

    test('REST reply before socket echo: echo is ignored', () {
      final local = optimisticMessage(
          conversationId: 'c', text: 'hi', now: t0, seq: 1);
      final echo = mk('srv1', sender: currentUserId, body: 'hi', at: t0);
      final afterRest = confirmSent([local], local.id, echo);
      expect(appendIncoming(afterRest, echo).length, 1);
    });

    test('poll while sending shows the server copy once after confirm', () {
      final local = optimisticMessage(
          conversationId: 'c', text: 'hi', now: t0, seq: 1);
      final echo = mk('srv1', sender: currentUserId, body: 'hi', at: t0);
      final merged = mergeServer([local], [echo]);
      expect(merged.length, 2); // transient: sending + server copy
      final done = confirmSent(merged, local.id, echo);
      expect(done.length, 1);
    });

    test('echo of a different text does not swallow a pending message', () {
      final local = optimisticMessage(
          conversationId: 'c', text: 'one', now: t0, seq: 1);
      final echo = mk('srv9', sender: currentUserId, body: 'other', at: t0);
      expect(appendIncoming([local], echo).length, 2);
    });

    test('peer message with identical text never replaces my pending one', () {
      final local = optimisticMessage(
          conversationId: 'c', text: 'ok', now: t0, seq: 1);
      final peer = mk('p1', body: 'ok');
      expect(appendIncoming([local], peer).length, 2);
    });
  });

  group('failed send', () {
    test('markFailed then retry keeps one message', () {
      final local = optimisticMessage(
          conversationId: 'c', text: 'hi', now: t0, seq: 1);
      final failed = markFailed([local], local.id);
      expect(failed.single.status, SendStatus.failed);
      // A failed message survives a poll that does not know it.
      expect(mergeServer(failed, <ChatMessage>[]).single.id, local.id);
      final out = confirmSent(failed, local.id,
          mk('srv1', sender: currentUserId, body: 'hi', at: t0));
      expect(out.single.id, 'srv1');
    });

    test('removeMessage drops only the target', () {
      final out = removeMessage([mk('a'), mk('b')], 'a');
      expect(out.single.id, 'b');
    });
  });

  group('mergeServer', () {
    test('socket-delivered newer message survives a stale poll', () {
      final old = mk('old', at: t0);
      final fresh = mk('fresh', at: t0.add(const Duration(seconds: 2)));
      final out = mergeServer([old, fresh], [old]);
      expect([for (final m in out) m.id], ['old', 'fresh']);
    });

    test('older sent message missing on the server is dropped', () {
      final gone = mk('gone', at: t0);
      final srv = mk('s', at: t0.add(const Duration(seconds: 2)));
      expect(mergeServer([gone], [srv]).map((m) => m.id), ['s']);
    });

    test('empty server list keeps local messages', () {
      expect(mergeServer([mk('a')], <ChatMessage>[]).length, 1);
    });
  });

  group('long mixed RTL/LTR text', () {
    test('body is preserved verbatim and trimmed only at the edges', () {
      final long = 'مرحبا ${'ABC-123 طلبية ' * 400}https://example.com/${'a' * 500}';
      final m = optimisticMessage(
          conversationId: 'c', text: '  $long \n', now: t0, seq: 1);
      expect(m.body, long.trim());
      expect(ChatMessage.fromJson(m.toJson()).body, m.body);
    });

    test('date separators work for messages across midnight', () {
      final items = buildChatItems([
        mk('a', at: DateTime(2026, 10, 12, 23, 59)),
        mk('b', at: DateTime(2026, 10, 13, 0, 1)),
      ]);
      expect(items.where((i) => i.day != null).length, 2);
    });
  });

  group('unread badge', () {
    test('label bounds', () {
      expect(unreadBadgeLabel(-3), '');
      expect(unreadBadgeLabel(0), '');
      expect(unreadBadgeLabel(7), '7');
      expect(unreadBadgeLabel(99), '99');
      expect(unreadBadgeLabel(100), '99+');
    });

    test('negative server unread_count is clamped to zero', () {
      final c = Conversation.fromJson({
        'id': 'c1',
        'title': 'T',
        'unread_count': -4,
      });
      expect(c.unread, 0);
    });

    test('mock total ignores muted and archived, markRead zeroes', () async {
      final repo = MockMessagingRepository(clock: () => t0);
      final all = await repo.conversations();
      final first = all.first;
      await repo.setPreferences(first.id, muted: true);
      final muted = await repo.unreadTotal();
      await repo.setPreferences(first.id, muted: false);
      final unmuted = await repo.unreadTotal();
      expect(unmuted, greaterThanOrEqualTo(muted));
      expect(unmuted - muted, first.unread);
      await repo.markRead(first.id);
      expect(await repo.unreadTotal(), muted);
    });
  });

  group('attachment and link safety', () {
    const base = 'https://api.example.com';
    test('relative media resolves against base', () {
      expect(safeAttachmentUrl(base, '/v1/media/files/a.jpg'),
          'https://api.example.com/v1/media/files/a.jpg');
      expect(safeAttachmentUrl('$base/', 'x.jpg'),
          'https://api.example.com/x.jpg');
    });

    test('http and https absolute urls are allowed', () {
      expect(safeAttachmentUrl(base, 'https://cdn.x.com/a.png'),
          'https://cdn.x.com/a.png');
      expect(safeAttachmentUrl(base, 'HTTP://cdn.x.com/a.png'),
          'HTTP://cdn.x.com/a.png');
    });

    test('dangerous schemes and malformed urls are rejected', () {
      for (final u in [
        'javascript:alert(1)',
        'JaVaScRiPt:alert(1)',
        'file:///etc/passwd',
        'data:text/html;base64,AAAA',
        'intent://x#Intent;end',
        'ftp://h/x',
        'content://media/1',
        '//evil.com/x.png',
        r'\\evil\share',
        '',
        '   ',
        'https://',
      ]) {
        expect(safeAttachmentUrl(base, u), isNull, reason: u);
      }
    });

    test('only http(s) links can be offered for confirmation', () {
      expect(isConfirmableLink('https://example.com/a?b=1'), isTrue);
      expect(isConfirmableLink('http://example.com'), isTrue);
      expect(isConfirmableLink('javascript:alert(1)'), isFalse);
      expect(isConfirmableLink('tel:+123'), isFalse);
      expect(isConfirmableLink('mailto:a@b.c'), isFalse);
      expect(isConfirmableLink('example.com'), isFalse);
      expect(isConfirmableLink('https://'), isFalse);
    });
  });

  group('reconnect backoff', () {
    test('sequence is capped and never negative', () {
      expect([for (var i = 0; i < 8; i++) backoffDelay(i).inSeconds],
          [1, 2, 4, 8, 16, 30, 30, 30]);
      expect(backoffDelay(-5).inSeconds, 1);
      expect(backoffDelay(1000).inSeconds, 30);
    });

    test('socket url carries only the ticket, never a token', () {
      final u = chatSocketUri('https://h.example.com/api/', 'c1', 'tk');
      expect(u.toString(), 'wss://h.example.com/api/v1/ws/conversations/c1?ticket=tk');
      expect(u.query.contains('token'), isFalse);
    });

    test('malformed frames are ignored without throwing', () {
      for (final raw in [null, 42, '{', '[]', '{"type":"message.created"}']) {
        expect(parseMessageFrame(raw), isNull);
      }
    });
  });
}
