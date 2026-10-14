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

/// Max attachments per message (contract `maxItems`, config-limited server side).
const int kMaxChatAttachments = 5;

enum AttachmentKind { image, document }

/// `MediaAttachment` of the messaging contract: a reference to a media file.
class MessageAttachment {
  const MessageAttachment({
    required this.url,
    this.kind = AttachmentKind.image,
    this.size,
    this.name,
  });

  /// May be server-relative (`/v1/media/files/<id>.<ext>`).
  final String url;
  final AttachmentKind kind;
  final int? size;
  final String? name;

  bool get isImage => kind == AttachmentKind.image;

  /// Tolerant: returns null when there is no usable url.
  static MessageAttachment? tryParse(Object? json) {
    if (json is! Map) return null;
    final url = (json['url'] ?? '').toString();
    if (url.isEmpty) return null;
    final size = json['size'];
    final name = json['name'];
    return MessageAttachment(
      url: url,
      kind: json['kind'] == 'document' ? AttachmentKind.document : AttachmentKind.image,
      size: size is num ? size.toInt() : null,
      name: name is String && name.isNotEmpty ? name : null,
    );
  }

  Map<String, dynamic> toJson() => {
        'url': url,
        'kind': kind.name,
        if (size != null) 'size': size,
        if (name != null) 'name': name,
      };
}

List<MessageAttachment> parseAttachments(Object? raw) {
  if (raw is! List) return const <MessageAttachment>[];
  return [
    for (final e in raw)
      if (MessageAttachment.tryParse(e) case final a?) a,
  ];
}

class ConversationContext {
  const ConversationContext({required this.type, required this.id, this.title});

  /// 'listing' | 'request' | 'deal'
  final String type;
  final String id;
  final String? title;

  factory ConversationContext.fromJson(Map<String, dynamic> j) => ConversationContext(
        type: (j['type'] ?? j['kind'] ?? 'listing').toString(),
        id: (j['id'] ?? j['ref_id'] ?? '').toString(),
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
    this.lastAttachments = const <MessageAttachment>[],
    required this.lastAt,
    this.unread = 0,
  });

  final String id;
  final String title;
  final String participantId;
  final String? avatarUrl;
  final ConversationContext? context;
  final String lastMessage;

  /// Attachments of the last message (when the server/mock provides them).
  final List<MessageAttachment> lastAttachments;
  final DateTime lastAt;
  final int unread;

  Conversation copyWith({
    String? lastMessage,
    List<MessageAttachment>? lastAttachments,
    DateTime? lastAt,
    int? unread,
  }) =>
      Conversation(
        id: id,
        title: title,
        participantId: participantId,
        avatarUrl: avatarUrl,
        context: context,
        lastMessage: lastMessage ?? this.lastMessage,
        lastAttachments: lastAttachments ?? this.lastAttachments,
        lastAt: lastAt ?? this.lastAt,
        unread: unread ?? this.unread,
      );

  /// [myUserId] (live mode) is used to pick the *other* participant of the
  /// contract's `participants: [{user_id, role}]` list.
  factory Conversation.fromJson(Map<String, dynamic> j, {String? myUserId}) {
    final participant = j['participant'];
    final participants = j['participants'];
    String otherId = '';
    if (participant is Map) {
      otherId = (participant['id'] ?? '').toString();
    } else if (participants is List) {
      for (final p in participants) {
        if (p is Map) {
          final uid = (p['user_id'] ?? '').toString();
          if (uid.isNotEmpty && uid != myUserId) {
            otherId = uid;
            break;
          }
        }
      }
    } else {
      otherId = (j['participant_id'] ?? '').toString();
    }
    final last = j['last_message'];
    final ctx = j['context'];
    final updated = _date(
      j['updated_at'] ??
          (last is Map ? last['created_at'] : null) ??
          j['created_at'],
    );
    final lastText =
        last is Map ? (last['body'] ?? last['preview']) : last;
    final ctxTitle = ctx is Map ? ctx['title'] : null;
    final title = (j['title'] ??
            (participant is Map ? participant['name'] : null) ??
            ctxTitle ??
            j['supplier_name'] ??
            otherId)
        .toString();
    return Conversation(
      id: j['id'].toString(),
      title: title,
      participantId: otherId,
      avatarUrl: participant is Map ? participant['avatar_url']?.toString() : null,
      context: ctx is Map ? ConversationContext.fromJson(Map<String, dynamic>.from(ctx)) : null,
      lastMessage: (lastText ?? '').toString(),
      lastAttachments: parseAttachments(last is Map ? last['attachments'] : null),
      lastAt: updated,
      unread: (j['unread_count'] as num?)?.toInt() ?? 0,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'participant': {'id': participantId, 'name': title, 'avatar_url': avatarUrl},
        if (context != null) 'context': context!.toJson(),
        'last_message': {
          'body': lastMessage,
          if (lastAttachments.isNotEmpty)
            'attachments': [for (final a in lastAttachments) a.toJson()],
          'created_at': lastAt.toUtc().toIso8601String(),
        },
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
    this.attachments = const <MessageAttachment>[],
    required this.createdAt,
    this.status = SendStatus.sent,
  });

  final String id;
  final String conversationId;
  final String senderId;
  final MessageKind kind;
  final String body;
  final String? attachmentUrl;

  /// Media attachments (contract `attachments[]`).
  final List<MessageAttachment> attachments;
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
        attachments: attachments,
        createdAt: createdAt ?? this.createdAt,
        status: status ?? this.status,
      );

  /// Accepts both the mock shape (`kind`, `body`) and the messaging contract
  /// (`type`, `text`, `attachment.url`). With [myUserId], messages sent by the
  /// signed-in user get [currentUserId] as sender so `isMine` works.
  factory ChatMessage.fromJson(Map<String, dynamic> j, {String? myUserId}) {
    final att = j['attachment'];
    final sender = (j['sender_id'] ?? '').toString();
    return ChatMessage(
      id: j['id'].toString(),
      conversationId: (j['conversation_id'] ?? '').toString(),
      senderId: (myUserId != null && sender == myUserId) ? currentUserId : sender,
      kind: _kindFrom((j['type'] ?? j['kind'])?.toString()),
      body: (j['body'] ?? j['text'] ?? '').toString(),
      attachmentUrl: (att is Map ? att['url'] : j['attachment_url'])?.toString(),
      attachments: parseAttachments(j['attachments']),
      createdAt: _date(j['created_at']),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'conversation_id': conversationId,
        'sender_id': senderId,
        'kind': kind.name,
        'body': body,
        if (attachmentUrl != null) 'attachment_url': attachmentUrl,
        if (attachments.isNotEmpty)
          'attachments': [for (final a in attachments) a.toJson()],
        'created_at': createdAt.toUtc().toIso8601String(),
      };
}
