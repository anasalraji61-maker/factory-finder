import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/requests/data/mock_rfq.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Localised unit label; falls back to the raw unit code.
String rfqUnitLabel(BuildContext context, String unit) {
  final key = 'req.unit.$unit';
  final t = context.tr(key);
  return t == key ? unit : t;
}

Color rfqStatusColor(RfqStatus s) {
  switch (s) {
    case RfqStatus.open:
      return AppColors.primary;
    case RfqStatus.negotiating:
      return AppColors.warning;
    case RfqStatus.awarded:
      return AppColors.success;
    case RfqStatus.closed:
    case RfqStatus.cancelled:
    case RfqStatus.expired:
      return AppColors.textSecondary;
  }
}

class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 12),
      ),
    );
  }
}

class RequestsScreen extends ConsumerStatefulWidget {
  const RequestsScreen({super.key});

  @override
  ConsumerState<RequestsScreen> createState() => _RequestsScreenState();
}

class _RequestsScreenState extends ConsumerState<RequestsScreen> {
  bool _mine = true;

  // Pages appended after the provider's first page via next_cursor.
  RfqPage? _base;
  RfqFilter? _baseFilter;
  List<RfqRequest> _extra = const <RfqRequest>[];
  String? _cursor;
  bool _loadingMore = false;

  Future<void> _loadMore(RfqFilter filter) async {
    final cursor = _cursor;
    if (cursor == null || _loadingMore) return;
    final base = _base;
    setState(() => _loadingMore = true);
    try {
      final next =
          await ref.read(rfqRepositoryProvider).list(filter, cursor: cursor);
      // Ignore results for a list that was refreshed / switched meanwhile.
      if (!mounted || !identical(base, _base)) return;
      setState(() {
        _extra = [..._extra, ...next.items];
        _cursor = next.nextCursor;
        _loadingMore = false;
      });
    } catch (_) {
      if (!mounted || !identical(base, _base)) return;
      setState(() => _loadingMore = false); // button reappears to retry
    }
  }

  @override
  Widget build(BuildContext context) {
    final filter = RfqFilter(mine: _mine);
    final async = ref.watch(rfqListProvider(filter));
    return Scaffold(
      appBar: AppBar(
        title: Text(context.tr('req.title')),
        actions: [
          IconButton(
            key: const ValueKey<String>('req-seller-entry'),
            tooltip: context.tr('req.seller.entry'),
            icon: const Icon(Icons.storefront_outlined),
            onPressed: () => context.push('/requests/open'),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.push('/requests/new'),
        icon: const Icon(Icons.add),
        label: Text(context.tr('req.new')),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: SizedBox(
              width: double.infinity,
              child: SegmentedButton<bool>(
                segments: [
                  ButtonSegment<bool>(
                    value: true,
                    label: Text(context.tr('req.tab.mine')),
                  ),
                  ButtonSegment<bool>(
                    value: false,
                    label: Text(context.tr('req.tab.open')),
                  ),
                ],
                selected: {_mine},
                onSelectionChanged: (s) => setState(() => _mine = s.first),
              ),
            ),
          ),
          Expanded(
            child: async.when(
              loading: () => const LoadingList(),
              error: (e, _) => ErrorState(
                error: e,
                onRetry: () => ref.invalidate(rfqListProvider(filter)),
              ),
              data: (page) {
                if (!identical(page, _base) || _baseFilter != filter) {
                  _base = page;
                  _baseFilter = filter;
                  _extra = const <RfqRequest>[];
                  _cursor = page.nextCursor;
                  _loadingMore = false;
                }
                final items = [...page.items, ..._extra];
                if (items.isEmpty) {
                  return EmptyState(
                    icon: Icons.request_quote_outlined,
                    title: context.tr(
                      _mine ? 'req.empty.mine_title' : 'req.empty.open_title',
                    ),
                    message: context.tr(
                      _mine ? 'req.empty.mine_msg' : 'req.empty.open_msg',
                    ),
                  );
                }
                return RefreshIndicator(
                  onRefresh: () async {
                    ref.invalidate(rfqListProvider(filter));
                    await ref.read(rfqListProvider(filter).future);
                  },
                  child: ListView.separated(
                    padding: const EdgeInsets.fromLTRB(
                      AppSpacing.lg,
                      0,
                      AppSpacing.lg,
                      96,
                    ),
                    itemCount: items.length + (_cursor != null ? 1 : 0),
                    separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
                    itemBuilder: (context, i) {
                      if (i < items.length) return RequestCard(request: items[i]);
                      return Center(
                        child: _loadingMore
                            ? const Padding(
                                padding: EdgeInsets.all(AppSpacing.md),
                                child: CircularProgressIndicator(),
                              )
                            : OutlinedButton(
                                key: const ValueKey<String>('req-load-more'),
                                onPressed: () => _loadMore(filter),
                                child: Text(context.tr('req.load_more')),
                              ),
                      );
                    },
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class RequestCard extends StatelessWidget {
  const RequestCard({super.key, required this.request, this.onTap});

  final RfqRequest request;

  /// Defaults to opening the buyer detail screen.
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final r = request;
    final theme = Theme.of(context);
    return AppCard(
      onTap: onTap ?? () => context.push('/requests/${r.id}'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  r.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              StatusPill(
                label: context.tr('req.status.${r.status.json}'),
                color: rfqStatusColor(r.status),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            context.tr('req.quantity_line', {
              'qty': r.quantity,
              'unit': rfqUnitLabel(context, r.unit),
            }),
            style: const TextStyle(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: [
              Expanded(
                child: Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    StatusPill(
                      label: context.tr('req.kind.${r.kind.json}'),
                      color: AppColors.accent,
                    ),
                    if (r.targetPrice != null) MoneyText(r.targetPrice!),
                  ],
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              const Icon(Icons.local_offer_outlined, size: 16),
              const SizedBox(width: 4),
              Text(
                context.tr('req.offers_count', {'n': '${r.offerCount}'}),
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ],
          ),
          if (r.destination != null) ...[
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                CountryFlag(countryCode: r.destination!.countryCode, size: 16),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    locationLabel(context, r.destination),
                    style: const TextStyle(color: AppColors.textSecondary),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
