import 'dart:async';
import 'dart:convert';

import 'package:factory_finder/features/messages/data/message_models.dart';

/// Connection state shown in the chat app bar.
enum ChatSocketStatus { idle, connecting, connected, reconnecting, failed }

/// Close codes (gateway README / messaging contract).
const int kCloseUnauthenticated = 4401;
const int kCloseForbidden = 4403;
const int kCloseNotFound = 4404;

bool isFatalCloseCode(int? code) => code == kCloseForbidden || code == kCloseNotFound;

/// Reconnect delay for the given zero-based [attempt]: 1,2,4,8,16,30,30...
Duration backoffDelay(int attempt) {
  final a = attempt < 0 ? 0 : attempt;
  if (a >= 5) return const Duration(seconds: 30);
  return Duration(seconds: 1 << a);
}

/// `http(s)://host[/prefix]` -> `ws(s)://host[/prefix]/v1/ws/conversations/{id}?token=...`
Uri chatSocketUri(String baseUrl, String conversationId, String token) {
  final base = Uri.parse(baseUrl);
  final scheme = base.scheme == 'https' || base.scheme == 'wss' ? 'wss' : 'ws';
  var prefix = base.path;
  while (prefix.endsWith('/')) {
    prefix = prefix.substring(0, prefix.length - 1);
  }
  return Uri(
    scheme: scheme,
    host: base.host,
    port: base.hasPort ? base.port : null,
    path: '$prefix/v1/ws/conversations/$conversationId',
    queryParameters: <String, String>{'token': token},
  );
}

/// Parses one server frame. Returns a message only for `message.created`
/// frames (for [conversationId] when given); everything else is ignored.
ChatMessage? parseMessageFrame(
  Object? raw, {
  String? myUserId,
  String? conversationId,
}) {
  try {
    final data = raw is String ? jsonDecode(raw) : raw;
    if (data is! Map || data['type'] != 'message.created') return null;
    final m = data['message'];
    if (m is! Map || m['id'] == null) return null;
    final msg = ChatMessage.fromJson(Map<String, dynamic>.from(m), myUserId: myUserId);
    if (conversationId != null &&
        msg.conversationId.isNotEmpty &&
        msg.conversationId != conversationId) {
      return null;
    }
    return msg;
  } catch (_) {
    return null;
  }
}

/// Appends [incoming] unless a message with the same id exists; keeps time order.
List<ChatMessage> appendIncoming(List<ChatMessage> list, ChatMessage incoming) {
  if (list.any((m) => m.id == incoming.id)) return list;
  final out = [...list, incoming];
  out.sort((a, b) => a.createdAt.compareTo(b.createdAt));
  return out;
}

/// Push-only realtime channel; REST stays the source of truth for sending.
abstract class ChatSocket {
  Stream<ChatMessage> get messages;
  Stream<ChatSocketStatus> get statuses;
  ChatSocketStatus get status;
  void connect();

  /// Sends a client frame (`{"type":"ping"}`, typing, read). No-op if offline.
  void send(Map<String, dynamic> frame);
  Future<void> close();
}

/// Never connects, never emits.
class MockChatSocket implements ChatSocket {
  @override
  Stream<ChatMessage> get messages => const Stream<ChatMessage>.empty();
  @override
  Stream<ChatSocketStatus> get statuses => const Stream<ChatSocketStatus>.empty();
  @override
  ChatSocketStatus get status => ChatSocketStatus.idle;
  @override
  void connect() {}
  @override
  void send(Map<String, dynamic> frame) {}
  @override
  Future<void> close() async {}
}

/// Minimal transport so the reconnect logic is testable without sockets.
abstract class ChatChannel {
  Stream<dynamic> get incoming;
  void add(String data);

  /// Valid once [incoming] is done.
  int? get closeCode;
  Future<void> close();
}

typedef ChatChannelConnector = Future<ChatChannel> Function(Uri uri);

class LiveChatSocket implements ChatSocket {
  LiveChatSocket({
    required this.baseUrl,
    required this.conversationId,
    required this.accessToken,
    required this.refreshSession,
    required this.connector,
    this.myUserId,
  });

  final String baseUrl;
  final String conversationId;
  final String? Function() accessToken;

  /// Refreshes tokens; true on success.
  final Future<bool> Function() refreshSession;
  final ChatChannelConnector connector;
  final String? myUserId;

  final StreamController<ChatMessage> _msgs = StreamController<ChatMessage>.broadcast();
  final StreamController<ChatSocketStatus> _stat =
      StreamController<ChatSocketStatus>.broadcast();
  ChatSocketStatus _status = ChatSocketStatus.idle;
  ChatChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  Timer? _timer;
  int _attempt = 0;
  bool _closed = false;
  bool _refreshUsed = false;

  @override
  Stream<ChatMessage> get messages => _msgs.stream;
  @override
  Stream<ChatSocketStatus> get statuses => _stat.stream;
  @override
  ChatSocketStatus get status => _status;

  void _set(ChatSocketStatus s) {
    if (_status == s || _stat.isClosed) return;
    _status = s;
    _stat.add(s);
  }

  @override
  void connect() {
    if (_closed || _channel != null) return;
    _open();
  }

  Future<void> _open() async {
    final token = accessToken();
    if (token == null || token.isEmpty) {
      _set(ChatSocketStatus.failed);
      return;
    }
    _set(_attempt == 0 ? ChatSocketStatus.connecting : ChatSocketStatus.reconnecting);
    ChatChannel ch;
    try {
      ch = await connector(chatSocketUri(baseUrl, conversationId, token));
    } catch (_) {
      _scheduleRetry();
      return;
    }
    if (_closed) {
      await ch.close();
      return;
    }
    _channel = ch;
    _attempt = 0;
    _refreshUsed = false;
    _set(ChatSocketStatus.connected);
    _sub = ch.incoming.listen(
      (raw) {
        final m = parseMessageFrame(raw, myUserId: myUserId, conversationId: conversationId);
        if (m != null && !_msgs.isClosed) _msgs.add(m);
      },
      onError: (Object _) {},
      onDone: () => _onDone(ch.closeCode),
      cancelOnError: false,
    );
  }

  Future<void> _onDone(int? code) async {
    _sub = null;
    _channel = null;
    if (_closed) return;
    if (isFatalCloseCode(code)) {
      _set(ChatSocketStatus.failed);
      return;
    }
    if (code == kCloseUnauthenticated) {
      if (_refreshUsed) {
        _set(ChatSocketStatus.failed);
        return;
      }
      _refreshUsed = true;
      _set(ChatSocketStatus.reconnecting);
      bool ok;
      try {
        ok = await refreshSession();
      } catch (_) {
        ok = false;
      }
      if (_closed) return;
      if (!ok) {
        _set(ChatSocketStatus.failed);
        return;
      }
      _open();
      return;
    }
    _scheduleRetry();
  }

  void _scheduleRetry() {
    if (_closed) return;
    _set(ChatSocketStatus.reconnecting);
    final d = backoffDelay(_attempt++);
    _timer?.cancel();
    _timer = Timer(d, () {
      if (!_closed) _open();
    });
  }

  @override
  void send(Map<String, dynamic> frame) {
    final ch = _channel;
    if (ch == null) return;
    try {
      ch.add(jsonEncode(frame));
    } catch (_) {}
  }

  @override
  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _timer?.cancel();
    await _sub?.cancel();
    final ch = _channel;
    _channel = null;
    try {
      await ch?.close();
    } catch (_) {}
    _set(ChatSocketStatus.idle);
    await _msgs.close();
    await _stat.close();
  }
}
