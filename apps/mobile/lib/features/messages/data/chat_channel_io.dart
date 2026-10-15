import 'dart:io';

import 'package:factory_finder/features/messages/data/chat_socket.dart';

class _IoChannel implements ChatChannel {
  _IoChannel(this._ws);
  final WebSocket _ws;

  @override
  Stream<dynamic> get incoming => _ws;
  @override
  void add(String data) => _ws.add(data);
  @override
  int? get closeCode => _ws.closeCode;
  @override
  Future<void> close() => _ws.close();
}

Future<ChatChannel> connectChatChannel(Uri uri) async {
  final ws = await WebSocket.connect(uri.toString()).timeout(const Duration(seconds: 10));
  // Detect half-open connections (NAT idle drop, airplane toggle) so the
  // reconnect logic in LiveChatSocket actually fires.
  ws.pingInterval = const Duration(seconds: 25);
  return _IoChannel(ws);
}
