/// Feature models for the Messages tab (hand-written JSON, no codegen).

const String currentUserId = 'me';

enum MessageKind { text, attachment, system }

enum SendStatus { sent, sending, failed }

MessageKind _kindFrom(String? v) {
  switch (v) {
    case 'attachment':
      return MessageKind.attachment;
    case 'system':
      return MessageKind.system;
    default:
      return MessageKind.text;
  }
}

DateTime _date(Object? v, [DateTime? fallback]) {
  if (v is String) {
    final d = DateTime.tryParse(v);
    if (d != null) return d.toLocal();
  }
  return fallback ?? DateTime.fromMillisecondsSinceEpoch(0);
}

class ConversationContext {
  const ConversationContext({required this.type, required this.id, this.title});

  /// 'listing' | 'request' | 'deal'
  final String type;
  final String id;
  final String? title;

  factory ConversationContext.fromJson(Map<String, dynamic> j) => ConversationContext(
        type: (j['type'] ?? j['kind'] ?? 'listing').toString(),
        id: (j['id'] ?? '').toString(),
        title: j['title']?.toString(),
      );

  Map<String, dynamic> toJson() => {
        'type': type,
        'id': id,
        if (title != null) 'title': title,
      };
}

class Conversation {
  const Conversation({
    required this.id,
    required this.title,
    this.participantId = '',
    this.avatarUrl,
    this.context,
    this.lastMessage = '',
    required this.lastAt,
    this.unread = 0,
  });

  final String id;
  final String title;
  final String participantId;
  final String? avatarUrl;
  final ConversationContext? context;
  final String lastMessage;
  final DateTime lastAt;
  final int unread;

  Conversation copyWith({String? lastMessage, DateTime? lastAt, int? unread}) =>
      Conversation(
        id: id,
        title: title,
        participantId: participantId,
        avatarUrl: avatarUrl,
        context: context,
        lastMessage: lastMessage ?? this.lastMessage,
        lastAt: lastAt ?? this.lastAt,
        unread: unread ?? this.unread,
      );

  factory Conversation.fromJson(Map<String, dynamic> j) {
    final participant = j['participant'];
    final last = j['last_message'];
    final ctx = j['context'];
    final updated = _date(j['updated_at'] ?? (last is Map ? last['created_at'] : null));
    return Conversation(
      id: j['id'].toString(),
      title: (j['title'] ??
              (participant is Map ? participant['name'] : null) ??
              '')
          .toString(),
      participantId:
          (participant is Map ? participant['id'] : j['participant_id'] ?? '').toString(),
      avatarUrl: participant is Map ? participant['avatar_url']?.toString() : null,
      context: ctx is Map ? ConversationContext.fromJson(Map<String, dynamic>.from(ctx)) : null,
      lastMessage: (last is Map ? last['body'] : last ?? '').toString(),
      lastAt: updated,
      unread: (j['unread_count'] as num?)?.toInt() ?? 0,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'participant': {'id': participantId, 'name': title, 'avatar_url': avatarUrl},
        if (context != null) 'context': context!.toJson(),
        'last_message': {'body': lastMessage, 'created_at': lastAt.toUtc().toIso8601String()},
        'unread_count': unread,
        'updated_at': lastAt.toUtc().toIso8601String(),
      };
}

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.conversationId,
    required this.senderId,
    this.kind = MessageKind.text,
    this.body = '',
    this.attachmentUrl,
    required this.createdAt,
    this.status = SendStatus.sent,
  });

  final String id;
  final String conversationId;
  final String senderId;
  final MessageKind kind;
  final String body;
  final String? attachmentUrl;
  final DateTime createdAt;
  final SendStatus status;

  bool get isMine => senderId == currentUserId;
  bool get isSystem => kind == MessageKind.system;

  ChatMessage copyWith({String? id, SendStatus? status, DateTime? createdAt}) =>
      ChatMessage(
        id: id ?? this.id,
        conversationId: conversationId,
        senderId: senderId,
        kind: kind,
        body: body,
        attachmentUrl: attachmentUrl,
        createdAt: createdAt ?? this.createdAt,
        status: status ?? this.status,
      );

  factory ChatMessage.fromJson(Map<String, dynamic> j) => ChatMessage(
        id: j['id'].toString(),
        conversationId: (j['conversation_id'] ?? '').toString(),
        senderId: (j['sender_id'] ?? '').toString(),
        kind: _kindFrom(j['kind']?.toString()),
        body: (j['body'] ?? j['text'] ?? '').toString(),
        attachmentUrl: j['attachment_url']?.toString(),
        createdAt: _date(j['created_at']),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'conversation_id': conversationId,
        'sender_id': senderId,
        'kind': kind.name,
        'body': body,
        if (attachmentUrl != null) 'attachment_url': attachmentUrl,
        'created_at': createdAt.toUtc().toIso8601String(),
      };
}
