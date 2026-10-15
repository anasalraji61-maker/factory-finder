import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart' show Location;
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/data/freight_errors.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart';
import 'package:factory_finder/features/freight/widgets/quote_comparison.dart';
import 'package:factory_finder/features/freight/widgets/report_sheet.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart' show CalculatorSeed;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

class _Loaded {
  const _Loaded(this.request, this.comparison, this.comparisonError);

  final ShipmentRequest request;
  final Comparison? comparison;
  final Object? comparisonError;
}

/// Buyer view of one request: summary, ranked quotes, accept, complete /
/// cancel, rate and report.
class FreightRequestDetailScreen extends ConsumerStatefulWidget {
  const FreightRequestDetailScreen({super.key, required this.requestId});

  final String requestId;

  @override
  ConsumerState<FreightRequestDetailScreen> createState() =>
      _FreightRequestDetailScreenState();
}

class _FreightRequestDetailScreenState
    extends ConsumerState<FreightRequestDetailScreen> {
  late Future<_Loaded> _future;
  String _sort = 'score';
  String? _actionError;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _future = _fetch();
  }

  Future<_Loaded> _fetch() async {
    final repo = ref.read(freightRepositoryProvider);
    final r = await repo.getRequest(widget.requestId);
    Comparison? c;
    Object? ce;
    try {
      c = await repo.compare(widget.requestId);
    } catch (e) {
      ce = e;
    }
    return _Loaded(r, c, ce);
  }

  void _reload({bool keepError = false}) {
    setState(() {
      if (!keepError) _actionError = null;
      _future = _fetch();
    });
  }

  void _snack(String text) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(text)));
  }

  Future<bool> _confirm({
    required String title,
    required String body,
    required String yes,
    required String idPrefix,
  }) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: Text(body),
        actions: [
          TextButton(
            key: ValueKey<String>('${idPrefix}_cancel'),
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(ctx.tr('common.cancel')),
          ),
          FilledButton(
            key: ValueKey<String>('${idPrefix}_confirm'),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(yes),
          ),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _run(Future<void> Function() action, {String? done}) async {
    setState(() {
      _busy = true;
      _actionError = null;
    });
    try {
      await action();
      ref.read(freightRefreshProvider.notifier).state++;
      if (!mounted) return;
      if (done != null) _snack(done);
      _busy = false;
      _reload();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _actionError = context.freightError(e);
      });
      // The award may have changed under us: refresh the data.
      if (_isStale(e)) _reload(keepError: true);
    }
  }

  bool _isStale(Object e) {
    final key = freightErrorKey(e);
    return key == 'freight.err.already_awarded' ||
        key == 'freight.err.request_not_open' ||
        key == 'freight.err.quote_not_available' ||
        key == 'freight.err.request_expired' ||
        key == 'freight.err.quote_expired';
  }

  Future<void> acceptQuote(Quote q) async {
    final name = q.forwarder?.companyName ?? q.forwarderId;
    final ok = await _confirm(
      title: context.tr('freight.accept.title'),
      body: context.tr('freight.accept.body', {
        'name': name,
        'price': FreightMoney.format(q.amount, q.currency),
        'days': '${q.transitDays}',
      }),
      yes: context.tr('freight.accept.yes'),
      idPrefix: 'freight_accept_dialog',
    );
    if (!ok || !mounted) return;
    await _run(
      () => ref.read(freightRepositoryProvider).acceptQuote(q.id),
      done: context.tr('freight.accept.done'),
    );
  }

  /// Fetches the awarded quote as a landed-cost override and opens the
  /// calculator with the shipment's origin/destination prefilled.
  Future<void> _useInLandedCost(ShipmentRequest r, Quote q) async {
    setState(() {
      _busy = true;
      _actionError = null;
    });
    try {
      final input = await ref.read(freightRepositoryProvider).landedCostInput(q.id);
      if (!mounted) return;
      ref.read(calculatorSeedProvider.notifier).state = CalculatorSeed(
        origin: Location(countryCode: r.originCountry, city: r.originPlace),
        destination: Location(countryCode: r.destinationCountry, city: r.destinationPlace),
        freightOverride: input,
      );
      setState(() => _busy = false);
      context.push('/logistics/calculator');
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _actionError = context.freightError(e);
      });
    }
  }

  Future<void> _close(ShipmentRequest r) async {
    final completing = r.isAwarded;
    final ok = await _confirm(
      title: context.tr(completing ? 'freight.complete.title' : 'freight.cancel.title'),
      body: context.tr(completing ? 'freight.complete.body' : 'freight.cancel.body'),
      yes: context.tr(completing ? 'freight.complete.yes' : 'freight.cancel.yes'),
      idPrefix: 'freight_close_dialog',
    );
    if (!ok || !mounted) return;
    await _run(
      () => ref.read(freightRepositoryProvider).closeRequest(r.id),
      done: context.tr(completing ? 'freight.complete.done' : 'freight.cancel.done'),
    );
  }

  Future<void> _report(String title, Future<void> Function(String, String?) send) async {
    final sent = await showFreightReportSheet(context, title: title, submit: send);
    if (sent && mounted) _snack(context.tr('freight.report.done'));
  }

  Future<void> reportQuote(Quote q) => _report(
        context.tr('freight.report.quote'),
        (reason, details) =>
            ref.read(freightRepositoryProvider).reportQuote(q.id, reason, details: details),
      );

  Future<void> reportForwarder(Quote q) => _report(
        context.tr('freight.report.forwarder'),
        (reason, details) => ref
            .read(freightRepositoryProvider)
            .reportForwarder(q.forwarderId, reason, details: details),
      );

  Future<void> _reportRequest(ShipmentRequest r) => _report(
        context.tr('freight.report.request'),
        (reason, details) =>
            ref.read(freightRepositoryProvider).reportRequest(r.id, reason, details: details),
      );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.tr('freight.detail.title')),
        actions: [
          IconButton(
            key: const ValueKey<String>('freight_refresh'),
            tooltip: context.tr('common.retry'),
            onPressed: () => _reload(),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: FutureBuilder<_Loaded>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(
              child: CircularProgressIndicator(key: ValueKey<String>('freight_detail_loading')),
            );
          }
          if (snap.hasError) {
            return ErrorState(
              key: const ValueKey<String>('freight_detail_error'),
              message: context.freightError(snap.error!),
              error: snap.error,
              onRetry: () => _reload(),
            );
          }
          return _body(context, snap.data!);
        },
      ),
    );
  }

  Widget _body(BuildContext context, _Loaded d) {
    final r = d.request;
    final c = d.comparison;
    Quote? awarded;
    if (c != null) {
      for (final i in c.items) {
        if (i.quote.id == r.awardedQuoteId) awarded = i.quote;
      }
    }
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: [
        if (_actionError != null)
          FreightErrorBox(_actionError!, key: const ValueKey<String>('freight_action_error')),
        FreightRequestSummary(request: r),
        const SizedBox(height: AppSpacing.md),
        if (r.isOpen)
          OutlinedButton.icon(
            key: const ValueKey<String>('freight_cancel_request'),
            style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
            onPressed: _busy ? null : () => _close(r),
            icon: const Icon(Icons.cancel_outlined),
            label: Text(context.tr('freight.cancel.cta')),
          ),
        if (r.isAwarded) ...[
          _AwardedBanner(name: awarded?.forwarder?.companyName),
          const SizedBox(height: AppSpacing.md),
          FilledButton.icon(
            key: const ValueKey<String>('freight_complete_request'),
            style: FilledButton.styleFrom(minimumSize: const Size(64, 48)),
            onPressed: _busy ? null : () => _close(r),
            icon: const Icon(Icons.task_alt),
            label: Text(context.tr('freight.complete.cta')),
          ),
        ],
        if (r.isCompleted && awarded != null) ...[
          const SizedBox(height: AppSpacing.md),
          FreightRateCard(requestId: r.id, forwarderName: awarded.forwarder?.companyName),
        ],
        FreightSectionHeader(
          title: context.tr('freight.quotes_title'),
          actionLabel: context.tr('freight.report.request'),
          onAction: () => _reportRequest(r),
        ),
        if (c == null)
          FreightErrorBox(
            context.freightError(d.comparisonError ?? StateError('no comparison')),
            key: const ValueKey<String>('freight_comparison_error'),
          )
        else
          QuoteComparisonView(
            comparison: c,
            sort: _sort,
            onSort: (s) => setState(() => _sort = s),
            canAccept: r.isOpen && !_busy,
            awardedQuoteId: r.awardedQuoteId,
            onAccept: acceptQuote,
            onReportQuote: reportQuote,
            onReportForwarder: reportForwarder,
            onUseInLandedCost:
                r.isAwarded || r.isCompleted ? (q) => _useInLandedCost(r, q) : null,
          ),
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

class _AwardedBanner extends StatelessWidget {
  const _AwardedBanner({this.name});

  final String? name;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const ValueKey<String>('freight_awarded_banner'),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.success.withOpacity(0.10),
        borderRadius: BorderRadius.circular(AppRadius.sm),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.verified_outlined, color: AppColors.success),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(context.tr('freight.awarded_to', {'name': name ?? '—'})),
          ),
        ],
      ),
    );
  }
}

/// Full request summary (details + deadlines).
class FreightRequestSummary extends StatelessWidget {
  const FreightRequestSummary({super.key, required this.request});

  final ShipmentRequest request;

  @override
  Widget build(BuildContext context) {
    final r = request;
    return AppCard(
      key: const ValueKey<String>('freight_summary'),
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          FreightRouteRow(request: r),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              FreightChip(freightModeName(context, r.mode), icon: freightModeIcon(r.mode)),
              FreightChip(r.incoterm, color: AppColors.accent),
              FreightChip(
                context.tr('freight.status.${r.status}'),
                color: requestStatusColor(r.status),
              ),
              if (r.outcome != null)
                FreightChip(
                  context.tr('freight.outcome.${r.outcome}'),
                  color: const Color(0xFF64748B),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(r.cargoDescription),
          const SizedBox(height: AppSpacing.sm),
          FreightInfoLine(context.tr('freight.form.quantity'), freightQuantityLine(context, r)),
          if (r.hsCode != null) FreightInfoLine(context.tr('freight.form.hs'), r.hsCode!),
          FreightInfoLine(context.tr('freight.ready'), r.readyDate),
          FreightInfoLine(context.tr('freight.form.currency'), r.currency),
          if (r.expiresAt != null)
            FreightInfoLine(context.tr('freight.expires'), formatDate(context, r.expiresAt)),
          FreightInfoLine(
            context.tr('freight.quotes_title'),
            context.tr('freight.quotes_count', {'n': '${r.quoteCount}'}),
          ),
        ],
      ),
    );
  }
}

/// Rate the awarded forwarder after completion (once per request).
class FreightRateCard extends ConsumerStatefulWidget {
  const FreightRateCard({super.key, required this.requestId, this.forwarderName});

  final String requestId;
  final String? forwarderName;

  @override
  ConsumerState<FreightRateCard> createState() => _FreightRateCardState();
}

class _FreightRateCardState extends ConsumerState<FreightRateCard> {
  final TextEditingController _comment = TextEditingController();
  int _stars = 0;
  bool _busy = false;
  bool _done = false;
  String? _error;

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (_stars < 1) {
      setState(() => _error = context.tr('freight.rate.pick'));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(freightRepositoryProvider)
          .rateForwarder(widget.requestId, _stars, comment: _comment.text);
      ref.read(freightRefreshProvider.notifier).state++;
      if (mounted) {
        setState(() {
          _busy = false;
          _done = true;
        });
      }
    } catch (e) {
      if (!mounted) return;
      final already = freightErrorKey(e) == 'freight.err.already_rated';
      setState(() {
        _busy = false;
        _done = already;
        _error = already ? null : context.freightError(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_done) {
      return AppCard(
        key: const ValueKey<String>('freight_rate_done'),
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Row(
          children: [
            const Icon(Icons.star_rounded, color: AppColors.warning),
            const SizedBox(width: AppSpacing.sm),
            Expanded(child: Text(context.tr('freight.rate.thanks'))),
          ],
        ),
      );
    }
    return AppCard(
      key: const ValueKey<String>('freight_rate_card'),
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.tr('freight.rate.title', {'name': widget.forwarderName ?? '—'}),
            style: const TextStyle(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            children: [
              for (var i = 1; i <= 5; i++)
                IconButton(
                  key: ValueKey<String>('freight_star_$i'),
                  tooltip: context.tr('freight.rate.star', {'n': '$i'}),
                  onPressed: _busy ? null : () => setState(() => _stars = i),
                  icon: Icon(
                    i <= _stars ? Icons.star_rounded : Icons.star_border_rounded,
                    color: AppColors.warning,
                    size: 32,
                  ),
                ),
            ],
          ),
          TextField(
            key: const ValueKey<String>('freight_rate_comment'),
            controller: _comment,
            maxLength: 500,
            maxLines: 3,
            minLines: 1,
            decoration: InputDecoration(labelText: context.tr('freight.rate.comment')),
          ),
          if (_error != null) FreightErrorBox(_error!, key: const ValueKey<String>('freight_rate_error')),
          const SizedBox(height: AppSpacing.sm),
          PrimaryButton(
            key: const ValueKey<String>('freight_rate_submit'),
            label: context.tr('freight.rate.send'),
            loading: _busy,
            onPressed: submit,
          ),
        ],
      ),
    );
  }
}
