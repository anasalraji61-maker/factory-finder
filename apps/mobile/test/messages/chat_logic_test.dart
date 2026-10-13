import 'package:factory_finder/features/messages/data/chat_logic.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final t0 = DateTime(2026, 10, 13, 12, 0);

  test('model JSON round trip', () async {
    final repo = MockMessagingRepository(clock: () => t0);
    final c = (await repo.conversations()).first;
    final back = Conversation.fromJson(c.toJson());
    expect(back.id, c.id);
    expect(back.title, c.title);
    expect(back.unread, c.unread);
    expect(back.context?.type, c.context?.type);
    final m = ChatMessage(
      id: 'a',
      conversationId: 'c',
      senderId: currentUserId,
      body: 'مرحبا',
      createdAt: t0.toUtc(),
    );
    final r = ChatMessage.fromJson(m.toJson());
    expect(r.body, 'مرحبا');
    expect(r.isMine, isTrue);
    expect(r.createdAt.toUtc(), m.createdAt.toUtc());
  });

  test('date separators are inserted once per day', () {
    ChatMessage mk(String id, DateTime d) => ChatMessage(
        id: id, conversationId: 'c', senderId: 'x', body: id, createdAt: d);
    final items = buildChatItems([
      mk('1', DateTime(2026, 10, 12, 9)),
      mk('2', DateTime(2026, 10, 12, 10)),
      mk('3', DateTime(2026, 10, 13, 8)),
    ]);
    expect(items.where((i) => i.day != null).length, 2);
    expect(items.length, 5);
    expect(items.first.day, isNotNull);
  });

  test('optimistic send: pending -> confirmed', () {
    final pending = optimisticMessage(
        conversationId: 'c', text: '  hi  ', now: t0, seq: 1);
    expect(pending.status, SendStatus.sending);
    expect(pending.body, 'hi');
    final sent = ChatMessage(
        id: 'srv_1',
        conversationId: 'c',
        senderId: currentUserId,
        body: 'hi',
        createdAt: t0);
    final out = confirmSent([pending], pending.id, sent);
    expect(out.length, 1);
    expect(out.single.id, 'srv_1');
    expect(out.single.status, SendStatus.sent);
  });

  test('optimistic send: failure keeps message, poll merge keeps it', () {
    final pending = optimisticMessage(
        conversationId: 'c', text: 'x', now: t0, seq: 2);
    final failed = markFailed([pending], pending.id);
    expect(failed.single.status, SendStatus.failed);
    final merged = mergeServer(failed, const []);
    expect(merged.single.id, pending.id);
    expect(removeMessage(merged, pending.id), isEmpty);
  });

  test('merge does not duplicate a confirmed message', () {
    final sent = ChatMessage(
        id: 'srv_1',
        conversationId: 'c',
        senderId: currentUserId,
        body: 'hi',
        createdAt: t0);
    final merged = mergeServer([sent], [sent]);
    expect(merged.length, 1);
  });

  test('mock repository fixtures and behaviour', () async {
    var now = t0;
    final repo = MockMessagingRepository(clock: () => now);
    final convs = await repo.conversations();
    expect(convs.length, greaterThanOrEqualTo(8));
    for (var i = 1; i < convs.length; i++) {
      expect(convs[i - 1].lastAt.isBefore(convs[i].lastAt), isFalse);
    }
    final target = convs.firstWhere((c) => c.unread > 0);
    await repo.markRead(target.id);
    final after = (await repo.conversations()).firstWhere((c) => c.id == target.id);
    expect(after.unread, 0);

    final before = (await repo.messages(target.id)).length;
    final sent = await repo.send(target.id, 'اختبار');
    expect(sent.isMine, isTrue);
    expect((await repo.messages(target.id)).length, before + 1);
    now = now.add(const Duration(seconds: 5));
    expect((await repo.messages(target.id)).length, before + 2);
  });

  test('createConversation reuses existing supplier+listing', () async {
    final repo = MockMessagingRepository(clock: () => t0, autoReply: false);
    final a = await repo.createConversation(supplierId: 'sup_001', listingId: 'lst_001');
    expect(a.id, 'cnv_001');
    final b = await repo.createConversation(
        supplierId: 'sup_new', listingId: 'lst_99', firstMessage: 'مرحبا');
    expect(b.lastMessage, 'مرحبا');
    expect((await repo.conversations()).length, 9);
  });
}
