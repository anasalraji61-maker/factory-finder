import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

class NewConversationScreen extends ConsumerStatefulWidget {
  const NewConversationScreen({super.key, this.supplierId, this.listingId});
  final String? supplierId;
  final String? listingId;

  @override
  ConsumerState<NewConversationScreen> createState() => _NewConversationScreenState();
}

class _NewConversationScreenState extends ConsumerState<NewConversationScreen> {
  final TextEditingController _text = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    final supplier = widget.supplierId;
    if (supplier == null || supplier.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final conv = await ref.read(messagingRepositoryProvider).createConversation(
            supplierId: supplier,
            listingId: widget.listingId,
            firstMessage: _text.text,
          );
      ref.invalidate(conversationsProvider);
      if (!mounted) return;
      context.pushReplacement('/chat/${conv.id}');
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final supplier = widget.supplierId;
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('messages.new.title'))),
      body: (supplier == null || supplier.isEmpty)
          ? EmptyState(
              icon: Icons.person_search_outlined,
              title: context.tr('messages.new.no_supplier'),
            )
          : ListView(
              padding: const EdgeInsets.all(AppSpacing.lg),
              children: [
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(context.tr('messages.new.supplier'),
                          style: theme.textTheme.bodySmall
                              ?.copyWith(color: AppColors.textSecondary)),
                      Text(supplier, style: theme.textTheme.titleMedium),
                      if (widget.listingId != null) ...[
                        const SizedBox(height: AppSpacing.md),
                        Text(context.tr('messages.new.listing'),
                            style: theme.textTheme.bodySmall
                                ?.copyWith(color: AppColors.textSecondary)),
                        Text(widget.listingId!, style: theme.textTheme.titleMedium),
                      ],
                    ],
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                TextField(
                  controller: _text,
                  minLines: 3,
                  maxLines: 6,
                  decoration: InputDecoration(
                    labelText: context.tr('messages.new.first'),
                    hintText: context.tr('messages.new.default_text'),
                  ),
                ),
                if (_error != null) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Text(_error!, style: const TextStyle(color: AppColors.danger)),
                ],
                const SizedBox(height: AppSpacing.lg),
                PrimaryButton(
                  label: context.tr('messages.new.start'),
                  icon: Icons.chat_bubble_outline,
                  loading: _busy,
                  onPressed: _start,
                ),
              ],
            ),
    );
  }
}
