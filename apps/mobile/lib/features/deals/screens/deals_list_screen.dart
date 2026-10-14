import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/deals/deals_models.dart';
import 'package:factory_finder/features/deals/deals_repository.dart';
import 'package:factory_finder/features/deals/widgets/deal_lifecycle_section.dart'
    show dealStatusColor;
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/screens/requests_screen.dart' show StatusPill;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Statuses offered by the filter row (null = all).
const List<String> kDealFilterStatuses = <String>[
  kDealPendingPayment,
  kDealPaid,
  kDealInFulfilment,
  kDealCompleted,
];

const int kDealsPageSize = 20;

/// The caller's deals from the backend (live) or the in-memory mock state,
/// with role tabs, a status filter, pull-to-refresh and load more.
class DealsListScreen extends ConsumerStatefulWidget {
  const DealsListScreen({super.key});

  @override
  ConsumerState<DealsListScreen> createState() => _DealsListScreenState();
}

class _DealsListScreenState extends ConsumerState<DealsListScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs;
  String? _status;
  List<Deal> _items = <Deal>[];
  int _page = 0;
  int _total = 0;
  bool _loading = true;
  bool _loadingMore = false;
  Object? _error;
  int _gen = 0;

  String get _role => _tabs.index == 0 ? 'buyer' : 'supplier';

  @override
  void initState() {
    super.initState();
    _tabs = TabController(length: 2, vsync: this)
      ..addListener(() {
        if (!_tabs.indexIsChanging) _reload();
      });
    _reload();
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  bool get _hasMore => _items.length < _total;

  /// Loads page 1. With [keep] the current list stays visible meanwhile
  /// (refresh / coming back from a deal).
  Future<void> _reload({bool keep = false}) async {
    final gen = ++_gen;
    setState(() {
      _error = null;
      _loadingMore = false;
      if (!keep) {
        _loading = true;
        _items = <Deal>[];
        _total = 0;
        _page = 0;
      }
    });
    try {
      final r = await ref.read(dealsRepositoryProvider).listDeals(
            role: _role,
            status: _status,
            page: 1,
            pageSize: kDealsPageSize,
          );
      if (!mounted || gen != _gen) return;
      setState(() {
        _items = r.items;
        _total = r.total;
        _page = 1;
        _loading = false;
      });
    } catch (e) {
      if (!mounted || gen != _gen) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  Future<void> _loadMore() async {
    if (_loadingMore || _loading || !_hasMore) return;
    final gen = _gen;
    setState(() => _loadingMore = true);
    try {
      final r = await ref.read(dealsRepositoryProvider).listDeals(
            role: _role,
            status: _status,
            page: _page + 1,
            pageSize: kDealsPageSize,
          );
      if (!mounted || gen != _gen) return;
      final seen = _items.map((d) => d.id).toSet();
      setState(() {
        _items = [..._items, ...r.items.where((d) => !seen.contains(d.id))];
        _total = r.total;
        _page += 1;
        _loadingMore = false;
      });
    } catch (e) {
      if (!mounted || gen != _gen) return;
      setState(() => _loadingMore = false);
      final messenger = ScaffoldMessenger.of(context);
      messenger.clearSnackBars();
      messenger.showSnackBar(SnackBar(content: Text(context.tr(dealErrorKey(e)))));
    }
  }

  void _setStatus(String? s) {
    if (s == _status) return;
    _status = s;
    _reload();
  }

  Future<void> _open(Deal deal) async {
    await context.push<void>('/deals/${deal.id}');
    if (mounted) _reload(keep: true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.tr('deals.list.title')),
        bottom: TabBar(
          key: const Key('deals_role_tabs'),
          controller: _tabs,
          tabs: [
            Tab(key: const Key('deals_tab_buyer'), text: context.tr('deals.tab.buyer')),
            Tab(
              key: const Key('deals_tab_supplier'),
              text: context.tr('deals.tab.supplier'),
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          _StatusFilter(selected: _status, onSelected: _setStatus),
          Expanded(child: _body(context)),
        ],
      ),
    );
  }

  Widget _body(BuildContext context) {
    if (_loading) return const LoadingList(itemCount: 4);
    Widget scrollable(List<Widget> children) => RefreshIndicator(
          onRefresh: () => _reload(keep: true),
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(AppSpacing.lg),
            children: children,
          ),
        );
    if (_error != null && _items.isEmpty) {
      return scrollable([
        ErrorState(
          key: const Key('deals_error'),
          error: _error!,
          onRetry: _reload,
        ),
      ]);
    }
    if (_items.isEmpty) {
      return scrollable([
        EmptyState(
          key: const Key('deals_empty'),
          icon: Icons.assignment_turned_in_outlined,
          title: context.tr('deals.list.empty_title'),
          message: context.tr(
            _status == null ? 'deals.list.empty_msg' : 'deals.list.empty_filtered',
          ),
        ),
      ]);
    }
    return scrollable([
      for (final d in _items)
        Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.sm),
          child: _DealTile(deal: d, onTap: () => _open(d)),
        ),
      if (_hasMore)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: Center(
            child: _loadingMore
                ? const SizedBox(
                    width: 24,
                    height: 24,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : OutlinedButton(
                    key: const Key('deals_load_more'),
                    onPressed: _loadMore,
                    child: Text(context.tr('deals.list.load_more')),
                  ),
          ),
        ),
    ]);
  }
}

class _StatusFilter extends StatelessWidget {
  const _StatusFilter({required this.selected, required this.onSelected});

  final String? selected;
  final ValueChanged<String?> onSelected;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.lg,
        vertical: AppSpacing.sm,
      ),
      child: Row(
        children: [
          Padding(
            padding: const EdgeInsetsDirectional.only(end: AppSpacing.sm),
            child: ChoiceChip(
              key: const Key('deals_filter_all'),
              label: Text(context.tr('deals.filter.all')),
              selected: selected == null,
              onSelected: (_) => onSelected(null),
            ),
          ),
          for (final s in kDealFilterStatuses)
            Padding(
              padding: const EdgeInsetsDirectional.only(end: AppSpacing.sm),
              child: ChoiceChip(
                key: Key('deals_filter_$s'),
                label: Text(context.tr('deals.status.$s')),
                selected: selected == s,
                onSelected: (_) => onSelected(s),
              ),
            ),
        ],
      ),
    );
  }
}

class _DealTile extends StatelessWidget {
  const _DealTile({required this.deal, required this.onTap});
  final Deal deal;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final statusKey = 'deals.status.${deal.status}';
    final label = context.tr(statusKey);
    return AppCard(
      key: Key('deal_tile_${deal.id}'),
      onTap: onTap,
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  deal.subtotal.format(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 2),
                Text(
                  deal.id,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Flexible(
            child: StatusPill(
              label: label == statusKey ? deal.status : label,
              color: dealStatusColor(deal.status),
            ),
          ),
        ],
      ),
    );
  }
}
