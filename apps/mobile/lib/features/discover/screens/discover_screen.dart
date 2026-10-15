import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/widgets/compare_tray.dart';
import 'package:factory_finder/features/discover/widgets/listing_card.dart';
import 'package:factory_finder/features/feed/feed_module.dart';
import 'package:factory_finder/features/reco/widgets/reco_carousel.dart';
import 'package:factory_finder/features/watchlist/screens/alerts_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

const List<ListingKind?> _kinds = [
  null,
  ListingKind.product,
  ListingKind.rawMaterial,
  ListingKind.productionLine,
];

class DiscoverScreen extends ConsumerStatefulWidget {
  const DiscoverScreen({super.key});

  @override
  ConsumerState<DiscoverScreen> createState() => _DiscoverScreenState();
}

class _DiscoverScreenState extends ConsumerState<DiscoverScreen> {
  int _kindIndex = 0;
  int _categoryIndex = 0; // 0 = all
  final TextEditingController _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  void _submit(String text) {
    final q = Uri.encodeQueryComponent(text.trim());
    context.push('/discover/search?q=$q');
  }

  ListingQuery get _query {
    final kind = _kinds[_kindIndex];
    final cats = kind == null ? const <String>[] : kCategoriesByKind[kind]!;
    return ListingQuery(
      kind: kind,
      category: (_categoryIndex > 0 && _categoryIndex <= cats.length)
          ? cats[_categoryIndex - 1]
          : null,
    );
  }

  @override
  Widget build(BuildContext context) {
    final kind = _kinds[_kindIndex];
    final cats = kind == null ? const <String>[] : kCategoriesByKind[kind]!;
    final feed = ref.watch(listingsProvider(_query));
    final trending = ref.watch(trendingProvider);
    final theme = Theme.of(context);
    final offline = (feed.hasError && isNetworkError(feed.error!)) ||
        (trending.hasError && isNetworkError(trending.error!));
    final textScale = MediaQuery.textScalerOf(context).scale(14) / 14;

    return Scaffold(
      bottomNavigationBar: const CompareTray(),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(listingsProvider(_query));
            ref.invalidate(trendingProvider);
          },
          child: CustomScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            slivers: [
              if (offline)
                SliverToBoxAdapter(
                  child: OfflineBanner(onRetry: () {
                    ref.invalidate(listingsProvider(_query));
                    ref.invalidate(trendingProvider);
                  }),
                ),
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg,
                    AppSpacing.lg,
                    AppSpacing.lg,
                    AppSpacing.md,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              context.tr('discover.greeting'),
                              style: theme.textTheme.bodyMedium
                                  ?.copyWith(color: AppColors.secondaryOf(context)),
                            ),
                          ),
                          const FeedEntryButton(),
                          const AlertsBell(),
                        ],
                      ),
                      const SizedBox(height: 2),
                      Text(
                        context.tr('discover.headline'),
                        style: theme.textTheme.headlineSmall
                            ?.copyWith(fontWeight: FontWeight.w900),
                      ),
                      const SizedBox(height: AppSpacing.lg),
                      TextField(
                        controller: _search,
                        textInputAction: TextInputAction.search,
                        onSubmitted: _submit,
                        decoration: InputDecoration(
                          hintText: context.tr('discover.search_hint'),
                          prefixIcon: const Icon(Icons.search),
                          suffixIcon: IconButton(
                            tooltip: context.tr('a11y.search_filters'),
                            icon: const Icon(Icons.tune),
                            onPressed: () => _submit(_search.text),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              SliverToBoxAdapter(
                child: FilterChipBar(
                  labels: [
                    context.tr('discover.kind.all'),
                    context.tr('discover.kind.product'),
                    context.tr('discover.kind.raw_material'),
                    context.tr('discover.kind.production_line'),
                  ],
                  selectedIndex: _kindIndex,
                  onSelected: (i) => setState(() {
                    _kindIndex = i;
                    _categoryIndex = 0;
                  }),
                ),
              ),
              if (cats.isNotEmpty)
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.sm),
                    child: FilterChipBar(
                      labels: [
                        context.tr('common.all'),
                        for (final c in cats) context.tr('cat.$c'),
                      ],
                      selectedIndex: _categoryIndex,
                      onSelected: (i) => setState(() => _categoryIndex = i),
                    ),
                  ),
                ),
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                  child: SectionHeader(title: context.tr('discover.trending')),
                ),
              ),
              SliverToBoxAdapter(
                child: SizedBox(
                  height: 290 * (textScale < 1 ? 1.0 : (textScale > 1.6 ? 1.6 : textScale)),
                  child: trending.when(
                    loading: () => const Center(child: CircularProgressIndicator()),
                    error: (e, _) => ErrorState(
                      error: e,
                      onRetry: () => ref.invalidate(trendingProvider),
                    ),
                    data: (items) => ListView.separated(
                      scrollDirection: Axis.horizontal,
                      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                      itemCount: items.length,
                      separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.md),
                      itemBuilder: (_, i) => SizedBox(
                        width: 180,
                        child: ListingCard(listing: items[i]),
                      ),
                    ),
                  ),
                ),
              ),
              const SliverToBoxAdapter(child: RecommendedSection()),
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                  child: SectionHeader(title: context.tr('discover.feed')),
                ),
              ),
              ...feed.when(
                loading: () => <Widget>[
                  const SliverToBoxAdapter(child: LoadingList(itemCount: 4)),
                ],
                error: (e, _) => <Widget>[
                  SliverToBoxAdapter(
                    child: ErrorState(
                      error: e,
                      onRetry: () => ref.invalidate(listingsProvider(_query)),
                    ),
                  ),
                ],
                data: (page) => page.items.isEmpty
                    ? <Widget>[
                        SliverToBoxAdapter(
                          child: EmptyState(
                            icon: Icons.search_off,
                            title: context.tr('discover.empty_title'),
                            message: context.tr('discover.empty_msg'),
                          ),
                        ),
                      ]
                    : <Widget>[ListingGrid(items: page.items)],
              ),
              const SliverToBoxAdapter(child: SizedBox(height: AppSpacing.xxl)),
            ],
          ),
        ),
      ),
    );
  }
}
