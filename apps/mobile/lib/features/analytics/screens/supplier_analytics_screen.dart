import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/analytics/analytics_logic.dart';
import 'package:factory_finder/features/analytics/analytics_models.dart';
import 'package:factory_finder/features/analytics/analytics_repository.dart';
import 'package:factory_finder/features/analytics/widgets/analytics_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Metrics that can be charted (the others are KPI cards only).
const List<AnalyticsMetric> kChartMetrics = <AnalyticsMetric>[
  AnalyticsMetric.impression,
  AnalyticsMetric.view,
  AnalyticsMetric.contactClick,
  AnalyticsMetric.share,
];

String _digits(BuildContext context, String text) =>
    localizeDigits(text, DigitStyleScope.of(context));

class _FilterChoice {
  const _FilterChoice(this.id);
  final String? id;
}

/// Verified-supplier analytics: KPIs with period-over-period change, a daily
/// chart, the conversion funnel and the top listings.
class SupplierAnalyticsScreen extends ConsumerStatefulWidget {
  const SupplierAnalyticsScreen({super.key, this.initialListingId});

  final String? initialListingId;

  @override
  ConsumerState<SupplierAnalyticsScreen> createState() =>
      _SupplierAnalyticsScreenState();
}

class _SupplierAnalyticsScreenState
    extends ConsumerState<SupplierAnalyticsScreen> {
  int _days = kDefaultAnalyticsDays;
  String? _listingId;
  AnalyticsMetric _metric = AnalyticsMetric.view;
  SupplierAnalytics? _data;
  bool _loading = true;
  String? _errorKey;
  int _req = 0;

  /// Listing choices for the filter, remembered from unfiltered responses.
  final Map<String, String> _options = <String, String>{};

  @override
  void initState() {
    super.initState();
    final id = widget.initialListingId;
    _listingId = (id == null || id.isEmpty) ? null : id;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

  Future<void> _load() async {
    final token = ++_req;
    setState(() {
      _loading = true;
      _errorKey = null;
    });
    try {
      final res = await ref
          .read(analyticsRepositoryProvider)
          .fetch(days: _days, listingId: _listingId);
      if (!mounted || token != _req) return;
      setState(() {
        _data = res;
        _loading = false;
        for (final r in res.listings) {
          if (r.listingId.isNotEmpty) _options[r.listingId] = r.title;
        }
      });
    } catch (e) {
      if (!mounted || token != _req) return;
      setState(() {
        _data = null;
        _loading = false;
        _errorKey = analyticsErrorKey(e);
      });
    }
  }

  void _setDays(int d) {
    if (d == _days) return;
    _days = d;
    _load();
  }

  Future<void> _pickListing() async {
    final choice = await showModalBottomSheet<_FilterChoice>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.only(bottom: AppSpacing.lg),
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.lg, vertical: AppSpacing.sm),
              child: Text(
                ctx.tr('ana.filter.title'),
                style: Theme.of(ctx)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.w800),
              ),
            ),
            ListTile(
              key: const ValueKey<String>('ana-filter-opt-all'),
              selected: _listingId == null,
              leading: const Icon(Icons.all_inclusive),
              title: Text(ctx.tr('ana.filter.all')),
              onTap: () => Navigator.of(ctx).pop(const _FilterChoice(null)),
            ),
            for (final e in _options.entries)
              ListTile(
                key: ValueKey<String>('ana-filter-opt-${e.key}'),
                selected: _listingId == e.key,
                leading: const Icon(Icons.inventory_2_outlined),
                title: Text(e.value, maxLines: 2, overflow: TextOverflow.ellipsis),
                onTap: () => Navigator.of(ctx).pop(_FilterChoice(e.key)),
              ),
          ],
        ),
      ),
    );
    if (choice == null || !mounted || choice.id == _listingId) return;
    _listingId = choice.id;
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final children = <Widget>[
      _controls(context),
      ..._body(context),
    ];
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('ana.title'))),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          key: const ValueKey<String>('ana-list'),
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: children,
        ),
      ),
    );
  }

  Widget _controls(BuildContext context) {
    final name = _listingId == null
        ? context.tr('ana.filter.all')
        : (_options[_listingId] ?? _listingId!);
    final data = _data;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (final d in kAnalyticsPeriods)
              ChoiceChip(
                key: ValueKey<String>('ana-period-$d'),
                label: Text(context.tr('ana.period.$d')),
                selected: _days == d,
                onSelected: (_) => _setDays(d),
              ),
          ],
        ),
        const SizedBox(height: AppSpacing.md),
        AppCard(
          key: const ValueKey<String>('ana-filter'),
          onTap: _pickListing,
          semanticLabel: context.tr('ana.filter.label', {'name': name}),
          child: Row(
            children: [
              const Icon(Icons.filter_list, size: 20),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  name,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              const Icon(Icons.arrow_drop_down),
            ],
          ),
        ),
        if (data != null && data.period.from.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.sm),
          Directionality(
            textDirection: TextDirection.ltr,
            child: Text(
              _digits(
                context,
                context.tr('ana.range',
                    {'from': data.period.from, 'to': data.period.to}),
              ),
              key: const ValueKey<String>('ana-range'),
              style: TextStyle(color: AppColors.secondaryOf(context)),
            ),
          ),
        ],
        const SizedBox(height: AppSpacing.md),
      ],
    );
  }

  List<Widget> _body(BuildContext context) {
    if (_loading && _data == null) {
      return const [LoadingList(itemCount: 4)];
    }
    if (_errorKey != null) {
      return [
        SizedBox(
          height: 360,
          child: ErrorState(
            message: context.tr(_errorKey!),
            onRetry: _load,
          ),
        ),
      ];
    }
    final data = _data;
    if (data == null) return const [];
    if (data.isEmpty) {
      return [
        SizedBox(
          height: 360,
          child: EmptyState(
            icon: Icons.insights_outlined,
            title: context.tr('ana.empty.title'),
            message: context.tr('ana.empty.msg'),
          ),
        ),
      ];
    }
    return [
      AnimatedOpacity(
        opacity: _loading ? 0.5 : 1,
        duration: const Duration(milliseconds: 150),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _KpiGrid(data: data),
            const SizedBox(height: AppSpacing.lg),
            _ChartCard(
              data: data,
              metric: _metric,
              onMetric: (m) => setState(() => _metric = m),
            ),
            const SizedBox(height: AppSpacing.lg),
            _FunnelCard(data: data),
            const SizedBox(height: AppSpacing.lg),
            _UniqueCard(data: data),
            const SizedBox(height: AppSpacing.lg),
            _TopListings(data: data),
          ],
        ),
      ),
    ];
  }
}

Color _changeColor(BuildContext context, ChangeDirection dir, bool risingIsBad) {
  final dark = Theme.of(context).brightness == Brightness.dark;
  final good = dark ? const Color(0xFF4ADE80) : const Color(0xFF15803D);
  final bad = dark ? const Color(0xFFFF8A80) : const Color(0xFFB91C1C);
  switch (dir) {
    case ChangeDirection.up:
      return risingIsBad ? bad : good;
    case ChangeDirection.down:
      return risingIsBad ? good : bad;
    case ChangeDirection.flat:
    case ChangeDirection.unknown:
      return AppColors.secondaryOf(context);
  }
}

String _changeSemantics(BuildContext context, ChangeInfo c) {
  switch (c.direction) {
    case ChangeDirection.up:
      return context.tr('ana.change.up', {'pct': formatChange(c)});
    case ChangeDirection.down:
      return context.tr('ana.change.down', {'pct': formatChange(c)});
    case ChangeDirection.flat:
      return context.tr('ana.change.flat');
    case ChangeDirection.unknown:
      return context.tr('ana.change.unknown');
  }
}

/// Arrow icon + signed percent (colour is never the only signal).
class ChangeChip extends StatelessWidget {
  const ChangeChip({super.key, required this.change, this.risingIsBad = false});

  final ChangeInfo change;
  final bool risingIsBad;

  @override
  Widget build(BuildContext context) {
    final color = _changeColor(context, change.direction, risingIsBad);
    final IconData icon;
    switch (change.direction) {
      case ChangeDirection.up:
        icon = Icons.arrow_upward;
      case ChangeDirection.down:
        icon = Icons.arrow_downward;
      case ChangeDirection.flat:
        icon = Icons.remove;
      case ChangeDirection.unknown:
        icon = Icons.remove;
    }
    final text = change.direction == ChangeDirection.unknown
        ? '-'
        : formatChange(change);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: color),
        const SizedBox(width: 2),
        Flexible(
          child: Directionality(
            textDirection: TextDirection.ltr,
            child: Text(
              _digits(context, text),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: color,
                fontWeight: FontWeight.w800,
                fontSize: 13,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _KpiGrid extends StatelessWidget {
  const _KpiGrid({required this.data});

  final SupplierAnalytics data;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, c) {
      const gap = AppSpacing.md;
      final w = (c.maxWidth - gap) / 2;
      return Wrap(
        spacing: gap,
        runSpacing: gap,
        children: [
          for (final m in AnalyticsMetric.values)
            SizedBox(width: w, child: _KpiCard(data: data, metric: m)),
        ],
      );
    });
  }
}

class _KpiCard extends StatelessWidget {
  const _KpiCard({required this.data, required this.metric});

  final SupplierAnalytics data;
  final AnalyticsMetric metric;

  @override
  Widget build(BuildContext context) {
    final label = context.tr('ana.kpi.${metric.json}');
    final value = formatCount(data.totals.of(metric));
    final change = classifyChange(data.changeOf(metric));
    return AppCard(
      key: ValueKey<String>('ana-kpi-${metric.json}'),
      semanticLabel: _digits(
        context,
        context.tr('ana.kpi.semantics', {
          'label': label,
          'value': value,
          'change': _changeSemantics(context, change),
        }),
      ),
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: 13,
              color: AppColors.secondaryOf(context),
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: AlignmentDirectional.centerStart,
            child: Text(
              _digits(context, value),
              key: ValueKey<String>('ana-kpi-value-${metric.json}'),
              style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w900),
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          ChangeChip(change: change, risingIsBad: metric.risingIsBad),
        ],
      ),
    );
  }
}

class _ChartCard extends StatelessWidget {
  const _ChartCard({
    required this.data,
    required this.metric,
    required this.onMetric,
  });

  final SupplierAnalytics data;
  final AnalyticsMetric metric;
  final ValueChanged<AnalyticsMetric> onMetric;

  @override
  Widget build(BuildContext context) {
    final values = [for (final d in data.series) d.counts.of(metric)];
    final peak = values.fold<int>(0, (a, b) => a > b ? a : b);
    final yMax = niceMax(peak);
    final total = values.fold<int>(0, (a, b) => a + b);
    final scheme = Theme.of(context).colorScheme;
    final grid = Theme.of(context).brightness == Brightness.dark
        ? const Color(0xFF26304D)
        : AppColors.border;
    final style = values.length <= 31
        ? AnalyticsChartStyle.bars
        : AnalyticsChartStyle.line;
    final first = data.series.isEmpty ? '' : data.series.first.date;
    final last = data.series.isEmpty ? '' : data.series.last.date;
    return AppCard(
      key: const ValueKey<String>('ana-chart-card'),
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.tr('ana.chart.title'),
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              for (final m in kChartMetrics)
                ChoiceChip(
                  key: ValueKey<String>('ana-metric-${m.json}'),
                  label: Text(context.tr('ana.kpi.${m.json}')),
                  selected: m == metric,
                  onSelected: (_) => onMetric(m),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            _digits(context,
                context.tr('ana.chart.max', {'max': formatCount(peak)})),
            style: TextStyle(
              fontSize: 12,
              color: AppColors.secondaryOf(context),
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          Semantics(
            image: true,
            label: _digits(
              context,
              context.tr('ana.chart.semantics', {
                'metric': context.tr('ana.kpi.${metric.json}'),
                'total': formatCount(total),
                'max': formatCount(peak),
                'days': '${data.series.length}',
              }),
            ),
            child: ExcludeSemantics(
              child: Directionality(
                textDirection: TextDirection.ltr,
                child: SizedBox(
                  height: 160,
                  width: double.infinity,
                  child: CustomPaint(
                    key: const ValueKey<String>('ana-chart'),
                    painter: AnalyticsChartPainter(
                      values: values,
                      yMax: yMax,
                      color: scheme.primary,
                      gridColor: grid,
                      style: style,
                    ),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          Directionality(
            textDirection: TextDirection.ltr,
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    _digits(context, first),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                        fontSize: 11, color: AppColors.secondaryOf(context)),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    _digits(context, last),
                    maxLines: 1,
                    textAlign: TextAlign.end,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                        fontSize: 11, color: AppColors.secondaryOf(context)),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _FunnelCard extends StatelessWidget {
  const _FunnelCard({required this.data});

  final SupplierAnalytics data;

  @override
  Widget build(BuildContext context) {
    final steps = <(String, int)>[
      ('ana.funnel.impression', data.totals.impression),
      ('ana.funnel.view', data.totals.view),
      ('ana.funnel.contact', data.totals.contactClick),
    ];
    final fractions = funnelFractions([for (final s in steps) s.$2]);
    final scheme = Theme.of(context).colorScheme;
    final conv = data.conversion;
    final prev = conv.previousViewToContact;
    return AppCard(
      key: const ValueKey<String>('ana-funnel'),
      semanticLabel: _digits(
        context,
        context.tr('ana.funnel.semantics', {
          'a': formatCount(steps[0].$2),
          'b': formatCount(steps[1].$2),
          'c': formatCount(steps[2].$2),
        }),
      ),
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.tr('ana.funnel.title'),
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.md),
          for (var i = 0; i < steps.length; i++) ...[
            Row(
              children: [
                Expanded(
                  child: Text(
                    context.tr(steps[i].$1),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Text(
                  _digits(context, formatCount(steps[i].$2)),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ],
            ),
            const SizedBox(height: 4),
            LayoutBuilder(builder: (context, c) {
              final f = fractions[i];
              // Non-zero steps keep a visible sliver.
              final w = steps[i].$2 > 0
                  ? (c.maxWidth * f).clamp(4.0, c.maxWidth).toDouble()
                  : 0.0;
              return Stack(
                children: [
                  Container(
                    height: 12,
                    decoration: BoxDecoration(
                      color: scheme.primary.withOpacity(0.10),
                      borderRadius: BorderRadius.circular(6),
                    ),
                  ),
                  Container(
                    key: ValueKey<String>('ana-funnel-bar-$i'),
                    width: w,
                    height: 12,
                    decoration: BoxDecoration(
                      color: scheme.primary,
                      borderRadius: BorderRadius.circular(6),
                    ),
                  ),
                ],
              );
            }),
            const SizedBox(height: AppSpacing.md),
          ],
          Text(
            _digits(
              context,
              context.tr('ana.funnel.imp_to_view',
                  {'pct': formatRatio(conv.impressionToView)}),
            ),
            key: const ValueKey<String>('ana-conv-imp-view'),
          ),
          const SizedBox(height: 2),
          Text(
            _digits(
              context,
              context.tr('ana.funnel.view_to_contact',
                  {'pct': formatRatio(conv.viewToContact)}),
            ),
            key: const ValueKey<String>('ana-conv-view-contact'),
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
          if (prev != null) ...[
            const SizedBox(height: 2),
            Text(
              _digits(
                context,
                context.tr('ana.funnel.previous', {'pct': formatRatio(prev)}),
              ),
              style: TextStyle(
                fontSize: 12,
                color: AppColors.secondaryOf(context),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _UniqueCard extends StatelessWidget {
  const _UniqueCard({required this.data});

  final SupplierAnalytics data;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      key: const ValueKey<String>('ana-unique'),
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.tr('ana.unique.title'),
            style: const TextStyle(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.lg,
            runSpacing: AppSpacing.xs,
            children: [
              Text(_digits(
                context,
                context.tr('ana.unique.views',
                    {'n': formatCount(data.uniqueViewers)}),
              )),
              Text(_digits(
                context,
                context.tr('ana.unique.contacts',
                    {'n': formatCount(data.uniqueContacts)}),
              )),
            ],
          ),
        ],
      ),
    );
  }
}

class _TopListings extends StatelessWidget {
  const _TopListings({required this.data});

  final SupplierAnalytics data;

  @override
  Widget build(BuildContext context) {
    final rows = data.listings;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionHeader(title: context.tr('ana.top.title')),
        for (final r in rows) ...[
          _ListingRow(row: r),
          const SizedBox(height: AppSpacing.sm),
        ],
        if (data.listingsTotal > rows.length)
          Text(
            _digits(
              context,
              context.tr('ana.top.more', {
                'shown': '${rows.length}',
                'total': '${data.listingsTotal}',
              }),
            ),
            style: TextStyle(
              fontSize: 12,
              color: AppColors.secondaryOf(context),
            ),
          ),
      ],
    );
  }
}

class _ListingRow extends StatelessWidget {
  const _ListingRow({required this.row});

  final AnalyticsListingRow row;

  @override
  Widget build(BuildContext context) {
    final views = context.tr('ana.top.views', {'n': formatCount(row.counts.view)});
    final contacts = context.tr(
        'ana.top.contacts', {'n': formatCount(row.counts.contactClick)});
    final conv =
        context.tr('ana.top.conv', {'pct': formatRatio(row.viewToContact)});
    final style = TextStyle(fontSize: 13, color: AppColors.secondaryOf(context));
    return AppCard(
      key: ValueKey<String>('ana-row-${row.listingId}'),
      onTap: () => context.push('/my-products/${row.listingId}'),
      semanticLabel:
          _digits(context, '${row.title}. $views. $contacts. $conv'),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  row.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: AppSpacing.xs),
                Wrap(
                  spacing: AppSpacing.md,
                  runSpacing: 2,
                  children: [
                    Text(_digits(context, views), style: style),
                    Text(_digits(context, contacts), style: style),
                    Text(_digits(context, conv), style: style),
                  ],
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right),
        ],
      ),
    );
  }
}
