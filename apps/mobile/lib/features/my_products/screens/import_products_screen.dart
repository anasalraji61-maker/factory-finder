import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/my_products/import/import_logic.dart';
import 'package:factory_finder/features/my_products/my_products_logic.dart';
import 'package:factory_finder/features/my_products/my_products_repository.dart';
import 'package:factory_finder/features/my_products/screens/my_products_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Supplier bulk import: paste CSV, validate per row, dry run, then import.
class ImportProductsScreen extends ConsumerStatefulWidget {
  const ImportProductsScreen({super.key});

  @override
  ConsumerState<ImportProductsScreen> createState() => _ImportProductsScreenState();
}

class _ImportProductsScreenState extends ConsumerState<ImportProductsScreen> {
  final TextEditingController _text = TextEditingController();
  ImportParseResult? _parsed;
  ImportRunResult? _result;
  String? _runErrorKey;
  bool _busy = false;
  int _progressDone = 0;
  int _progressTotal = 0;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    setState(() {
      _parsed = value.trim().isEmpty ? null : parseListingCsv(value);
      _result = null;
      _runErrorKey = null;
    });
  }

  Future<void> _run({required bool dryRun}) async {
    final parsed = _parsed;
    if (parsed == null || parsed.validRows.isEmpty || _busy) return;
    final repo = ref.read(myListingsRepositoryProvider);
    setState(() {
      _busy = true;
      _result = null;
      _runErrorKey = null;
      _progressDone = 0;
      _progressTotal = parsed.batchCount;
    });
    final res = await runImportBatches(
      parsed.rows,
      (items, dry) => repo.importListings(items, dryRun: dry),
      dryRun: dryRun,
      onProgress: (done, total) {
        if (mounted) setState(() => _progressDone = done);
      },
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      _result = res;
      final err = res.error;
      _runErrorKey = err == null ? null : myProductsErrorKey(err);
    });
  }

  @override
  Widget build(BuildContext context) {
    final me = ref.watch(authProvider);
    final open = isVerifiedSupplier(me) || ref.watch(myProductsBypassGateProvider);
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('myp.imp.title'))),
      body: open
          ? _buildBody(context)
          : EmptyState(
              icon: Icons.lock_outline,
              title: context.tr('myp.err.supplier_required'),
            ),
    );
  }

  Widget _buildBody(BuildContext context) {
    final parsed = _parsed;
    final result = _result;
    final children = <Widget>[
      Text(
        context.tr('myp.imp.help'),
        key: const ValueKey<String>('imp-help'),
        style: const TextStyle(color: AppColors.textSecondary),
      ),
      const SizedBox(height: AppSpacing.md),
      TextField(
        key: const ValueKey<String>('imp-text'),
        controller: _text,
        minLines: 6,
        maxLines: 12,
        keyboardType: TextInputType.multiline,
        enabled: !_busy,
        onChanged: _onChanged,
        decoration: InputDecoration(
          hintText: context.tr('myp.imp.hint'),
          border: const OutlineInputBorder(),
        ),
      ),
      const SizedBox(height: AppSpacing.md),
    ];

    if (parsed != null && parsed.errorKey != null) {
      children.add(Text(
        context.tr(parsed.errorKey!, <String, String>{'cols': parsed.missingColumns.join(', ')}),
        key: const ValueKey<String>('imp-parse-error'),
        style: const TextStyle(color: AppColors.danger, fontWeight: FontWeight.w700),
      ));
    } else if (parsed != null) {
      final valid = parsed.validRows.length;
      children.add(Text(
        context.tr('myp.imp.rows', <String, String>{
          'total': '${parsed.rows.length}',
          'valid': '$valid',
          'invalid': '${parsed.rows.length - valid}',
        }),
        key: const ValueKey<String>('imp-counts'),
        style: const TextStyle(fontWeight: FontWeight.w700),
      ));
      if (valid > kImportBatchSize) {
        children.add(Padding(
          padding: const EdgeInsets.only(top: AppSpacing.sm),
          child: Text(
            context.tr('myp.imp.batches', <String, String>{
              'valid': '$valid',
              'n': '${parsed.batchCount}',
            }),
            key: const ValueKey<String>('imp-batches'),
          ),
        ));
      }
      children.add(const SizedBox(height: AppSpacing.md));
      children.add(Row(
        children: [
          Expanded(
            child: OutlinedButton(
              key: const ValueKey<String>('imp-dry'),
              onPressed: _busy || valid == 0 ? null : () => _run(dryRun: true),
              child: Text(context.tr('myp.imp.dry')),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: PrimaryButton(
              key: const ValueKey<String>('imp-run'),
              label: context.tr('myp.imp.run'),
              icon: Icons.upload_file_outlined,
              loading: _busy,
              onPressed: valid == 0 ? null : () => _run(dryRun: false),
            ),
          ),
        ],
      ));
    }

    if (_busy && _progressTotal > 1) {
      children.add(Padding(
        padding: const EdgeInsets.only(top: AppSpacing.md),
        child: Text(
          context.tr('myp.imp.progress', <String, String>{
            'done': '$_progressDone',
            'total': '$_progressTotal',
          }),
          key: const ValueKey<String>('imp-progress'),
        ),
      ));
    }

    if (result != null) {
      children.add(const SizedBox(height: AppSpacing.md));
      children.add(Text(
        context.tr(
          result.dryRun ? 'myp.imp.summary.dry' : 'myp.imp.summary.run',
          <String, String>{
            'created': '${result.created}',
            'updated': '${result.updated}',
            'rejected': '${result.rejected}',
            'invalid': '${result.invalid}',
          },
        ),
        key: const ValueKey<String>('imp-summary'),
        style: const TextStyle(fontWeight: FontWeight.w800),
      ));
      final errKey = _runErrorKey;
      if (errKey != null) {
        final partial = context.tr('myp.imp.partial', <String, String>{
          'done': '${result.batchesDone}',
          'total': '${result.batches}',
        });
        children.add(Padding(
          padding: const EdgeInsets.only(top: AppSpacing.sm),
          child: Text(
            '$partial ${context.tr(errKey)}',
            key: const ValueKey<String>('imp-run-error'),
            style: const TextStyle(color: AppColors.danger),
          ),
        ));
      }
    }

    final outcomes = result != null
        ? result.outcomes
        : (parsed == null ? const <ImportOutcome>[] : invalidOutcomes(parsed.rows));
    final dry = result?.dryRun ?? false;
    for (final o in outcomes) {
      children.add(_OutcomeTile(outcome: o, dryRun: dry));
    }

    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: children,
    );
  }
}

class _OutcomeTile extends StatelessWidget {
  const _OutcomeTile({required this.outcome, required this.dryRun});

  final ImportOutcome outcome;
  final bool dryRun;

  String _actionKey() {
    switch (outcome.action) {
      case 'created':
        return dryRun ? 'myp.imp.act.created_dry' : 'myp.imp.act.created';
      case 'updated':
        return dryRun ? 'myp.imp.act.updated_dry' : 'myp.imp.act.updated';
      case 'rejected':
        return 'myp.imp.act.rejected';
      default:
        return 'myp.imp.act.invalid';
    }
  }

  Color _color() {
    switch (outcome.action) {
      case 'created':
      case 'updated':
        return AppColors.success;
      default:
        return AppColors.danger;
    }
  }

  String _reasonKey(String reason) {
    switch (reason) {
      case 'validation_error':
      case 'invalid_item':
      case 'duplicate_in_batch':
      case 'listing_cap_reached':
      case 'conflict':
        return 'myp.imp.reason.$reason';
    }
    return 'myp.imp.reason.unknown';
  }

  @override
  Widget build(BuildContext context) {
    final lines = <Widget>[];
    final reason = outcome.reason;
    if (reason != null) {
      lines.add(Text(
        context.tr(_reasonKey(reason)),
        key: ValueKey<String>('imp-reason-${outcome.rowNumber}'),
      ));
    }
    final message = outcome.message;
    if (message != null) {
      lines.add(Text(message, style: const TextStyle(color: AppColors.textSecondary)));
    }
    for (final e in outcome.errors) {
      lines.add(Text('${e.column}: ${context.tr(e.key)}'));
    }
    final ref = outcome.externalRef.isEmpty ? '-' : outcome.externalRef;
    final rowLabel = context.tr('myp.imp.row', <String, String>{'n': '${outcome.rowNumber}'});
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.sm),
      child: AppCard(
        key: ValueKey<String>('imp-row-${outcome.rowNumber}'),
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '$rowLabel - $ref',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                Text(
                  context.tr(_actionKey()),
                  key: ValueKey<String>('imp-status-${outcome.rowNumber}'),
                  style: TextStyle(color: _color(), fontWeight: FontWeight.w800),
                ),
              ],
            ),
            ...lines,
          ],
        ),
      ),
    );
  }
}
