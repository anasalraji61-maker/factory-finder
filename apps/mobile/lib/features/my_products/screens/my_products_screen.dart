import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/my_products/my_products_logic.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:factory_finder/features/my_products/my_products_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// True when the signed-in user may manage listings (verified supplier claim).
bool isVerifiedSupplier(Me? me) => me != null && me.supplierClaimStatus == 'verified';

/// Mock mode has no real claim to verify, so the screen is open there. Tests
/// override this to exercise the unverified-supplier card.
final myProductsBypassGateProvider = Provider<bool>(
  (ref) => ref.watch(apiClientProvider).isMock,
);

Color _statusColor(ListingStatus s) {
  switch (s) {
    case ListingStatus.draft:
      return AppColors.warning;
    case ListingStatus.published:
      return AppColors.success;
    case ListingStatus.archived:
      return AppColors.textSecondary;
  }
}

/// Shows a snackbar replacing any previous one.
void showMyProductsSnack(BuildContext context, String text) {
  final messenger = ScaffoldMessenger.of(context);
  messenger.clearSnackBars();
  messenger.showSnackBar(SnackBar(content: Text(text)));
}

Future<bool> confirmMyProductsAction(
  BuildContext context, {
  required String titleKey,
  required String messageKey,
  required String confirmKey,
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(ctx.tr(titleKey)),
      content: Text(ctx.tr(messageKey)),
      actions: [
        TextButton(
          key: const ValueKey('myp-confirm-cancel'),
          onPressed: () => Navigator.of(ctx).pop(false),
          child: Text(ctx.tr('myp.cancel')),
        ),
        TextButton(
          key: const ValueKey('myp-confirm-ok'),
          onPressed: () => Navigator.of(ctx).pop(true),
          child: Text(ctx.tr(confirmKey)),
        ),
      ],
    ),
  );
  return ok == true;
}

class MyProductsScreen extends ConsumerStatefulWidget {
  const MyProductsScreen({super.key});

  @override
  ConsumerState<MyProductsScreen> createState() => _MyProductsScreenState();
}

class _MyProductsScreenState extends ConsumerState<MyProductsScreen> {
  ListingStatus? _status;
  List<OwnedListing> _items = const <OwnedListing>[];
  int _page = 1;
  int _total = 0;
  bool _loading = true;
  bool _loadingMore = false;
  String? _errorKey;
  String? _busyId;
  int _req = 0;

  bool _isOpen() {
    final verified = isVerifiedSupplier(ref.read(authProvider));
    return verified || ref.read(myProductsBypassGateProvider);
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _isOpen()) _load();
    });
  }

  Future<void> _load({bool more = false}) async {
    final token = ++_req;
    final page = more ? _page + 1 : 1;
    setState(() {
      if (more) {
        _loadingMore = true;
      } else {
        _loading = _items.isEmpty;
        _errorKey = null;
      }
    });
    try {
      final res = await ref
          .read(myListingsRepositoryProvider)
          .list(status: _status, page: page, pageSize: 50);
      if (!mounted || token != _req) return;
      setState(() {
        _items = more ? <OwnedListing>[..._items, ...res.items] : res.items;
        _page = page;
        _total = res.total;
        _loading = false;
        _loadingMore = false;
        _errorKey = null;
      });
    } catch (e) {
      if (!mounted || token != _req) return;
      final key = myProductsErrorKey(e);
      setState(() {
        _loading = false;
        _loadingMore = false;
        if (!more) {
          _items = const <OwnedListing>[];
          _errorKey = key;
        }
      });
      if (more) showMyProductsSnack(context, context.tr(key));
    }
  }

  void _setStatus(ListingStatus? s) {
    if (s == _status) return;
    setState(() {
      _status = s;
      _items = const <OwnedListing>[];
      _loading = true;
    });
    _load();
  }

  Future<void> _openEditor(String? id) async {
    final changed = await context.push<bool>(id == null ? '/my-products/new' : '/my-products/$id');
    if (changed == true && mounted) _load();
  }

  Future<void> _runAction(
    OwnedListing l, {
    required String titleKey,
    required String messageKey,
    required String confirmKey,
    required String okKey,
    required Future<void> Function(MyListingsRepository repo) action,
  }) async {
    final sure = await confirmMyProductsAction(
      context,
      titleKey: titleKey,
      messageKey: messageKey,
      confirmKey: confirmKey,
    );
    if (!sure || !mounted) return;
    setState(() => _busyId = l.id);
    try {
      await action(ref.read(myListingsRepositoryProvider));
      if (!mounted) return;
      setState(() => _busyId = null);
      showMyProductsSnack(context, context.tr(okKey));
      _load();
    } catch (e) {
      if (!mounted) return;
      setState(() => _busyId = null);
      showMyProductsSnack(context, context.tr(myProductsErrorKey(e)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final me = ref.watch(authProvider);
    final open = isVerifiedSupplier(me) || ref.watch(myProductsBypassGateProvider);
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('myp.title'))),
      floatingActionButton: open
          ? FloatingActionButton.extended(
              key: const ValueKey('myp-add'),
              onPressed: () => _openEditor(null),
              icon: const Icon(Icons.add),
              label: Text(context.tr('myp.add')),
            )
          : null,
      body: open ? _buildList(context) : _buildGate(context, me),
    );
  }

  Widget _buildGate(BuildContext context, Me? me) {
    if (me == null) {
      return EmptyState(
        icon: Icons.lock_outline,
        title: context.tr('myp.signin'),
        action: PrimaryButton(
          label: context.tr('auth.login'),
          icon: Icons.login,
          onPressed: () => context.push('/login'),
        ),
      );
    }
    final pending = me.supplierClaimStatus == 'pending';
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: [
        AppCard(
          key: const ValueKey('myp-claim-card'),
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.storefront_outlined, color: AppColors.primary),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Text(
                      context.tr('myp.claim.title'),
                      style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.md),
              Text(context.tr('myp.claim.msg')),
              if (pending) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  context.tr('myp.claim.pending'),
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ],
              const SizedBox(height: AppSpacing.lg),
              PrimaryButton(
                label: context.tr('myp.claim.button'),
                icon: Icons.link,
                onPressed: () => context.push('/supplier-claim'),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildChips(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md, AppSpacing.lg, AppSpacing.sm),
      child: Row(
        children: [
          for (final s in kStatusFilters)
            Padding(
              padding: const EdgeInsetsDirectional.only(end: AppSpacing.sm),
              child: ChoiceChip(
                key: ValueKey('myp-filter-${s?.json ?? 'all'}'),
                label: Text(context.tr('myp.filter.${s?.json ?? 'all'}')),
                selected: _status == s,
                onSelected: (_) => _setStatus(s),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildList(BuildContext context) {
    final Widget content;
    if (_loading) {
      content = const LoadingList();
    } else if (_errorKey != null) {
      content = ErrorState(
        message: context.tr(_errorKey!),
        onRetry: () => _load(),
      );
    } else if (_items.isEmpty) {
      content = RefreshIndicator(
        onRefresh: () => _load(),
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            SizedBox(
              height: 420,
              child: EmptyState(
                icon: Icons.inventory_2_outlined,
                title: context.tr(_status == null ? 'myp.empty_title' : 'myp.empty_filtered'),
                message: _status == null ? context.tr('myp.empty_msg') : null,
              ),
            ),
          ],
        ),
      );
    } else {
      final lang = Localizations.localeOf(context).languageCode;
      final hasMore = _items.length < _total;
      content = RefreshIndicator(
        onRefresh: () => _load(),
        child: ListView.separated(
          key: const ValueKey('myp-list'),
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, 96),
          itemCount: _items.length + (hasMore ? 1 : 0),
          separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
          itemBuilder: (context, i) {
            if (i >= _items.length) {
              return Center(
                child: OutlinedButton(
                  onPressed: _loadingMore ? null : () => _load(more: true),
                  child: Text(context.tr('myp.load_more')),
                ),
              );
            }
            return _ProductCard(
              listing: _items[i],
              lang: lang,
              busy: _busyId == _items[i].id,
              onEdit: () => _openEditor(_items[i].id),
              onPublish: () => _runAction(
                _items[i],
                titleKey: 'myp.confirm.publish_title',
                messageKey: 'myp.confirm.publish_msg',
                confirmKey: 'myp.publish',
                okKey: 'myp.ok.published',
                action: (r) => r.publish(_items[i].id),
              ),
              onUnpublish: () => _runAction(
                _items[i],
                titleKey: 'myp.confirm.unpublish_title',
                messageKey: 'myp.confirm.unpublish_msg',
                confirmKey: 'myp.unpublish',
                okKey: 'myp.ok.unpublished',
                action: (r) => r.unpublish(_items[i].id),
              ),
              onDelete: () => _runAction(
                _items[i],
                titleKey: 'myp.confirm.delete_title',
                messageKey: 'myp.confirm.delete_msg',
                confirmKey: 'myp.delete',
                okKey: 'myp.ok.deleted',
                action: (r) => r.delete(_items[i].id),
              ),
            );
          },
        ),
      );
    }
    return Column(
      children: [
        _buildChips(context),
        Expanded(child: content),
      ],
    );
  }
}

class _ProductCard extends StatelessWidget {
  const _ProductCard({
    required this.listing,
    required this.lang,
    required this.busy,
    required this.onEdit,
    required this.onPublish,
    required this.onUnpublish,
    required this.onDelete,
  });

  final OwnedListing listing;
  final String lang;
  final bool busy;
  final VoidCallback onEdit;
  final VoidCallback onPublish;
  final VoidCallback onUnpublish;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final l = listing;
    final theme = Theme.of(context);
    final color = _statusColor(l.status);
    return AppCard(
      key: ValueKey('myp-card-${l.id}'),
      onTap: onEdit,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  l.displayTitle(lang),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                decoration: BoxDecoration(
                  color: color.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  context.tr('myp.status.${l.status.json}'),
                  style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 12),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            l.price.format(),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 2),
          Text(
            '${context.tr('myp.kind.${l.kind.json}')} • ${context.tr('myp.cond.${l.condition.json}')}'
            '${l.moq == null ? '' : ' • MOQ ${l.moq}'}',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.sm),
          if (busy)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 6),
              child: LinearProgressIndicator(),
            )
          else
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: 0,
              children: [
                TextButton.icon(
                  key: ValueKey('myp-edit-${l.id}'),
                  onPressed: onEdit,
                  icon: const Icon(Icons.edit_outlined, size: 18),
                  label: Text(context.tr('myp.edit')),
                ),
                if (l.status == ListingStatus.published)
                  TextButton.icon(
                    key: ValueKey('myp-unpublish-${l.id}'),
                    onPressed: onUnpublish,
                    icon: const Icon(Icons.visibility_off_outlined, size: 18),
                    label: Text(context.tr('myp.unpublish')),
                  )
                else
                  TextButton.icon(
                    key: ValueKey('myp-publish-${l.id}'),
                    onPressed: onPublish,
                    icon: const Icon(Icons.publish, size: 18),
                    label: Text(context.tr('myp.publish')),
                  ),
                TextButton.icon(
                  key: ValueKey('myp-delete-${l.id}'),
                  onPressed: onDelete,
                  style: TextButton.styleFrom(foregroundColor: AppColors.danger),
                  icon: const Icon(Icons.delete_outline, size: 18),
                  label: Text(context.tr('myp.delete')),
                ),
              ],
            ),
        ],
      ),
    );
  }
}
