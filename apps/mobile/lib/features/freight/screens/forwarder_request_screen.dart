import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/utils/number_format.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/data/freight_decimal.dart';
import 'package:factory_finder/features/freight/data/freight_drafts.dart';
import 'package:factory_finder/features/freight/data/freight_errors.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/freight/screens/request_detail_screen.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart';
import 'package:factory_finder/features/freight/widgets/report_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class _QuoteContext {
  const _QuoteContext(this.request, this.existing);

  final ShipmentRequest request;
  final Quote? existing;
}

class _LineControllers {
  _LineControllers(this.id, {String label = '', String amount = ''})
      : label = TextEditingController(text: label),
        amount = TextEditingController(text: amount);

  final int id;
  final TextEditingController label;
  final TextEditingController amount;

  void dispose() {
    label.dispose();
    amount.dispose();
  }
}

/// Forwarder view of a matching request: summary + submit / revise /
/// withdraw the forwarder's single quote. The currency is fixed to the
/// request currency and breakdown lines must add up to the total exactly.
class ForwarderRequestScreen extends ConsumerStatefulWidget {
  const ForwarderRequestScreen({super.key, required this.requestId});

  final String requestId;

  @override
  ConsumerState<ForwarderRequestScreen> createState() => _ForwarderRequestScreenState();
}

class _ForwarderRequestScreenState extends ConsumerState<ForwarderRequestScreen> {
  final GlobalKey<FormState> _form = GlobalKey<FormState>();
  final TextEditingController _amount = TextEditingController();
  final TextEditingController _transit = TextEditingController();
  final TextEditingController _validDays = TextEditingController(text: '14');
  final TextEditingController _inclusions = TextEditingController();
  final TextEditingController _exclusions = TextEditingController();
  final TextEditingController _terms = TextEditingController();
  final List<_LineControllers> _lines = [];

  /// Controllers of removed rows; disposed with the screen because their
  /// widgets may still be mounted for one more frame.
  final List<_LineControllers> _retired = [];
  int _lineSeq = 0;
  late Future<_QuoteContext> _future;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _future = _fetch();
  }

  @override
  void dispose() {
    for (final c in [_amount, _transit, _validDays, _inclusions, _exclusions, _terms]) {
      c.dispose();
    }
    for (final l in [..._lines, ..._retired]) {
      l.dispose();
    }
    super.dispose();
  }

  Future<_QuoteContext> _fetch({bool refill = true}) async {
    final repo = ref.read(freightRepositoryProvider);
    final r = await repo.getRequest(widget.requestId);
    final q = await findMyQuoteForRequest(repo, widget.requestId);
    if (refill) _fill(q);
    return _QuoteContext(r, q);
  }

  void _fill(Quote? q) {
    _retired.addAll(_lines);
    _lines.clear();
    if (q == null) return;
    _amount.text = q.amount;
    _transit.text = '${q.transitDays}';
    _inclusions.text = q.inclusions.join('\n');
    _exclusions.text = q.exclusions.join('\n');
    _terms.text = q.terms ?? '';
    for (final l in q.breakdown) {
      _lines.add(_LineControllers(_lineSeq++, label: l.label, amount: l.amount));
    }
  }

  void _reload() {
    setState(() {
      _error = null;
      _future = _fetch();
    });
  }

  List<String> _split(String raw) => [
        for (final p in raw.split('\n'))
          if (p.trim().isNotEmpty) p.trim(),
      ];

  QuoteDraft _draft(String currency) => QuoteDraft(
        amount: _amount.text,
        currency: currency,
        transitDays: int.tryParse(FreightDecimal.normalize(_transit.text) ?? '') ?? 0,
        validDays: int.tryParse(FreightDecimal.normalize(_validDays.text) ?? '') ?? 0,
        inclusions: _split(_inclusions.text),
        exclusions: _split(_exclusions.text),
        breakdown: [
          for (final l in _lines)
            if (l.label.text.trim().isNotEmpty || l.amount.text.trim().isNotEmpty)
              QuoteLine(label: l.label.text, amount: l.amount.text.trim()),
        ],
        terms: _terms.text,
      );

  void _snack(String text) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> submit(_QuoteContext ctx) async {
    setState(() => _error = null);
    if (!(_form.currentState?.validate() ?? false)) return;
    final draft = _draft(ctx.request.currency);
    final invalid = draft.validate();
    if (invalid != null) {
      setState(() => _error = context.tr(invalid));
      return;
    }
    await _call(
      () async {
        final repo = ref.read(freightRepositoryProvider);
        if (ctx.existing == null) {
          await repo.submitQuote(ctx.request.id, draft);
        } else {
          await repo.reviseQuote(ctx.existing!.id, draft);
        }
      },
      done: context.tr(ctx.existing == null ? 'freight.quote.sent' : 'freight.quote.revised'),
    );
  }

  Future<void> withdraw(_QuoteContext ctx) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx2) => AlertDialog(
        title: Text(ctx2.tr('freight.withdraw.title')),
        content: Text(ctx2.tr('freight.withdraw.body')),
        actions: [
          TextButton(
            key: const ValueKey<String>('freight_withdraw_cancel'),
            onPressed: () => Navigator.of(ctx2).pop(false),
            child: Text(ctx2.tr('common.cancel')),
          ),
          FilledButton(
            key: const ValueKey<String>('freight_withdraw_confirm'),
            onPressed: () => Navigator.of(ctx2).pop(true),
            child: Text(ctx2.tr('freight.withdraw.yes')),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await _call(
      () async {
        await ref.read(freightRepositoryProvider).withdrawQuote(ctx.existing!.id);
      },
      done: context.tr('freight.quote.withdrawn'),
    );
  }

  Future<void> _call(Future<void> Function() action, {required String done}) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
      ref.read(freightRefreshProvider.notifier).state++;
      if (!mounted) return;
      _snack(done);
      setState(() {
        _busy = false;
        _future = _fetch();
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = context.freightError(e);
        // The quote / request changed under us (e.g. quote_exists after a
        // double submit): re-read it so the button flips to "revise" or the
        // form locks, but keep what the user typed.
        if (_isStale(e)) _future = _fetch(refill: false);
      });
    }
  }

  bool _isStale(Object e) {
    const stale = {
      'freight.err.quote_exists',
      'freight.err.quote_changed',
      'freight.err.state_changed',
      'freight.err.quote_final',
      'freight.err.quote_expired',
      'freight.err.request_expired',
      'freight.err.request_not_open',
    };
    return stale.contains(freightErrorKey(e));
  }

  Future<void> _report(ShipmentRequest r) async {
    final sent = await showFreightReportSheet(
      context,
      title: context.tr('freight.report.request'),
      submit: (reason, details) =>
          ref.read(freightRepositoryProvider).reportRequest(r.id, reason, details: details),
    );
    if (sent && mounted) _snack(context.tr('freight.report.done'));
  }

  String? _val(String? Function() check) {
    final k = check();
    return k == null ? null : context.tr(k);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.tr('freight.quote.title')),
        actions: [
          FutureBuilder<_QuoteContext>(
            future: _future,
            builder: (context, snap) {
              final r = snap.data?.request;
              if (r == null) return const SizedBox.shrink();
              return IconButton(
                key: const ValueKey<String>('freight_report_request'),
                tooltip: context.tr('freight.report.request'),
                onPressed: () => _report(r),
                icon: const Icon(Icons.flag_outlined),
              );
            },
          ),
        ],
      ),
      body: FutureBuilder<_QuoteContext>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(
              child: CircularProgressIndicator(key: ValueKey<String>('freight_quote_loading')),
            );
          }
          if (snap.hasError) {
            return ErrorState(
              key: const ValueKey<String>('freight_quote_load_error'),
              message: context.freightError(snap.error!),
              error: snap.error,
              onRetry: _reload,
            );
          }
          return _buildForm(context, snap.data!);
        },
      ),
    );
  }

  Widget _buildForm(BuildContext context, _QuoteContext ctx) {
    final r = ctx.request;
    final q = ctx.existing;
    final editable = r.isOpen && (q == null || q.isSubmitted || q.isWithdrawn);
    final amountUnits = FreightDecimal.parseScaled(_amount.text, 2);
    final lineUnits = _lines.isEmpty
        ? null
        : FreightDecimal.sumScaled(
            [
              for (final l in _lines)
                if (l.amount.text.trim().isNotEmpty) l.amount.text,
            ],
            2,
          );
    final mismatch = _lines.isNotEmpty && lineUnits != amountUnits;
    return Form(
      key: _form,
      child: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          FreightRequestSummary(request: r),
          const SizedBox(height: AppSpacing.md),
          if (q != null)
            AppCard(
              key: const ValueKey<String>('freight_existing_quote'),
              padding: const EdgeInsets.all(AppSpacing.md),
              child: Wrap(
                spacing: 8,
                runSpacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(context.tr('freight.quote.yours')),
                  FreightMoney(q.amount, q.currency),
                  FreightChip(
                    context.tr('freight.qstatus.${q.status}'),
                    color: quoteStatusColor(q.status),
                  ),
                  Text(context.tr('freight.revision', {'n': '${q.revision}'})),
                ],
              ),
            ),
          if (!editable)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.md),
              child: FreightErrorBox(
                context.tr(r.isOpen ? 'freight.quote.final' : 'freight.quote.closed'),
                key: const ValueKey<String>('freight_quote_locked'),
              ),
            )
          else ...[
            const SizedBox(height: AppSpacing.md),
            if (_error != null)
              FreightErrorBox(_error!, key: const ValueKey<String>('freight_quote_error')),
            TextFormField(
              key: const ValueKey<String>('freight_quote_amount'),
              controller: _amount,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9٠-٩۰-۹.,٫]')),
              ],
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(
                labelText: context.tr('freight.quote.amount'),
                suffixText: r.currency,
              ),
              validator: (v) => _val(() => FreightValidators.amount(v ?? '')),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('freight_quote_currency'),
              initialValue: r.currency,
              enabled: false,
              decoration: InputDecoration(
                labelText: context.tr('freight.form.currency'),
                helperText: context.tr('freight.quote.currency_fixed'),
                helperMaxLines: 2,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('freight_quote_transit'),
              controller: _transit,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(labelText: context.tr('freight.quote.transit_days')),
              validator: (v) =>
                  _val(() => FreightValidators.intRange(v ?? '', 1, 365, 'freight.v.transit')),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('freight_quote_valid_days'),
              controller: _validDays,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(labelText: context.tr('freight.quote.valid_days')),
              validator: (v) =>
                  _val(() => FreightValidators.intRange(v ?? '', 1, 90, 'freight.v.valid_days')),
            ),
            SectionHeader(title: context.tr('freight.breakdown')),
            Text(
              context.tr('freight.quote.breakdown_hint'),
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: AppColors.secondaryOf(context)),
            ),
            const SizedBox(height: AppSpacing.sm),
            for (final l in _lines)
              Padding(
                key: ValueKey<String>('freight_line_${l.id}'),
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    TextFormField(
                      key: ValueKey<String>('freight_line_label_${l.id}'),
                      controller: l.label,
                      maxLength: 60,
                      decoration: InputDecoration(labelText: context.tr('freight.quote.line_label')),
                    ),
                    TextFormField(
                      key: ValueKey<String>('freight_line_amount_${l.id}'),
                      controller: l.amount,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      onChanged: (_) => setState(() {}),
                      decoration: InputDecoration(
                        labelText: context.tr('freight.quote.line_amount'),
                        suffixText: r.currency,
                      ),
                    ),
                    Align(
                      alignment: AlignmentDirectional.centerEnd,
                      child: TextButton.icon(
                        key: ValueKey<String>('freight_line_remove_${l.id}'),
                        onPressed: () => setState(() {
                          _lines.remove(l);
                          _retired.add(l);
                        }),
                        icon: const Icon(Icons.delete_outline),
                        label: Text(context.tr('freight.quote.remove_line')),
                      ),
                    ),
                  ],
                ),
              ),
            if (_lines.length < 10)
              OutlinedButton.icon(
                key: const ValueKey<String>('freight_line_add'),
                style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
                onPressed: () => setState(() => _lines.add(_LineControllers(_lineSeq++))),
                icon: const Icon(Icons.add),
                label: Text(context.tr('freight.quote.add_line')),
              ),
            if (_lines.isNotEmpty)
              Padding(
                key: const ValueKey<String>('freight_breakdown_sum'),
                padding: const EdgeInsets.only(top: AppSpacing.sm),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      mismatch ? Icons.warning_amber_rounded : Icons.check_circle_outline,
                      size: 18,
                      color: mismatch ? AppColors.warning : AppColors.success,
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        context.tr(
                          mismatch ? 'freight.quote.sum_mismatch' : 'freight.quote.sum_ok',
                          {
                            'lines': lineUnits == null
                                ? '?'
                                : isolateLtr(FreightMoney.format(
                                    FreightDecimal.formatScaled(lineUnits, 2), r.currency)),
                            'total': amountUnits == null
                                ? '?'
                                : isolateLtr(FreightMoney.format(
                                    FreightDecimal.formatScaled(amountUnits, 2), r.currency)),
                          },
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            SectionHeader(title: context.tr('freight.quote.details')),
            TextFormField(
              key: const ValueKey<String>('freight_quote_inclusions'),
              controller: _inclusions,
              minLines: 2,
              maxLines: 5,
              decoration: InputDecoration(
                labelText: context.tr('freight.inclusions'),
                helperText: context.tr('freight.quote.one_per_line'),
                helperMaxLines: 2,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('freight_quote_exclusions'),
              controller: _exclusions,
              minLines: 2,
              maxLines: 5,
              decoration: InputDecoration(
                labelText: context.tr('freight.exclusions'),
                helperText: context.tr('freight.quote.one_per_line'),
                helperMaxLines: 2,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('freight_quote_terms'),
              controller: _terms,
              maxLength: 1000,
              minLines: 2,
              maxLines: 5,
              decoration: InputDecoration(
                labelText: context.tr('freight.terms'),
                helperText: context.tr('freight.form.no_contacts'),
                helperMaxLines: 2,
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              key: const ValueKey<String>('freight_quote_submit'),
              label: context.tr(q == null
                  ? 'freight.quote.submit'
                  : q.isWithdrawn
                      ? 'freight.quote.revive'
                      : 'freight.quote.revise'),
              icon: Icons.send_outlined,
              loading: _busy,
              onPressed: () => submit(ctx),
            ),
            if (q != null && q.isSubmitted) ...[
              const SizedBox(height: AppSpacing.md),
              OutlinedButton.icon(
                key: const ValueKey<String>('freight_quote_withdraw'),
                style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
                onPressed: _busy ? null : () => withdraw(ctx),
                icon: const Icon(Icons.undo),
                label: Text(context.tr('freight.withdraw.cta')),
              ),
            ],
          ],
          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }
}
