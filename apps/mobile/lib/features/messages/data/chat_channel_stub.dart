import 'package:factory_finder/features/messages/data/chat_socket.dart';

/// Web builds: no dart:io; the screen falls back to REST polling only.
Future<ChatChannel> connectChatChannel(Uri uri) =>
    Future<ChatChannel>.error(UnsupportedError('WebSocket unavailable'));
