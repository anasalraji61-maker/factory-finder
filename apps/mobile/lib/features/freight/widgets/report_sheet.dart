import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/freight/data/freight_errors.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart';
import 'package:flutter/material.dart';

/// Bottom sheet to report abuse (a request, a quote or a forwarder).
/// [submit] performs the API call; the sheet maps failures to localized text
/// and closes with `true` on success.
Future<bool> showFreightReportSheet(
  BuildContext context, {
  required String title,
  required Future<void> Function(String reason, String? details) submit,
}) async {
  final done = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (ctx) => _ReportSheet(title: title, submit: submit),
  );
  return done == true;
}

class _ReportSheet extends StatefulWidget {
  const _ReportSheet({required this.title, required this.submit});

  final String title;
  final Future<void> Function(String reason, String? details) submit;

  @override
  State<_ReportSheet> createState() => _ReportSheetState();
}

class _ReportSheetState extends State<_ReportSheet> {
  final TextEditingController _details = TextEditingController();
  String? _reason;
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _details.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final reason = _reason;
    if (reason == null) {
      setState(() => _error = context.tr('freight.report.pick_reason'));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final d = _details.text.trim();
      await widget.submit(reason, d.isEmpty ? null : d);
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = context.freightError(e);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;
    return SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg + bottom),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            widget.title,
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(context.tr('freight.report.hint')),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final r in kReportReasons)
                ChoiceChip(
                  key: ValueKey<String>('freight_reason_$r'),
                  label: Text(context.tr('freight.reason.$r')),
                  selected: _reason == r,
                  onSelected: _busy ? null : (_) => setState(() => _reason = r),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          TextField(
            key: const ValueKey<String>('freight_report_details'),
            controller: _details,
            maxLength: 300,
            maxLines: 3,
            decoration: InputDecoration(labelText: context.tr('freight.report.details')),
          ),
          if (_error != null) FreightErrorBox(_error!),
          const SizedBox(height: AppSpacing.sm),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              key: const ValueKey<String>('freight_report_submit'),
              style: FilledButton.styleFrom(minimumSize: const Size(64, 48)),
              onPressed: _busy ? null : _send,
              child: Text(context.tr('freight.report.send')),
            ),
          ),
        ],
      ),
    );
  }
}
