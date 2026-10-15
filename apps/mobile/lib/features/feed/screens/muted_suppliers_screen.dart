import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/feed/feed_controller.dart';
import 'package:factory_finder/features/feed/feed_repository.dart';
import 'package:factory_finder/features/feed/widgets/post_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Suppliers the viewer muted, each with an Unmute button.
class MutedSuppliersScreen extends ConsumerStatefulWidget {
  const MutedSuppliersScreen({super.key});

  @override
  ConsumerState<MutedSuppliersScreen> createState() => _MutedSuppliersScreenState();
}

class _MutedSuppliersScreenState extends ConsumerState<MutedSuppliersScreen> {
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final ids = await fetchAllMutes(ref.read(feedRepositoryProvider));
      if (!mounted) return;
      // Keep optimistic mutes that the server list may not include yet.
      final notifier = ref.read(mutedSuppliersProvider.notifier);
      notifier.state = <String>{...ids, ...notifier.state};
      setState(() => _loading = false);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final muted = ref.watch(mutedSuppliersProvider).toList();
    final Widget body;
    if (muted.isEmpty && _loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (muted.isEmpty && _error != null) {
      body = ErrorState(error: _error, onRetry: _refresh);
    } else if (muted.isEmpty) {
      body = EmptyState(
        icon: Icons.volume_off_outlined,
        title: context.tr('feed.muted_empty'),
        message: context.tr('feed.muted_empty_hint'),
      );
    } else {
      body = ListView.separated(
        key: const ValueKey<String>('muted-list'),
        itemCount: muted.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (_, i) => _MutedTile(supplierId: muted[i]),
      );
    }
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('feed.muted_title'))),
      body: body,
    );
  }
}

class _MutedTile extends ConsumerWidget {
  const _MutedTile({required this.supplierId});

  final String supplierId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final name = ref
        .watch(supplierProvider(supplierId))
        .maybeWhen(data: (s) => s.name, orElse: () => supplierId);
    return ListTile(
      key: ValueKey<String>('muted-$supplierId'),
      leading: const Icon(Icons.volume_off_outlined),
      title: Text(name, maxLines: 2, overflow: TextOverflow.ellipsis),
      trailing: OutlinedButton(
        key: ValueKey<String>('unmute-$supplierId'),
        style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
        onPressed: () => toggleMuteFlow(context, ref, supplierId),
        child: Text(context.tr('feed.unmute_short')),
      ),
    );
  }
}
