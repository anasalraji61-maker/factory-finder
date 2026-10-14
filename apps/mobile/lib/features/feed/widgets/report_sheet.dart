import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/feed/feed_logic.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:factory_finder/features/feed/widgets/feed_common.dart';
import 'package:flutter/material.dart';

/// Bottom sheet to pick a report reason (+ optional details). [onSubmit] does
/// the request; failures are shown inside the sheet. Returns true when sent.
Future<bool> showFeedReportSheet(
  BuildContext context, {
  required Future<void> Function(ReportReason reason, String? details) onSubmit,
}) async {
  final sent = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => FeedReportSheet(onSubmit: onSubmit),
  );
  return sent ?? false;
}

class FeedReportSheet extends StatefulWidget {
  const FeedReportSheet({super.key, required this.onSubmit});

  final Future<void> Function(ReportReason reason, String? details) onSubmit;

  @override
  State<FeedReportSheet> createState() => _FeedReportSheetState();
}

class _FeedReportSheetState extends State<FeedReportSheet> {
  ReportReason? _reason;
  final TextEditingController _details = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _details.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final reason = _reason;
    if (reason == null || _busy) return;
    final problem = validateReportDetails(_details.text);
    if (problem != null) {
      setState(() => _error = context.tr(problem));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final d = _details.text.trim();
      await widget.onSubmit(reason, d.isEmpty ? null : d);
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = feedErrorMessage(context, e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg + MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              context.tr('feed.report.title'),
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: AppSpacing.md),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final r in ReportReason.values)
                  ChoiceChip(
                    key: ValueKey<String>('feed-report-${r.json}'),
                    label: Text(context.tr('feed.report.reason.${r.json}')),
                    selected: _reason == r,
                    onSelected: _busy ? null : (_) => setState(() => _reason = r),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            TextField(
              key: const ValueKey<String>('feed-report-details'),
              controller: _details,
              enabled: !_busy,
              maxLength: kReportDetailsMax,
              maxLines: 3,
              minLines: 2,
              decoration: InputDecoration(hintText: context.tr('feed.report.details_hint')),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Text(
                  _error!,
                  key: const ValueKey<String>('feed-report-error'),
                  style: TextStyle(color: theme.colorScheme.error),
                ),
              ),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                key: const ValueKey<String>('feed-report-send'),
                style: FilledButton.styleFrom(minimumSize: const Size(64, 50)),
                onPressed: (_reason == null || _busy) ? null : _send,
                child: _busy
                    ? const SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(strokeWidth: 2.5),
                      )
                    : Text(context.tr('feed.report.send')),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
