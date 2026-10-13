import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class MessagingRepository {
  Future<List<Conversation>> conversations();
  Future<List<ChatMessage>> messages(String conversationId);
  Future<ChatMessage> send(String conversationId, String text);
  Future<void> markRead(String conversationId);

  /// Returns an existing conversation for the same supplier+context or creates one.
  Future<Conversation> createConversation({
    required String supplierId,
    String? listingId,
    String? firstMessage,
  });
}

List<T> _items<T>(dynamic data, T Function(Map<String, dynamic>) parse) {
  final raw = data is Map ? (data['items'] ?? const []) : data;
  if (raw is! List) return <T>[];
  return [
    for (final e in raw)
      if (e is Map) parse(Map<String, dynamic>.from(e)),
  ];
}

/// REST implementation per ARCHITECTURE §4 (polling is the realtime fallback).
class LiveMessagingRepository implements MessagingRepository {
  LiveMessagingRepository(this._api);
  final ApiClient _api;

  @override
  Future<List<Conversation>> conversations() async {
    final data = await _api.get('/v1/conversations');
    final list = _items(data, Conversation.fromJson);
    list.sort((a, b) => b.lastAt.compareTo(a.lastAt));
    return list;
  }

  @override
  Future<List<ChatMessage>> messages(String id) async {
    final data = await _api.get('/v1/conversations/$id/messages');
    final list = _items(data, ChatMessage.fromJson);
    list.sort((a, b) => a.createdAt.compareTo(b.createdAt));
    return list;
  }

  @override
  Future<ChatMessage> send(String id, String text) async {
    final data = await _api.post('/v1/conversations/$id/messages',
        body: {'kind': 'text', 'body': text});
    return ChatMessage.fromJson(Map<String, dynamic>.from(data as Map));
  }

  @override
  Future<void> markRead(String id) async {
    await _api.post('/v1/conversations/$id/read');
  }

  @override
  Future<Conversation> createConversation({
    required String supplierId,
    String? listingId,
    String? firstMessage,
  }) async {
    final data = await _api.post('/v1/conversations', body: {
      'participant_id': supplierId,
      if (listingId != null) 'context': {'type': 'listing', 'id': listingId},
      if (firstMessage != null && firstMessage.trim().isNotEmpty)
        'initial_message': firstMessage.trim(),
    });
    return Conversation.fromJson(Map<String, dynamic>.from(data as Map));
  }
}

class _Seed {
  const _Seed(this.id, this.title, this.supplierId, this.ctxType, this.ctxId,
      this.ctxTitle, this.unread, this.lines);
  final String id;
  final String title;
  final String supplierId;
  final String? ctxType;
  final String? ctxId;
  final String? ctxTitle;
  final int unread;

  /// (fromMe, text, minutes ago); `system` lines use fromMe == null.
  final List<(bool?, String, int)> lines;
}

const List<_Seed> _seeds = [
  _Seed('cnv_001', 'شركة شنتشن للإلكترونيات', 'sup_001', 'listing', 'lst_001',
      'سماعات بلوتوث لاسلكية TWS', 2, [
    (null, 'تم فتح المحادثة بخصوص: سماعات بلوتوث لاسلكية TWS', 3000),
    (true, 'السلام عليكم، ما هو أقل كمية للطلب؟', 2990),
    (false, 'وعليكم السلام، الحد الأدنى 500 قطعة بسعر 5.5 دولار للقطعة FOB شنتشن.', 2950),
    (true, 'ممكن سعر أفضل لـ 2000 قطعة؟', 1500),
    (false, 'لـ 2000 قطعة نقدر نعطيك 4.9 دولار للقطعة.', 60),
    (false, 'وإذا تريد شعارك على العلبة نضيف 0.2 دولار.', 58),
  ]),
  _Seed('cnv_002', 'مصنع فوشان للأثاث', 'sup_005', 'listing', 'lst_005',
      'كرسي مكتب مريح', 0, [
    (true, 'هل الكرسي متوفر باللون الأسود؟', 1700),
    (false, 'نعم متوفر بالأسود والرمادي، التسليم خلال 15 يوم.', 1650),
    (true, 'تمام، أرسل لي كتالوج المواصفات.', 1640),
  ]),
  _Seed('cnv_003', 'طلب: 20 طن حبيبات HDPE', 'sup_010', 'request', 'req_003',
      'طلب شراء حبيبات HDPE', 1, [
    (null, 'تم إرسال عرض سعر على طلبك', 600),
    (false, 'عرضنا: 1115 دولار للطن CFR أم قصر، الشحن خلال 25 يوم.', 590),
    (true, 'هل السعر قابل للتفاوض عند ٤٠ طن؟', 400),
    (false, 'نعم، نعطيك 1090 دولار للطن عند ٤٠ طن.', 30),
  ]),
  _Seed('cnv_004', 'مجموعة تانغشان للصلب', 'sup_012', 'listing', 'lst_012',
      'لفائف فولاذ ملفوفة على الساخن', 0, [
    (true, 'أحتاج شهادة المطابقة ومصنع المنشأ.', 4400),
    (false, 'أرسلنا لك الشهادة ISO 9001 وتقرير الفحص SGS.', 4300),
    (true, 'شكراً، سأراجعها وأعود لك.', 4290),
  ]),
  _Seed('cnv_005', 'خطوط تعبئة فوشان', 'sup_017', 'listing', 'lst_017',
      'خط نفخ عبوات PET', 3, [
    (true, 'هل يمكن معاينة الخط قبل الشحن؟', 8000),
    (false, 'بالتأكيد، نرحب بزيارتكم أو نرسل فيديو تشغيل مباشر.', 7900),
    (false, 'المصنع يبعد ساعة عن مطار قوانغتشو.', 7890),
    (false, 'متى تفضل موعد الزيارة؟', 7880),
  ]),
  _Seed('cnv_006', 'يي وو للتجارة العامة', 'sup_009', 'listing', 'lst_009',
      'ساعة ذكية لتتبع اللياقة', 0, [
    (false, 'مرحباً، العينة جاهزة وسنرسلها اليوم عبر DHL.', 12000),
    (true, 'أرسل رقم التتبع عند الإرسال لو سمحت.', 11900),
    (null, 'تمت إضافة شحنة للتتبع', 11800),
  ]),
  _Seed('cnv_007', 'مصنع نينغبو للكرتون', 'sup_007', 'listing', 'lst_007',
      'كراتين شحن مموجة', 0, [
    (true, 'نريد كراتين بمقاس 40×30×30 سم، ٥٠٠٠ قطعة.', 20000),
    (false, 'السعر 0.42 دولار للقطعة EXW، ويمكن الطباعة بلونين.', 19900),
  ]),
  _Seed('cnv_008', 'بورصة قطن بورصة - تركيا', 'sup_015', 'listing', 'lst_015',
      'خيوط قطن ممشطة', 1, [
    (true, 'Merhaba، هل تشحنون إلى البصرة؟', 100000),
    (false, 'نعم، نشحن عبر ميناء مرسين ثم بالشاحنات إلى إبراهيم الخليل.', 99900),
    (false, 'مدة النقل التقديرية ١٠ أيام من المصنع إلى بغداد.', 99890),
  ]),
];

/// In-memory implementation used in mock mode and tests.
class MockMessagingRepository implements MessagingRepository {
  MockMessagingRepository({DateTime Function()? clock, bool autoReply = true})
      : _clock = clock ?? DateTime.now,
        _autoReply = autoReply {
    final now = _clock();
    for (final s in _seeds) {
      final msgs = <ChatMessage>[];
      for (var i = 0; i < s.lines.length; i++) {
        final l = s.lines[i];
        msgs.add(ChatMessage(
          id: '${s.id}_m$i',
          conversationId: s.id,
          senderId: l.$1 == null ? 'system' : (l.$1! ? currentUserId : s.supplierId),
          kind: l.$1 == null ? MessageKind.system : MessageKind.text,
          body: l.$2,
          createdAt: now.subtract(Duration(minutes: l.$3)),
        ));
      }
      _messages[s.id] = msgs;
      final lastText = msgs.lastWhere((m) => !m.isSystem, orElse: () => msgs.last);
      _convs[s.id] = Conversation(
        id: s.id,
        title: s.title,
        participantId: s.supplierId,
        context: s.ctxType == null
            ? null
            : ConversationContext(type: s.ctxType!, id: s.ctxId ?? '', title: s.ctxTitle),
        lastMessage: lastText.body,
        lastAt: lastText.createdAt,
        unread: s.unread,
      );
    }
  }

  final DateTime Function() _clock;
  final bool _autoReply;
  final Map<String, Conversation> _convs = {};
  final Map<String, List<ChatMessage>> _messages = {};
  int _seq = 0;

  @override
  Future<List<Conversation>> conversations() async {
    final list = _convs.values.toList()..sort((a, b) => b.lastAt.compareTo(a.lastAt));
    return list;
  }

  /// Delayed mock replies only become visible once their time has come.
  @override
  Future<List<ChatMessage>> messages(String id) async {
    final now = _clock();
    return [
      for (final m in _messages[id] ?? const <ChatMessage>[])
        if (!m.createdAt.isAfter(now)) m,
    ];
  }

  @override
  Future<ChatMessage> send(String id, String text) async {
    final conv = _convs[id];
    if (conv == null) {
      throw ApiException(status: 404, code: 'not_found', message: 'conversation not found');
    }
    final now = _clock();
    final msg = ChatMessage(
      id: 'srv_${++_seq}',
      conversationId: id,
      senderId: currentUserId,
      body: text.trim(),
      createdAt: now,
    );
    final list = _messages.putIfAbsent(id, () => []);
    list.add(msg);
    final last = conv.copyWith(lastMessage: msg.body, lastAt: now);
    if (_autoReply) {
      final at = now.add(const Duration(seconds: 3));
      list.add(ChatMessage(
        id: 'srv_${++_seq}',
        conversationId: id,
        senderId: conv.participantId,
        body: 'شكراً لرسالتك، سنرد عليك بالتفاصيل خلال ساعات قليلة.',
        createdAt: at,
      ));
    }
    _convs[id] = last;
    return msg;
  }

  @override
  Future<void> markRead(String id) async {
    final c = _convs[id];
    if (c != null) _convs[id] = c.copyWith(unread: 0);
  }

  @override
  Future<Conversation> createConversation({
    required String supplierId,
    String? listingId,
    String? firstMessage,
  }) async {
    for (final c in _convs.values) {
      if (c.participantId == supplierId &&
          (listingId == null || c.context?.id == listingId)) {
        if (firstMessage != null && firstMessage.trim().isNotEmpty) {
          await send(c.id, firstMessage);
        }
        return _convs[c.id]!;
      }
    }
    final id = 'cnv_new_${++_seq}';
    final now = _clock();
    _convs[id] = Conversation(
      id: id,
      title: 'مورّد $supplierId',
      participantId: supplierId,
      context: listingId == null
          ? null
          : ConversationContext(type: 'listing', id: listingId),
      lastAt: now,
    );
    _messages[id] = [];
    if (firstMessage != null && firstMessage.trim().isNotEmpty) {
      await send(id, firstMessage);
    }
    return _convs[id]!;
  }
}

final messagingRepositoryProvider = Provider<MessagingRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockMessagingRepository() : LiveMessagingRepository(api);
});

final conversationsProvider = FutureProvider.autoDispose<List<Conversation>>(
  (ref) => ref.watch(messagingRepositoryProvider).conversations(),
);
