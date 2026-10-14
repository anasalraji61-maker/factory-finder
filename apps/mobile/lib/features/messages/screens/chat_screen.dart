import 'dart:async';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/messages/data/chat_logic.dart';
import 'package:factory_finder/features/messages/data/chat_socket.dart';
import 'package:factory_finder/features/messages/data/chat_socket_provider.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:factory_finder/features/messages/screens/conversations_screen.dart';
import 'package:factory_finder/features/my_products/media/image_pick_service.dart';
import 'package:factory_finder/features/my_products/media/media_logic.dart';
import 'package:factory_finder/features/my_products/media/media_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key, required this.conversationId});
  final String conversationId;

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _PendingUpload {
  _PendingUpload(this.id);
  final int id;
  double progress = 0;
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _input = TextEditingController();
  final List<MessageAttachment> _attached = <MessageAttachment>[];
  final List<_PendingUpload> _uploads = <_PendingUpload>[];
  int _uploadSeq = 0;
  List<ChatMessage> _messages = const [];
  Conversation? _conversation;
  bool _loading = true;
  Object? _error;
  Timer? _poll;
  int _seq = 0;
  ProviderSubscription<ChatSocket>? _keepAlive;
  StreamSubscription<ChatMessage>? _wsMsgs;
  StreamSubscription<ChatSocketStatus>? _wsStatus;
  ChatSocketStatus _wsState = ChatSocketStatus.idle;

  MessagingRepository get _repo => ref.read(messagingRepositoryProvider);

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 4), (_) => _refresh());
    // Keep the autoDispose provider alive while this screen is open.
    _keepAlive = ref.listenManual(chatSocketProvider(widget.conversationId), (_, __) {});
    final socket = _keepAlive!.read();
    _wsMsgs = socket.messages.listen((m) {
      if (!mounted) return;
      setState(() => _messages = appendIncoming(_messages, m));
    });
    _wsStatus = socket.statuses.listen((s) {
      if (!mounted) return;
      setState(() => _wsState = s);
    });
    _wsState = socket.status;
    socket.connect();
  }

  @override
  void dispose() {
    _poll?.cancel();
    _wsMsgs?.cancel();
    _wsStatus?.cancel();
    _keepAlive?.close();
    _input.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final convs = await _repo.conversations();
      for (final c in convs) {
        if (c.id == widget.conversationId) _conversation = c;
      }
      final msgs = await _repo.messages(widget.conversationId);
      await _repo.markRead(widget.conversationId);
      if (!mounted) return;
      ref.invalidate(conversationsProvider);
      setState(() {
        _messages = mergeServer(_messages, msgs);
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e;
      });
    }
  }

  Future<void> _refresh() async {
    if (!mounted || _loading) return;
    try {
      final msgs = await _repo.messages(widget.conversationId);
      if (!mounted) return;
      setState(() => _messages = mergeServer(_messages, msgs));
    } catch (_) {
      // Polling failures are silent; the next tick retries.
    }
  }

  void _snack(String text) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    messenger.showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _send(
    String text, {
    String? retryId,
    List<MessageAttachment> attachments = const <MessageAttachment>[],
  }) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty && attachments.isEmpty) return;
    final localId = retryId ?? 'local_${++_seq}';
    if (retryId == null) {
      final pending = optimisticMessage(
        conversationId: widget.conversationId,
        text: trimmed,
        now: DateTime.now(),
        seq: _seq,
        attachments: attachments,
      );
      setState(() {
        _messages = [..._messages, pending];
        _attached.clear();
      });
      _input.clear();
    } else {
      setState(() {
        _messages = [
          for (final m in _messages)
            if (m.id == retryId) m.copyWith(status: SendStatus.sending) else m,
        ];
      });
    }
    try {
      final sent = await _repo.send(
        widget.conversationId,
        trimmed,
        attachments: attachments,
      );
      if (!mounted) return;
      setState(() => _messages = confirmSent(_messages, localId, sent));
      ref.invalidate(conversationsProvider);
    } catch (e) {
      if (!mounted) return;
      setState(() => _messages = markFailed(_messages, localId));
      final key = sendErrorKey(e);
      if (key != null) _snack(context.tr(key));
    }
  }

  void _submit() {
    if (_uploads.isNotEmpty) {
      _snack(context.tr('messages.attach.wait'));
      return;
    }
    _send(_input.text, attachments: List<MessageAttachment>.of(_attached));
  }

  Future<void> _chooseSource() async {
    if (_attached.length + _uploads.length >= kMaxChatAttachments) {
      _snack(context.tr('messages.attach.limit'));
      return;
    }
    final camera = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              key: const ValueKey('chat-attach-gallery'),
              leading: const Icon(Icons.photo_library_outlined),
              title: Text(ctx.tr('messages.attach.gallery')),
              onTap: () => Navigator.of(ctx).pop(false),
            ),
            ListTile(
              key: const ValueKey('chat-attach-camera'),
              leading: const Icon(Icons.photo_camera_outlined),
              title: Text(ctx.tr('messages.attach.camera')),
              onTap: () => Navigator.of(ctx).pop(true),
            ),
          ],
        ),
      ),
    );
    if (camera == null || !mounted) return;
    await _pickAndUpload(camera);
  }

  Future<void> _pickAndUpload(bool camera) async {
    final picker = ref.read(imagePickServiceProvider);
    PickedImage? picked;
    try {
      picked = camera ? await picker.pickFromCamera() : await picker.pickFromGallery();
    } catch (_) {
      if (mounted) _snack(context.tr('myp.media.err.generic'));
      return;
    }
    if (picked == null || !mounted) return;
    final img = picked;
    final problem = checkImageFile(bytes: img.bytes.length, mime: img.mime);
    if (problem != null) {
      _snack(context.tr(problem));
      return;
    }
    if (_attached.length + _uploads.length >= kMaxChatAttachments) {
      _snack(context.tr('messages.attach.limit'));
      return;
    }
    final slot = _PendingUpload(++_uploadSeq);
    setState(() => _uploads.add(slot));
    try {
      final up = await ref.read(mediaRepositoryProvider).uploadImage(
        img,
        kind: 'attachment',
        onProgress: (p) {
          if (mounted && _uploads.contains(slot)) setState(() => slot.progress = p);
        },
      );
      if (!mounted) return;
      setState(() {
        _uploads.remove(slot);
        if (_attached.length < kMaxChatAttachments) {
          _attached.add(MessageAttachment(
            url: up.url,
            size: up.bytes ?? img.bytes.length,
            name: img.filename,
          ));
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _uploads.remove(slot));
      _snack(context.tr(mediaErrorKey(e)));
    }
  }

  void _openImage(String url) {
    showDialog<void>(
      context: context,
      builder: (ctx) => Dialog(
        insetPadding: const EdgeInsets.all(AppSpacing.md),
        child: Stack(
          children: [
            ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.of(ctx).size.height * 0.7,
              ),
              child: InteractiveViewer(
                child: AppNetworkImage(url: url, width: double.infinity, fit: BoxFit.contain),
              ),
            ),
            PositionedDirectional(
              top: 0,
              end: 0,
              child: IconButton(
                key: const ValueKey('chat-image-close'),
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.of(ctx).pop(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final conv = _conversation;
    final items = buildChatItems(_messages).reversed.toList();
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Row(
          children: [
            ConversationAvatar(title: conv?.title ?? '', radius: 18),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(conv?.title ?? '', maxLines: 1, overflow: TextOverflow.ellipsis),
                  if (conv?.context != null)
                    Text(
                      '${context.tr(contextLabelKey(conv!.context!.type))}'
                      '${conv.context!.title == null ? '' : ' · ${conv.context!.title}'}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context)
                          .textTheme
                          .bodySmall
                          ?.copyWith(color: AppColors.textSecondary),
                    ),
                ],
              ),
            ),
          ],
        ),
        actions: [_statusChip(context)],
      ),
      body: Column(
        children: [
          Expanded(child: _body(context, items)),
          _composer(context),
        ],
      ),
    );
  }

  Widget _statusChip(BuildContext context) {
    final String key;
    final Color color;
    switch (_wsState) {
      case ChatSocketStatus.idle:
        return const SizedBox.shrink();
      case ChatSocketStatus.connected:
        key = 'messages.conn.live';
        color = Colors.green;
        break;
      case ChatSocketStatus.connecting:
        key = 'messages.conn.connecting';
        color = Colors.orange;
        break;
      case ChatSocketStatus.reconnecting:
        key = 'messages.conn.reconnecting';
        color = Colors.orange;
        break;
      case ChatSocketStatus.failed:
        key = 'messages.conn.failed';
        color = Colors.grey;
        break;
    }
    return Padding(
      padding: const EdgeInsetsDirectional.only(end: AppSpacing.md),
      child: Center(
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
            ),
            const SizedBox(width: 4),
            Text(context.tr(key), style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }

  Widget _body(BuildContext context, List<ChatItem> items) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null && _messages.isEmpty) {
      return ErrorState(message: _error.toString(), onRetry: _load);
    }
    if (items.isEmpty) {
      return EmptyState(
        icon: Icons.waving_hand_outlined,
        title: context.tr('messages.chat_empty'),
      );
    }
    return ListView.builder(
      reverse: true,
      padding: const EdgeInsets.all(AppSpacing.md),
      itemCount: items.length,
      itemBuilder: (context, i) {
        final item = items[i];
        if (item.day != null) return _DaySeparator(day: item.day!);
        final m = item.message!;
        return _Bubble(
          message: m,
          baseUrl: ref.read(apiClientProvider).baseUrl,
          onOpenImage: _openImage,
          onRetry: () => _send(m.body, retryId: m.id, attachments: m.attachments),
        );
      },
    );
  }

  Widget _attachStrip(BuildContext context) {
    final base = ref.read(apiClientProvider).baseUrl;
    return SizedBox(
      key: const ValueKey('chat-attach-strip'),
      height: 72,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.only(bottom: AppSpacing.sm),
        children: [
          for (var i = 0; i < _attached.length; i++)
            Padding(
              padding: const EdgeInsetsDirectional.only(end: AppSpacing.sm),
              child: SizedBox(
                key: ValueKey('chat-attach-thumb-$i'),
                width: 64,
                height: 64,
                child: Stack(
                  children: [
                    AppNetworkImage(
                      url: mediaThumbUrl(base, _attached[i].url),
                      width: 64,
                      height: 64,
                      borderRadius: BorderRadius.circular(AppRadius.sm),
                    ),
                    PositionedDirectional(
                      top: 0,
                      end: 0,
                      child: InkWell(
                        key: ValueKey('chat-attach-remove-$i'),
                        onTap: () => setState(() => _attached.removeAt(i)),
                        child: Tooltip(
                          message: context.tr('messages.attach.remove'),
                          child: Container(
                            padding: const EdgeInsets.all(3),
                            decoration: const BoxDecoration(
                              color: Colors.black54,
                              shape: BoxShape.circle,
                            ),
                            child: const Icon(Icons.close, size: 14, color: Colors.white),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          for (final u in _uploads)
            Padding(
              padding: const EdgeInsetsDirectional.only(end: AppSpacing.sm),
              child: Container(
                key: ValueKey('chat-attach-uploading-${u.id}'),
                width: 64,
                height: 64,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: AppColors.border.withOpacity(0.6),
                  borderRadius: BorderRadius.circular(AppRadius.sm),
                ),
                child: const SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _composer(BuildContext context) {
    return Material(
      color: Theme.of(context).colorScheme.surface,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.sm, AppSpacing.sm, AppSpacing.sm, AppSpacing.sm),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_attached.isNotEmpty || _uploads.isNotEmpty) _attachStrip(context),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  IconButton(
                    key: const ValueKey('chat-attach'),
                    tooltip: context.tr('messages.attach_images'),
                    icon: const Icon(Icons.attach_file),
                    onPressed: _chooseSource,
                  ),
                  Expanded(
                    child: TextField(
                      controller: _input,
                      minLines: 1,
                      maxLines: 5,
                      textInputAction: TextInputAction.newline,
                      decoration: InputDecoration(
                        hintText: context.tr('messages.composer_hint'),
                        isDense: true,
                      ),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  IconButton.filled(
                    key: const ValueKey('chat-send'),
                    tooltip: context.tr('messages.send'),
                    icon: const Icon(Icons.send_rounded),
                    onPressed: _submit,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DaySeparator extends StatelessWidget {
  const _DaySeparator({required this.day});
  final DateTime day;

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final String label;
    if (isSameDay(day, now)) {
      label = context.tr('messages.today');
    } else if (isSameDay(day, now.subtract(const Duration(days: 1)))) {
      label = context.tr('messages.yesterday');
    } else {
      label = ymd(day);
    }
    return Center(
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        decoration: BoxDecoration(
          color: AppColors.border.withOpacity(0.7),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(
          label,
          style: Theme.of(context)
              .textTheme
              .bodySmall
              ?.copyWith(color: AppColors.textSecondary),
        ),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({
    required this.message,
    required this.baseUrl,
    required this.onOpenImage,
    required this.onRetry,
  });
  final ChatMessage message;
  final String baseUrl;
  final void Function(String url) onOpenImage;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (message.isSystem) {
      return Center(
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 6),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: AppColors.accent.withOpacity(0.12),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(
            message.body,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
          ),
        ),
      );
    }
    final mine = message.isMine;
    final failed = message.status == SendStatus.failed;
    final sending = message.status == SendStatus.sending;
    final bg = mine ? AppColors.primary : theme.colorScheme.surfaceContainerHighest;
    final fg = mine ? Colors.white : theme.colorScheme.onSurface;
    final radius = BorderRadiusDirectional.only(
      topStart: const Radius.circular(16),
      topEnd: const Radius.circular(16),
      bottomStart: Radius.circular(mine ? 16 : 4),
      bottomEnd: Radius.circular(mine ? 4 : 16),
    );
    return Align(
      alignment: mine ? AlignmentDirectional.centerEnd : AlignmentDirectional.centerStart,
      child: GestureDetector(
        onTap: failed ? onRetry : null,
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 3),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
          decoration: BoxDecoration(color: bg, borderRadius: radius),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (message.attachments.isNotEmpty) _attachments(context, fg),
              if (message.body.isNotEmpty)
                Padding(
                  padding: EdgeInsets.only(top: message.attachments.isEmpty ? 0 : 6),
                  child: Text(message.body, style: theme.textTheme.bodyMedium?.copyWith(color: fg)),
                ),
              const SizedBox(height: 2),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (failed)
                    Flexible(
                      child: Text(
                        context.tr('messages.failed'),
                        style: const TextStyle(color: Color(0xFFFFB4B4), fontSize: 11),
                      ),
                    )
                  else
                    Text(
                      hhmm(message.createdAt),
                      style: TextStyle(color: fg.withOpacity(0.7), fontSize: 11),
                    ),
                  if (sending) ...[
                    const SizedBox(width: 4),
                    Icon(Icons.schedule, size: 12, color: fg.withOpacity(0.7)),
                  ],
                  if (failed) ...[
                    const SizedBox(width: 4),
                    const Icon(Icons.error_outline, size: 12, color: Color(0xFFFFB4B4)),
                  ],
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _attachments(BuildContext context, Color fg) {
    final images = [for (final a in message.attachments) if (a.isImage) a];
    final docs = [for (final a in message.attachments) if (!a.isImage) a];
    final single = images.length == 1;
    final side = single ? 180.0 : 88.0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (images.isNotEmpty)
          Wrap(
            spacing: 4,
            runSpacing: 4,
            children: [
              for (var i = 0; i < images.length; i++)
                GestureDetector(
                  key: ValueKey('chat-img-${message.id}-$i'),
                  onTap: () => onOpenImage(resolveMediaUrl(baseUrl, images[i].url)),
                  child: AppNetworkImage(
                    url: mediaThumbUrl(baseUrl, images[i].url, width: single ? 400 : 200),
                    width: side,
                    height: side,
                    borderRadius: BorderRadius.circular(AppRadius.sm),
                  ),
                ),
            ],
          ),
        for (final d in docs)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 200),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.insert_drive_file_outlined, size: 18, color: fg),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(
                      d.name ?? context.tr('messages.attach.document'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: fg, decoration: TextDecoration.underline),
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
