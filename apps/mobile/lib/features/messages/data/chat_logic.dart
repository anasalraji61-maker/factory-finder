import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';

/// Pure helpers for the chat screen (unit-tested).

bool isSameDay(DateTime a, DateTime b) =>
    a.year == b.year && a.month == b.month && a.day == b.day;

String _two(int n) => n.toString().padLeft(2, '0');

String hhmm(DateTime d) => '${_two(d.hour)}:${_two(d.minute)}';

String ymd(DateTime d) => '${d.year}/${_two(d.month)}/${_two(d.day)}';

/// One row of the chat list: either a date separator or a message.
class ChatItem {
  const ChatItem.day(this.day) : message = null;
  const ChatItem.message(this.message) : day = null;

  final DateTime? day;
  final ChatMessage? message;
}

/// Oldest-first messages -> items with a date separator before each new day.
List<ChatItem> buildChatItems(List<ChatMessage> messages) {
  final items = <ChatItem>[];
  DateTime? lastDay;
  for (final m in messages) {
    if (lastDay == null || !isSameDay(lastDay, m.createdAt)) {
      items.add(ChatItem.day(m.createdAt));
      lastDay = m.createdAt;
    }
    items.add(ChatItem.message(m));
  }
  return items;
}

/// A message shown immediately while the request is in flight.
ChatMessage optimisticMessage({
  required String conversationId,
  required String text,
  required DateTime now,
  required int seq,
  List<MessageAttachment> attachments = const <MessageAttachment>[],
}) =>
    ChatMessage(
      id: 'local_$seq',
      conversationId: conversationId,
      senderId: currentUserId,
      body: text.trim(),
      attachments: attachments,
      createdAt: now,
      status: SendStatus.sending,
    );

/// Replace the optimistic message [localId] with the server copy.
List<ChatMessage> confirmSent(List<ChatMessage> list, String localId, ChatMessage sent) {
  final out = <ChatMessage>[];
  var replaced = false;
  for (final m in list) {
    if (m.id == localId) {
      out.add(sent);
      replaced = true;
    } else if (m.id != sent.id) {
      out.add(m);
    }
  }
  if (!replaced) out.add(sent);
  out.sort((a, b) => a.createdAt.compareTo(b.createdAt));
  return out;
}

List<ChatMessage> markFailed(List<ChatMessage> list, String localId) => [
      for (final m in list)
        if (m.id == localId) m.copyWith(status: SendStatus.failed) else m,
    ];

List<ChatMessage> removeMessage(List<ChatMessage> list, String id) =>
    [for (final m in list) if (m.id != id) m];

/// Merge a polled server list with local state, keeping unsent local messages.
List<ChatMessage> mergeServer(List<ChatMessage> local, List<ChatMessage> server) {
  final ids = {for (final m in server) m.id};
  final out = <ChatMessage>[
    ...server,
    for (final m in local)
      if (m.status != SendStatus.sent && !ids.contains(m.id)) m,
  ];
  out.sort((a, b) => a.createdAt.compareTo(b.createdAt));
  return out;
}

/// Server preview placeholders (`[image]` ...) -> i18n keys.
const Map<String, String> kPreviewKeys = <String, String>{
  '[image]': 'messages.preview.image',
  '[document]': 'messages.preview.document',
  '[attachment]': 'messages.preview.attachment',
};

/// i18n key when [preview] is (or starts with) a server placeholder, else null.
String? previewKeyOf(String preview) {
  final p = preview.trimLeft();
  for (final e in kPreviewKeys.entries) {
    if (p.startsWith(e.key)) return e.value;
  }
  return null;
}

/// Text after a leading placeholder (a caption), or [preview] unchanged.
String previewRest(String preview) {
  final p = preview.trimLeft();
  for (final k in kPreviewKeys.keys) {
    if (p.startsWith(k)) return p.substring(k.length).trim();
  }
  return preview;
}

/// Preview text for a conversation row; [t] resolves an i18n key.
String localizedPreview(String preview, String Function(String key) t) {
  final key = previewKeyOf(preview);
  if (key == null) return preview;
  final rest = previewRest(preview);
  return rest.isEmpty ? t(key) : '${t(key)} $rest';
}

/// Preview a conversation row would show right after sending locally.
String localPreview(String text, List<MessageAttachment> attachments) {
  if (text.trim().isNotEmpty || attachments.isEmpty) return text.trim();
  if (attachments.every((a) => a.isImage)) return '[image]';
  if (attachments.every((a) => !a.isImage)) return '[document]';
  return '[attachment]';
}

/// i18n key for a failed send (contract 422 codes), or null for generic failures.
String? sendErrorKey(Object error) {
  if (error is ApiException) {
    switch (error.code) {
      case 'too_many_attachments':
        return 'messages.err.too_many';
      case 'attachment_url_not_allowed':
      case 'invalid_attachment':
        return 'messages.err.invalid_attachment';
    }
    return apiErrorKey(error);
  }
  return null;
}
