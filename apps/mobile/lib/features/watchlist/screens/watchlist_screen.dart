import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/watchlist/data/watch_models.dart';
import 'package:factory_finder/features/watchlist/data/watch_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Result of the price-threshold sheet. Both fields are optional.
class WatchDraft {
  const WatchDraft({this.targetPrice, this.dropPct});
  final Money? targetPrice;
  final String? dropPct;
}

/// Returns an error key, or null when [v] is empty or a positive decimal.
String? validateTargetPrice(String v) {
  final t = v.trim();
  if (t.isEmpty) return null;
  final n = double.tryParse(t);
  if (n == null || n <= 0) return 'watch.err.target';
  return null;
}

/// Returns an error key, or null when [v] is empty or in (0, 100].
String? validateDropPct(String v) {
  final t = v.trim();
  if (t.isEmpty) return null;
  final n = double.tryParse(t);
  if (n == null || n <= 0 || n > 100) return 'watch.err.pct';
  return null;
}

/// Shows the optional threshold sheet; null when dismissed.
Future<WatchDraft?> showWatchSheet(
  BuildContext context, {
  required String currency,
  String? initialTarget,
}) {
  return showModalBottomSheet<WatchDraft>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _WatchSheet(currency: currency, initialTarget: initialTarget),
  );
}

class _WatchSheet extends StatefulWidget {
  const _WatchSheet({required this.currency, this.initialTarget});
  final String currency;
  final String? initialTarget;

  @override
  State<_WatchSheet> createState() => _WatchSheetState();
}

class _WatchSheetState extends State<_WatchSheet> {
  late final TextEditingController _target =
      TextEditingController(text: widget.initialTarget ?? '');
  final TextEditingController _pct = TextEditingController();
  String? _targetErr;
  String? _pctErr;

  @override
  void dispose() {
    _target.dispose();
    _pct.dispose();
    super.dispose();
  }

  void _submit() {
    final te = validateTargetPrice(_target.text);
    final pe = validateDropPct(_pct.text);
    if (te != null || pe != null) {
      setState(() {
        _targetErr = te;
        _pctErr = pe;
      });
      return;
    }
    final t = _target.text.trim();
    final p = _pct.text.trim();
    Navigator.of(context).pop(WatchDraft(
      targetPrice: t.isEmpty ? null : Money(amount: t, currency: widget.currency),
      dropPct: p.isEmpty ? null : p,
    ));
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                context.tr('watch.sheet_title'),
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 4),
              Text(
                context.tr('watch.sheet_hint'),
                style: const TextStyle(color: AppColors.textSecondary),
              ),
              const SizedBox(height: AppSpacing.md),
              TextField(
                controller: _target,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                textDirection: TextDirection.ltr,
                decoration: InputDecoration(
                  labelText: context.tr('watch.target_price', {'currency': widget.currency}),
                  errorText: _targetErr == null ? null : context.tr(_targetErr!),
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              TextField(
                controller: _pct,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                textDirection: TextDirection.ltr,
                decoration: InputDecoration(
                  labelText: context.tr('watch.drop_pct'),
                  hintText: '5',
                  errorText: _pctErr == null ? null : context.tr(_pctErr!),
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              PrimaryButton(
                label: context.tr('watch.confirm'),
                icon: Icons.star,
                onPressed: _submit,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class WatchlistScreen extends ConsumerWidget {
  const WatchlistScreen({super.key});

  Future<void> _remove(BuildContext context, WidgetRef ref, WatchItem w) async {
    final messenger = ScaffoldMessenger.of(context);
    final okText = context.tr('watch.removed');
    final failText = context.tr('watch.failed');
    try {
      await ref.read(watchlistRepositoryProvider).remove(w.id);
      ref.invalidate(watchlistProvider);
      messenger.showSnackBar(SnackBar(content: Text(okText)));
    } catch (_) {
      messenger.showSnackBar(SnackBar(content: Text(failText)));
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(watchlistProvider);
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('watch.title'))),
      body: async.when(
        loading: () => const LoadingList(),
        error: (e, _) => ErrorState(
          error: e,
          onRetry: () => ref.invalidate(watchlistProvider),
        ),
        data: (list) {
          Future<void> refresh() async {
            ref.invalidate(watchlistProvider);
            await ref.read(watchlistProvider.future);
          }

          if (list.isEmpty) {
            // Scrollable so pull-to-refresh also works on the empty state.
            return RefreshIndicator(
              onRefresh: refresh,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  SizedBox(
                    height: 420,
                    child: EmptyState(
                      icon: Icons.star_border,
                      title: context.tr('watch.empty_title'),
                      message: context.tr('watch.empty_msg'),
                    ),
                  ),
                ],
              ),
            );
          }
          return RefreshIndicator(
            onRefresh: refresh,
            child: ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(AppSpacing.lg),
              itemCount: list.length,
              separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
              itemBuilder: (context, i) => _WatchCard(
                item: list[i],
                onRemove: () => _remove(context, ref, list[i]),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _WatchCard extends StatelessWidget {
  const _WatchCard({required this.item, required this.onRemove});
  final WatchItem item;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final lang = Localizations.localeOf(context).languageCode;
    final w = item;
    final reached = w.reachedTarget;
    final title = w.type == 'search' && (w.title == null || w.title!.isEmpty)
        ? context.tr('watch.search_watch')
        : w.displayTitle(lang);
    return AppCard(
      onTap: w.isListing ? () => context.push('/listing/${w.listingId}') : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              IconButton(
                tooltip: context.tr('watch.remove'),
                icon: const Icon(Icons.delete_outline),
                onPressed: onRemove,
              ),
            ],
          ),
          Row(
            children: [
              Expanded(
                child: _kv(
                  context,
                  context.tr('watch.current'),
                  w.currentPrice == null
                      ? Text(context.tr('watch.no_price'))
                      : MoneyText(
                          w.currentPrice!,
                          style: TextStyle(
                            fontWeight: FontWeight.w900,
                            fontSize: 16,
                            color: reached ? AppColors.success : null,
                          ),
                        ),
                ),
              ),
              if (w.targetPrice != null)
                Expanded(
                  child: _kv(context, context.tr('watch.target'),
                      MoneyText(w.targetPrice!)),
                ),
              if (w.baselinePrice != null && w.targetPrice == null)
                Expanded(
                  child: _kv(context, context.tr('watch.baseline'),
                      MoneyText(w.baselinePrice!)),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: 4,
            children: [
              Chip(
                visualDensity: VisualDensity.compact,
                label: Text(context.tr('watch.threshold', {'pct': w.dropThresholdPct})),
              ),
              if (reached)
                Chip(
                  visualDensity: VisualDensity.compact,
                  label: Text(context.tr('watch.target_reached')),
                ),
              if (w.available == false)
                Chip(
                  visualDensity: VisualDensity.compact,
                  label: Text(context.tr('watch.unavailable')),
                ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _kv(BuildContext context, String label, Widget value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: Theme.of(context)
              .textTheme
              .bodySmall
              ?.copyWith(color: AppColors.textSecondary),
        ),
        value,
      ],
    );
  }
}
