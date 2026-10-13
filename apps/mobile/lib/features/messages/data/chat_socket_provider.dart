import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/features/messages/data/chat_channel_io.dart'
    if (dart.library.html) 'package:factory_finder/features/messages/data/chat_channel_stub.dart';
import 'package:factory_finder/features/messages/data/chat_socket.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// One socket per open chat; mock mode never connects.
final chatSocketProvider = Provider.autoDispose.family<ChatSocket, String>((ref, id) {
  final api = ref.watch(apiClientProvider);
  if (api.isMock) return MockChatSocket();
  final socket = LiveChatSocket(
    baseUrl: api.baseUrl,
    conversationId: id,
    accessToken: () => api.tokens.accessToken,
    refreshSession: api.refreshSession,
    connector: connectChatChannel,
    myUserId: ref.read(authProvider)?.id,
  );
  ref.onDispose(() {
    socket.close();
  });
  return socket;
});
