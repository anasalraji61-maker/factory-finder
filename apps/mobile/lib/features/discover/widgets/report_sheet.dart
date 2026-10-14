import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/data/listing_report.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Opens the report sheet; resolves true when the report was accepted (202).
Future<bool> showReportListingSheet(BuildContext context, String listingId) async {
  final ok = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => ReportListingSheet(listingId: listingId),
  );
  return ok == true;
}

class ReportListingSheet extends ConsumerStatefulWidget {
  const ReportListingSheet({super.key, required this.listingId});
  final String listingId;

  @override
  ConsumerState<ReportListingSheet> createState() => _ReportListingSheetState();
}

class _ReportListingSheetState extends ConsumerState<ReportListingSheet> {
  final TextEditingController _details = TextEditingController();
  ListingReportReason? _reason;
  bool _busy = false;
  String? _error;
  Map<String, String> _errorArgs = const <String, String>{};

  @override
  void dispose() {
    _details.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy) return;
    final reason = _reason;
    if (reason == null) {
      setState(() {
        _error = 'report.pick_reason';
        _errorArgs = const <String, String>{};
      });
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(discoverRepositoryProvider)
          .reportListing(widget.listingId, reason, details: _details.text);
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = reportErrorKey(e);
        _errorArgs = (e is ApiException && e.retryAfterSeconds != null)
            ? <String, String>{'n': '${retryAfterMinutes(e.retryAfterSeconds!)}'}
            : const <String, String>{};
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: SingleChildScrollView(
        key: const ValueKey('report-sheet'),
        padding: EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              context.tr('report.title'),
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              context.tr('report.subtitle'),
              style: theme.textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.sm),
            for (final r in ListingReportReason.values)
              ListTile(
                key: ValueKey('report-reason-${r.json}'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                enabled: !_busy,
                leading: Icon(
                  _reason == r ? Icons.radio_button_checked : Icons.radio_button_unchecked,
                  color: _reason == r ? AppColors.primary : AppColors.textSecondary,
                ),
                title: Text(context.tr('report.reason.${r.json}')),
                onTap: () => setState(() {
                  _reason = r;
                  _error = null;
                }),
              ),
            const SizedBox(height: AppSpacing.sm),
            TextField(
              key: const ValueKey('report-details'),
              controller: _details,
              enabled: !_busy,
              minLines: 2,
              maxLines: 4,
              maxLength: kReportDetailsMax,
              decoration: InputDecoration(
                labelText: context.tr('report.details'),
                helperText: context.tr('report.details_hint'),
                helperMaxLines: 2,
              ),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Text(
                  context.tr(_error!, _errorArgs),
                  key: const ValueKey('report-error'),
                  style: const TextStyle(color: AppColors.danger),
                ),
              ),
            PrimaryButton(
              key: const ValueKey('report-submit'),
              label: context.tr('report.submit'),
              icon: Icons.flag_outlined,
              loading: _busy,
              onPressed: _busy ? null : _submit,
            ),
          ],
        ),
      ),
    );
  }
}
