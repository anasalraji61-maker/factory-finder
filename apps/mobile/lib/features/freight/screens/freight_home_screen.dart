import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/data/freight_errors.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/data/freight_prefill.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/freight/widgets/freight_paged_list.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

const String kFreightBase = '/logistics/freight';

/// Entry point: "Freight quotes" with a buyer tab and a forwarder tab.
class FreightHomeScreen extends StatelessWidget {
  const FreightHomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(context.tr('freight.title')),
          bottom: TabBar(
            tabs: [
              Tab(key: const ValueKey<String>('freight_tab_buyer'), text: context.tr('freight.tab.buyer')),
              Tab(key: const ValueKey<String>('freight_tab_forwarder'), text: context.tr('freight.tab.forwarder')),
            ],
          ),
        ),
        body: const TabBarView(
          children: [FreightBuyerTab(), FreightForwarderTab()],
        ),
      ),
    );
  }
}

/// My shipment requests + the "new request" button.
class FreightBuyerTab extends ConsumerStatefulWidget {
  const FreightBuyerTab({super.key});

  @override
  ConsumerState<FreightBuyerTab> createState() => _FreightBuyerTabState();
}

class _FreightBuyerTabState extends ConsumerState<FreightBuyerTab> {
  String? _status;

  @override
  Widget build(BuildContext context) {
    final repo = ref.watch(freightRepositoryProvider);
    return FreightPagedList<ShipmentRequest>(
      key: ValueKey<String>('freight_requests_${_status ?? 'all'}'),
      idPrefix: 'freight_requests',
      fetch: (cursor) => repo.myRequests(status: _status, cursor: cursor),
      emptyIcon: Icons.local_shipping_outlined,
      emptyTitle: context.tr('freight.requests.empty'),
      emptyMessage: context.tr('freight.requests.empty_msg'),
      header: [
        PrimaryButton(
          key: const ValueKey<String>('freight_new_request'),
          label: context.tr('freight.new_request'),
          icon: Icons.add,
          onPressed: () {
            ref.read(freightPrefillProvider.notifier).state = null;
            context.push('$kFreightBase/new');
          },
        ),
        const SizedBox(height: AppSpacing.md),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ChoiceChip(
              key: const ValueKey<String>('freight_filter_all'),
              label: Text(context.tr('common.all')),
              selected: _status == null,
              onSelected: (_) => setState(() => _status = null),
            ),
            for (final s in kRequestStatuses)
              ChoiceChip(
                key: ValueKey<String>('freight_filter_$s'),
                label: Text(context.tr('freight.status.$s')),
                selected: _status == s,
                onSelected: (_) => setState(() => _status = s),
              ),
          ],
        ),
        const SizedBox(height: AppSpacing.lg),
      ],
      itemBuilder: (context, r) => FreightRequestTile(
        key: ValueKey<String>('freight_request_${r.id}'),
        request: r,
        onTap: () => context.push('$kFreightBase/requests/${r.id}'),
      ),
    );
  }
}

/// Forwarder side: application state, inbox and my quotes.
class FreightForwarderTab extends ConsumerStatefulWidget {
  const FreightForwarderTab({super.key});

  @override
  ConsumerState<FreightForwarderTab> createState() => _FreightForwarderTabState();
}

class _FreightForwarderTabState extends ConsumerState<FreightForwarderTab> {
  late Future<Whoami> _who;
  String _section = 'inbox';

  @override
  void initState() {
    super.initState();
    _who = ref.read(freightRepositoryProvider).whoami();
  }

  void _reload() {
    setState(() => _who = ref.read(freightRepositoryProvider).whoami());
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<int>(freightRefreshProvider, (previous, next) => _reload());
    return FutureBuilder<Whoami>(
      future: _who,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(
            child: CircularProgressIndicator(key: ValueKey<String>('freight_forwarder_loading')),
          );
        }
        if (snap.hasError) {
          return ErrorState(
            key: const ValueKey<String>('freight_forwarder_error'),
            message: context.freightError(snap.error!),
            error: snap.error,
            onRetry: _reload,
          );
        }
        final who = snap.data!;
        if (who.isActive) return _active(context);
        if (who.isSuspended) {
          return ListView(
            padding: const EdgeInsets.all(AppSpacing.lg),
            children: [
              FreightErrorBox(
                context.tr('freight.err.forwarder_suspended'),
                key: const ValueKey<String>('freight_suspended'),
              ),
            ],
          );
        }
        return const _ApplicationStatus();
      },
    );
  }

  Widget _active(BuildContext context) {
    final repo = ref.read(freightRepositoryProvider);
    final chips = Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final s in const ['inbox', 'quotes'])
          ChoiceChip(
            key: ValueKey<String>('freight_section_$s'),
            label: Text(context.tr('freight.section.$s')),
            selected: _section == s,
            onSelected: (_) => setState(() => _section = s),
          ),
      ],
    );
    if (_section == 'inbox') {
      return FreightPagedList<ShipmentRequest>(
        key: const ValueKey<String>('freight_inbox_list'),
        idPrefix: 'freight_inbox',
        fetch: (cursor) => repo.inbox(cursor: cursor),
        emptyIcon: Icons.inbox_outlined,
        emptyTitle: context.tr('freight.inbox.empty'),
        emptyMessage: context.tr('freight.inbox.empty_msg'),
        header: [chips, const SizedBox(height: AppSpacing.lg)],
        itemBuilder: (context, r) => FreightRequestTile(
          key: ValueKey<String>('freight_inbox_${r.id}'),
          request: r,
          showQuoted: true,
          onTap: () => context.push('$kFreightBase/forwarder/requests/${r.id}'),
        ),
      );
    }
    return FreightPagedList<Quote>(
      key: const ValueKey<String>('freight_myquotes_list'),
      idPrefix: 'freight_myquotes',
      fetch: (cursor) => repo.myQuotes(cursor: cursor),
      emptyIcon: Icons.request_quote_outlined,
      emptyTitle: context.tr('freight.myquotes.empty'),
      emptyMessage: context.tr('freight.myquotes.empty_msg'),
      header: [chips, const SizedBox(height: AppSpacing.lg)],
      itemBuilder: (context, q) => AppCard(
        key: ValueKey<String>('freight_myquote_${q.id}'),
        padding: const EdgeInsets.all(AppSpacing.lg),
        onTap: () => context.push('$kFreightBase/forwarder/requests/${q.requestId}'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                FreightMoney(q.amount, q.currency),
                FreightChip(
                  context.tr('freight.qstatus.${q.status}'),
                  color: quoteStatusColor(q.status),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              [
                context.tr('freight.days', {'n': '${q.transitDays}'}),
                context.tr('freight.revision', {'n': '${q.revision}'}),
              ].join(' · '),
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: AppColors.secondaryOf(context)),
            ),
          ],
        ),
      ),
    );
  }
}

/// Shown to users that are not (yet) forwarders: latest application + apply.
class _ApplicationStatus extends ConsumerStatefulWidget {
  const _ApplicationStatus();

  @override
  ConsumerState<_ApplicationStatus> createState() => _ApplicationStatusState();
}

class _ApplicationStatusState extends ConsumerState<_ApplicationStatus> {
  late Future<FreightPage<FreightApplication>> _apps;

  @override
  void initState() {
    super.initState();
    _apps = ref.read(freightRepositoryProvider).myApplications();
  }

  void _reload() {
    setState(() => _apps = ref.read(freightRepositoryProvider).myApplications());
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<FreightPage<FreightApplication>>(
      future: _apps,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(
            child: CircularProgressIndicator(key: ValueKey<String>('freight_apps_loading')),
          );
        }
        if (snap.hasError) {
          return ErrorState(
            key: const ValueKey<String>('freight_apps_error'),
            message: context.freightError(snap.error!),
            error: snap.error,
            onRetry: _reload,
          );
        }
        final apps = snap.data!.items;
        final pending = apps.any((a) => a.isPending);
        return ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            Text(
              context.tr('freight.apply.intro'),
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: AppSpacing.lg),
            if (!pending)
              PrimaryButton(
                key: const ValueKey<String>('freight_apply'),
                label: context.tr('freight.apply.cta'),
                icon: Icons.business_center_outlined,
                onPressed: () async {
                  await context.push('$kFreightBase/forwarder/apply');
                  if (mounted) _reload();
                },
              ),
            const SizedBox(height: AppSpacing.lg),
            if (apps.isNotEmpty)
              SectionHeader(title: context.tr('freight.apply.history')),
            for (final a in apps)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: _ApplicationCard(app: a),
              ),
          ],
        );
      },
    );
  }
}

class _ApplicationCard extends StatelessWidget {
  const _ApplicationCard({required this.app});

  final FreightApplication app;

  @override
  Widget build(BuildContext context) {
    final color = app.status == 'approved'
        ? AppColors.success
        : app.status == 'rejected'
            ? AppColors.danger
            : AppColors.warning;
    return AppCard(
      key: ValueKey<String>('freight_app_${app.id}'),
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(app.companyName, style: const TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              FreightChip(context.tr('freight.app.status.${app.status}'), color: color),
              for (final m in app.modes) FreightChip(freightModeName(context, m)),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            context.tr('freight.app.status_msg.${app.status}'),
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (app.reviewNote != null && app.reviewNote!.isNotEmpty)
            FreightInfoLine(context.tr('freight.app.note'), app.reviewNote!),
        ],
      ),
    );
  }
}
