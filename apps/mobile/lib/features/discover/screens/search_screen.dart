import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/data/saved_search.dart';
import 'package:factory_finder/features/discover/data/search_facets.dart';
import 'package:factory_finder/features/discover/widgets/compare_tray.dart';
import 'package:factory_finder/features/discover/widgets/listing_card.dart';
import 'package:factory_finder/features/watchlist/data/watch_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key, this.initialQuery = ''});

  final String initialQuery;

  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  late ListingQuery _query = ListingQuery(query: widget.initialQuery);
  late final TextEditingController _controller =
      TextEditingController(text: widget.initialQuery);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  SearchFacets? _facets;

  String _sortLabel(SortOption o) {
    switch (o) {
      case SortOption.relevance:
        return context.tr('discover.sort.relevance');
      case SortOption.priceLow:
        return context.tr('discover.sort.price_low');
      case SortOption.priceHigh:
        return context.tr('discover.sort.price_high');
      case SortOption.trust:
        return context.tr('discover.sort.trust');
      case SortOption.moq:
        return context.tr('discover.sort.moq');
    }
  }

  Future<void> _openFilters() async {
    final facets = _facets;
    final result = await showModalBottomSheet<ListingQuery>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _FilterSheet(initial: _query, facets: facets),
    );
    if (result != null) setState(() => _query = result);
  }

  void _snack(String text) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    messenger.showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _saveSearch() async {
    final q = _query.copyWith(query: _controller.text.trim());
    final emptyText = context.tr('compare.search_empty');
    final savedText = context.tr('compare.search_saved');
    final loginText = context.tr('watch.login_required');
    final failText = context.tr('watch.failed');
    if (!canSaveSearch(q)) {
      _snack(emptyText);
      return;
    }
    try {
      await ref.read(watchlistRepositoryProvider).addSearch(
            savedSearchPayload(q),
            title: savedSearchTitle(q),
            titleAr: savedSearchTitle(q),
          );
      if (!mounted) return;
      ref.invalidate(watchlistProvider);
      _snack(savedText);
    } on ApiException catch (e) {
      if (mounted) _snack(e.isUnauthorized ? loginText : failText);
    } catch (_) {
      if (mounted) _snack(failText);
    }
  }

  @override
  Widget build(BuildContext context) {
    final results = ref.watch(listingsProvider(_query));
    final pageFacets = results.valueOrNull;
    if (pageFacets is ListingPage && pageFacets.facets != null) {
      _facets = pageFacets.facets;
    }
    return Scaffold(
      bottomNavigationBar: const CompareTray(),
      appBar: AppBar(
        title: TextField(
          controller: _controller,
          textInputAction: TextInputAction.search,
          onSubmitted: (v) => setState(() => _query = _query.copyWith(query: v.trim())),
          decoration: InputDecoration(
            hintText: context.tr('discover.search_hint'),
            prefixIcon: const Icon(Icons.search),
            isDense: true,
          ),
        ),
        actions: [
          IconButton(
            tooltip: context.tr('compare.save_search'),
            onPressed: _saveSearch,
            icon: const Icon(Icons.bookmark_add_outlined),
          ),
          IconButton(
            tooltip: context.tr('discover.filters'),
            onPressed: _openFilters,
            icon: Badge(
              isLabelVisible: _query.activeFilterCount > 0,
              label: Text('${_query.activeFilterCount}'),
              child: const Icon(Icons.tune),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          const SizedBox(height: AppSpacing.sm),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: Row(
              children: [
                Text(
                  context.tr('discover.sort'),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: DropdownButton<SortOption>(
                    key: const ValueKey('search-sort'),
                    value: _query.sort,
                    isExpanded: true,
                    onChanged: (v) {
                      if (v != null) {
                        setState(() => _query = _query.copyWith(sort: v));
                      }
                    },
                    items: [
                      for (final o in SortOption.values)
                        DropdownMenuItem<SortOption>(
                          value: o,
                          child: Text(_sortLabel(o), overflow: TextOverflow.ellipsis),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: results.when(
              loading: () => const SingleChildScrollView(child: LoadingList()),
              error: (e, _) => ErrorState(
                message: '$e',
                onRetry: () => ref.invalidate(listingsProvider(_query)),
              ),
              data: (page) {
                if (page.items.isEmpty) {
                  return EmptyState(
                    icon: Icons.search_off,
                    title: context.tr('discover.empty_title'),
                    message: context.tr('discover.empty_msg'),
                  );
                }
                return CustomScrollView(
                  slivers: [
                    SliverToBoxAdapter(
                      child: Padding(
                        padding: const EdgeInsets.all(AppSpacing.lg),
                        child: Text(
                          context.tr('discover.results_count', {'n': '${page.total}'}),
                          style: const TextStyle(color: AppColors.textSecondary),
                        ),
                      ),
                    ),
                    ListingGrid(items: page.items),
                    const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.xxl)),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _FilterSheet extends StatefulWidget {
  const _FilterSheet({required this.initial, this.facets});

  final ListingQuery initial;
  final SearchFacets? facets;

  @override
  State<_FilterSheet> createState() => _FilterSheetState();
}

class _FilterSheetState extends State<_FilterSheet> {
  late ListingKind? _kind = widget.initial.kind;
  late ItemCondition? _condition = widget.initial.condition;
  late String? _origin = widget.initial.originCountry;
  late int? _maxMoq = widget.initial.maxMoq;
  late bool _verified = widget.initial.verifiedOnly;

  static const List<String> _origins = ['CN', 'DE', 'IT', 'TR', 'US'];
  static const List<int?> _moqOptions = [null, 10, 100, 500, 1000];

  Widget _label(String text) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.lg, bottom: AppSpacing.sm),
        child: Text(text, style: const TextStyle(fontWeight: FontWeight.w800)),
      );

  @override
  Widget build(BuildContext context) {
    final any = context.tr('discover.filter.any');
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            _label(context.tr('discover.filter.kind')),
            Wrap(
              spacing: AppSpacing.sm,
              children: [
                ChoiceChip(
                  label: Text(any),
                  selected: _kind == null,
                  onSelected: (_) => setState(() => _kind = null),
                ),
                for (final k in ListingKind.values)
                  ChoiceChip(
                    label: Text(
                      '${context.tr('discover.kind.${k.json}')}${facetSuffix(widget.facets?.kind, k.json)}',
                    ),
                    selected: _kind == k,
                    onSelected: (_) => setState(() => _kind = k),
                  ),
              ],
            ),
            _label(context.tr('discover.filter.condition')),
            Wrap(
              spacing: AppSpacing.sm,
              children: [
                ChoiceChip(
                  label: Text(any),
                  selected: _condition == null,
                  onSelected: (_) => setState(() => _condition = null),
                ),
                for (final c in ItemCondition.values)
                  ChoiceChip(
                    label: Text(
                      '${context.tr('condition.${c.json}')}${facetSuffix(widget.facets?.condition, c.json)}',
                    ),
                    selected: _condition == c,
                    onSelected: (_) => setState(() => _condition = c),
                  ),
              ],
            ),
            _label(context.tr('discover.filter.origin')),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                ChoiceChip(
                  label: Text(any),
                  selected: _origin == null,
                  onSelected: (_) => setState(() => _origin = null),
                ),
                for (final o in _origins)
                  ChoiceChip(
                    avatar: CountryFlag(countryCode: o, size: 14),
                    label: Text(
                      '${context.tr('country.$o')}${facetSuffix(widget.facets?.originCountry, o)}',
                    ),
                    selected: _origin == o,
                    onSelected: (_) => setState(() => _origin = o),
                  ),
              ],
            ),
            _label(context.tr('discover.filter.max_moq')),
            Wrap(
              spacing: AppSpacing.sm,
              children: [
                for (final m in _moqOptions)
                  ChoiceChip(
                    label: Text(m == null ? any : '≤ $m'),
                    selected: _maxMoq == m,
                    onSelected: (_) => setState(() => _maxMoq = m),
                  ),
              ],
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(context.tr('discover.filter.verified')),
              value: _verified,
              onChanged: (v) => setState(() => _verified = v),
            ),
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(context).pop(
                      ListingQuery(
                        query: widget.initial.query,
                        sort: widget.initial.sort,
                        category: widget.initial.category,
                        supplierId: widget.initial.supplierId,
                      ),
                    ),
                    child: Text(context.tr('common.reset')),
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  flex: 2,
                  child: PrimaryButton(
                    label: context.tr('common.apply'),
                    onPressed: () => Navigator.of(context).pop(
                      ListingQuery(
                        query: widget.initial.query,
                        sort: widget.initial.sort,
                        category: widget.initial.category,
                        supplierId: widget.initial.supplierId,
                        kind: _kind,
                        condition: _condition,
                        originCountry: _origin,
                        maxMoq: _maxMoq,
                        verifiedOnly: _verified,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
