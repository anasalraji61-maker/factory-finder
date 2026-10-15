import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/feed/feed_controller.dart';
import 'package:factory_finder/features/feed/feed_logic.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:factory_finder/features/feed/widgets/feed_common.dart';
import 'package:factory_finder/features/feed/widgets/post_card.dart';
import 'package:factory_finder/features/feed/widgets/report_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

class PostDetailScreen extends ConsumerStatefulWidget {
  const PostDetailScreen({super.key, required this.postId});

  final String postId;

  @override
  ConsumerState<PostDetailScreen> createState() => _PostDetailScreenState();
}

class _PostDetailScreenState extends ConsumerState<PostDetailScreen> {
  final TextEditingController _input = TextEditingController();
  String? _inputError;
  bool _sending = false;

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (_sending) return;
    final problem = validateCommentBody(_input.text);
    if (problem != null) {
      setState(() => _inputError = context.tr(problem));
      return;
    }
    setState(() {
      _inputError = null;
      _sending = true;
    });
    try {
      await ref.read(feedCommentsProvider(widget.postId).notifier).add(_input.text);
      if (!mounted) return;
      _input.clear();
      setState(() => _sending = false);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _sending = false;
        _inputError = feedErrorMessage(context, e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final id = widget.postId;
    final post = ref.watch(feedPostProvider(id));
    final fetch = ref.watch(feedPostDetailProvider(id));
    final me = ref.watch(authProvider);

    Widget body;
    if (post == null) {
      body = fetch.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorState(
          error: e,
          message: feedErrorMessage(context, e),
          onRetry: () => ref.invalidate(feedPostDetailProvider(id)),
        ),
        // The post was removed (e.g. a like answered 404) after it loaded.
        data: (_) => EmptyState(
          key: const ValueKey<String>('feed-detail-gone'),
          icon: Icons.visibility_off_outlined,
          title: context.tr('feed.err.not_found'),
        ),
      );
    } else {
      final comments = ref.watch(feedCommentsProvider(id));
      final ctrl = ref.read(feedCommentsProvider(id).notifier);
      final isPostOwner = me?.supplierId != null && me?.supplierId == post.supplierId;
      body = Column(
        children: [
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async {
                ref.invalidate(feedPostDetailProvider(id));
                await ctrl.refresh();
              },
              child: ListView(
                key: const ValueKey<String>('feed-detail-list'),
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(AppSpacing.lg),
                children: [
                  PostCard(postId: id, detail: true),
                  const SizedBox(height: AppSpacing.lg),
                  Text(
                    context.tr('feed.comments_title', {'n': '${post.commentCount}'}),
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  if (comments.loading)
                    const Padding(
                      padding: EdgeInsets.all(AppSpacing.lg),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else if (comments.error != null && comments.items.isEmpty)
                    ErrorState(
                      error: comments.error,
                      message: feedErrorMessage(context, comments.error!),
                      onRetry: ctrl.refresh,
                    )
                  else if (comments.items.isEmpty)
                    Padding(
                      padding: const EdgeInsets.all(AppSpacing.lg),
                      child: Text(
                        context.tr('feed.comments_empty'),
                        textAlign: TextAlign.center,
                        style: TextStyle(color: AppColors.secondaryOf(context)),
                      ),
                    )
                  else
                    for (final c in comments.items)
                      _CommentTile(
                        key: ValueKey<String>('feed-comment-${c.id}'),
                        comment: c,
                        mine: me != null && c.userId == me.id,
                        canDelete: (me != null && c.userId == me.id) || isPostOwner,
                        onDelete: () async {
                          try {
                            await ctrl.delete(c.id);
                          } catch (e) {
                            if (context.mounted) showFeedError(context, e);
                          }
                        },
                        onReport: () async {
                          final sent = await showFeedReportSheet(
                            context,
                            onSubmit: (r, d) =>
                                ref.read(feedActionsProvider).reportComment(c.id, r, d),
                          );
                          if (sent && context.mounted) {
                            showFeedSnack(context, context.tr('feed.report.done'));
                          }
                        },
                      ),
                  if (comments.hasMore && !comments.loading)
                    Padding(
                      padding: const EdgeInsets.only(top: AppSpacing.sm),
                      child: comments.loadingMore
                          ? const Center(child: CircularProgressIndicator())
                          : OutlinedButton(
                              key: const ValueKey<String>('feed-comments-more'),
                              onPressed: ctrl.loadMore,
                              child: Text(
                                comments.moreError != null
                                    ? context.tr('common.retry')
                                    : context.tr('feed.load_more'),
                              ),
                            ),
                    ),
                ],
              ),
            ),
          ),
          _CommentBar(
            signedIn: me != null,
            controller: _input,
            error: _inputError,
            sending: _sending,
            onSend: _send,
            onChanged: () {
              if (_inputError != null) setState(() => _inputError = null);
            },
          ),
        ],
      );
    }

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('feed.post'))),
      body: body,
    );
  }
}

class _CommentBar extends StatelessWidget {
  const _CommentBar({
    required this.signedIn,
    required this.controller,
    required this.error,
    required this.sending,
    required this.onSend,
    required this.onChanged,
  });

  final bool signedIn;
  final TextEditingController controller;
  final String? error;
  final bool sending;
  final VoidCallback onSend;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    return Material(
      elevation: 4,
      color: Theme.of(context).colorScheme.surface,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.sm,
            AppSpacing.sm,
            AppSpacing.sm,
          ),
          child: signedIn
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: TextField(
                        key: const ValueKey<String>('feed-comment-field'),
                        controller: controller,
                        enabled: !sending,
                        minLines: 1,
                        maxLines: 4,
                        maxLength: kCommentBodyMax,
                        onChanged: (_) => onChanged(),
                        textInputAction: TextInputAction.newline,
                        decoration: InputDecoration(
                          hintText: context.tr('feed.comment_hint'),
                          errorText: error,
                          errorMaxLines: 3,
                          counterText: '',
                        ),
                      ),
                    ),
                    const SizedBox(width: AppSpacing.xs),
                    IconButton(
                      key: const ValueKey<String>('feed-comment-send'),
                      tooltip: context.tr('feed.comment_send'),
                      style: IconButton.styleFrom(minimumSize: const Size(48, 48)),
                      onPressed: sending ? null : onSend,
                      icon: sending
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.send),
                    ),
                  ],
                )
              : Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: TextButton(
                    key: const ValueKey<String>('feed-comment-login'),
                    onPressed: () => context.push('/login'),
                    child: Text(context.tr('feed.login_to_comment')),
                  ),
                ),
        ),
      ),
    );
  }
}

class _CommentTile extends StatelessWidget {
  const _CommentTile({
    super.key,
    required this.comment,
    required this.mine,
    required this.canDelete,
    required this.onDelete,
    required this.onReport,
  });

  final FeedComment comment;
  final bool mine;
  final bool canDelete;
  final VoidCallback onDelete;
  final VoidCallback onReport;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final secondary = AppColors.secondaryOf(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SupplierAvatar(label: mine ? '★' : '•', radius: 16),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: AppSpacing.sm,
                  children: [
                    Text(
                      context.tr(mine ? 'feed.comment.you' : 'feed.comment.user'),
                      style: theme.textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w800),
                    ),
                    Text(
                      feedTimeLabel(context, comment.createdAt),
                      style: theme.textTheme.bodySmall?.copyWith(color: secondary),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(comment.body),
              ],
            ),
          ),
          PopupMenuButton<String>(
            key: ValueKey<String>('feed-comment-menu-${comment.id}'),
            tooltip: context.tr('feed.more'),
            onSelected: (v) {
              if (v == 'delete') onDelete();
              if (v == 'report') onReport();
            },
            itemBuilder: (_) => [
              if (canDelete)
                PopupMenuItem<String>(value: 'delete', child: Text(context.tr('feed.delete'))),
              if (!mine)
                PopupMenuItem<String>(
                  value: 'report',
                  child: Text(context.tr('feed.report.comment')),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
