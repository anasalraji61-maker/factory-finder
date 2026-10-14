import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/trust/trust_models.dart';
import 'package:factory_finder/features/trust/trust_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

String confidenceLabelKey(int c) => c >= 70
    ? 'trust.confidence_high'
    : (c >= 40 ? 'trust.confidence_mid' : 'trust.confidence_low');

/// Confidence meter, missing information, flags, history chart and the
/// "report a concern" entry point for one supplier.
class TrustInsights extends ConsumerWidget {
  const TrustInsights({super.key, required this.supplierId, required this.trust});

  final String supplierId;
  final TrustScore trust;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final lang = Localizations.localeOf(context).languageCode;
    final theme = Theme.of(context);
    final conf = trust.confidence;
    final history = ref.watch(trustHistoryProvider(supplierId));

    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (conf != null) ...[
            Row(
              children: [
                Expanded(
                  child: Text(
                    context.tr('trust.confidence'),
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Flexible(
                  child: Text(
                    '${context.tr(confidenceLabelKey(conf))} · ${context.tr('trust.confidence_value', {'n': '$conf'})}',
                    textAlign: TextAlign.end,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: LinearProgressIndicator(
                key: const Key('trust_confidence_meter'),
                value: conf / 100,
                minHeight: 8,
                backgroundColor: AppColors.border,
                color: conf >= 70
                    ? AppColors.success
                    : (conf >= 40 ? AppColors.warning : AppColors.textSecondary),
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              context.tr('trust.confidence_hint'),
              style: const TextStyle(
                color: AppColors.textSecondary,
                fontSize: 12,
                height: 1.4,
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
          ],
          if (trust.flags.isNotEmpty) ...[
            Text(
              context.tr('trust.flags_title'),
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.xs,
              children: [
                for (final f in trust.flags)
                  ConstrainedBox(
                    constraints: BoxConstraints(
                      maxWidth: MediaQuery.of(context).size.width - 96,
                    ),
                    child: Chip(
                      avatar: const Icon(
                        Icons.flag_outlined,
                        size: 16,
                        color: AppColors.danger,
                      ),
                      label: Text(
                        flagLabel(context, f),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.lg),
          ],
          if (trust.dataGaps.isNotEmpty) ...[
            Text(
              context.tr('trust.gaps_title'),
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              context.tr('trust.gaps_hint'),
              style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
            ),
            const SizedBox(height: AppSpacing.sm),
            for (final g in trust.dataGaps)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  children: [
                    const Icon(
                      Icons.help_outline,
                      size: 16,
                      color: AppColors.textSecondary,
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Text(g.display(lang), style: theme.textTheme.bodyMedium),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: AppSpacing.lg),
          ],
          Text(
            context.tr('trust.history_title'),
            style: const TextStyle(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.sm),
          history.when(
            loading: () => SizedBox(
              height: 40,
              child: Center(
                child: Text(
                  context.tr('trust.history_loading'),
                  style: const TextStyle(color: AppColors.textSecondary),
                ),
              ),
            ),
            error: (e, _) => Text(
              context.tr('trust.history_failed'),
              style: const TextStyle(color: AppColors.textSecondary),
            ),
            data: (points) => TrustHistoryChart(points: points),
          ),
          const SizedBox(height: AppSpacing.md),
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: TextButton(
              key: const Key('trust_report_button'),
              onPressed: () => openReportSheet(context, ref, supplierId),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.report_gmailerrorred_outlined, size: 18),
                  const SizedBox(width: 8),
                  Flexible(child: Text(context.tr('trust.report.open'))),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

String flagLabel(BuildContext context, String flag) {
  if (kKnownTrustFlags.contains(flag)) return context.tr('trust.flag.$flag');
  return flag.replaceAll('_', ' ');
}

/// Score-over-time line chart. Fewer than two points shows a message instead.
class TrustHistoryChart extends StatelessWidget {
  const TrustHistoryChart({super.key, required this.points});

  final List<TrustHistoryPoint> points;

  @override
  Widget build(BuildContext context) {
    if (points.length < 2) {
      return Text(
        context.tr('trust.history_empty'),
        key: const Key('trust_history_empty'),
        style: const TextStyle(color: AppColors.textSecondary),
      );
    }
    return SizedBox(
      height: 120,
      width: double.infinity,
      child: Directionality(
        // Time always runs left to right, even in Arabic.
        textDirection: TextDirection.ltr,
        child: CustomPaint(
          key: const Key('trust_history_chart'),
          painter: TrustHistoryPainter(
            scores: [for (final p in points) p.score],
            lineColor: AppColors.primary,
            gridColor: AppColors.border,
          ),
        ),
      ),
    );
  }
}

class TrustHistoryPainter extends CustomPainter {
  TrustHistoryPainter({
    required this.scores,
    required this.lineColor,
    required this.gridColor,
  });

  final List<int> scores;
  final Color lineColor;
  final Color gridColor;

  /// Pixel position of point [i] (score 0-100 mapped to the height).
  static Offset pointAt(int i, int count, int score, Size size) {
    final x = count <= 1 ? size.width / 2 : size.width * i / (count - 1);
    final y = size.height * (1 - score.clamp(0, 100) / 100);
    return Offset(x, y);
  }

  @override
  void paint(Canvas canvas, Size size) {
    final grid = Paint()
      ..color = gridColor
      ..strokeWidth = 1;
    for (final v in const [0, 50, 100]) {
      final y = size.height * (1 - v / 100);
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
    if (scores.length < 2) return;
    final path = Path();
    for (var i = 0; i < scores.length; i++) {
      final o = pointAt(i, scores.length, scores[i], size);
      if (i == 0) {
        path.moveTo(o.dx, o.dy);
      } else {
        path.lineTo(o.dx, o.dy);
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = lineColor
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5
        ..strokeJoin = StrokeJoin.round,
    );
    final dot = Paint()..color = lineColor;
    for (var i = 0; i < scores.length; i++) {
      canvas.drawCircle(pointAt(i, scores.length, scores[i], size), 3.5, dot);
    }
  }

  @override
  bool shouldRepaint(TrustHistoryPainter old) =>
      old.scores != scores || old.lineColor != lineColor || old.gridColor != gridColor;
}

Future<void> openReportSheet(
  BuildContext context,
  WidgetRef ref,
  String supplierId,
) async {
  if (ref.read(authProvider) == null) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    messenger.showSnackBar(SnackBar(content: Text(context.tr('trust.report.login'))));
    return;
  }
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (ctx) => ReportConcernSheet(supplierId: supplierId),
  );
}

class ReportConcernSheet extends ConsumerStatefulWidget {
  const ReportConcernSheet({super.key, required this.supplierId});

  final String supplierId;

  @override
  ConsumerState<ReportConcernSheet> createState() => _ReportConcernSheetState();
}

class _ReportConcernSheetState extends ConsumerState<ReportConcernSheet> {
  final TextEditingController _text = TextEditingController();
  String? _type;
  String? _errorKey; // validation / submit error i18n key
  bool _busy = false;
  bool _done = false;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final err = validateReport(_type, _text.text);
    if (err != null) {
      setState(() => _errorKey = err);
      return;
    }
    setState(() {
      _busy = true;
      _errorKey = null;
    });
    try {
      await ref
          .read(trustExtrasRepositoryProvider)
          .report(widget.supplierId, _type!, _text.text);
      if (!mounted) return;
      setState(() {
        _busy = false;
        _done = true;
      });
    } catch (e) {
      if (!mounted) return;
      final status = e is ApiException ? e.status : null;
      setState(() {
        _busy = false;
        _errorKey = status == 429
            ? 'trust.report.rate_limited'
            : (status == 401 ? 'trust.report.login' : 'trust.report.failed');
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final inset = MediaQuery.of(context).viewInsets.bottom;
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg + inset,
        ),
        child: _done ? _success(context) : _form(context),
      ),
    );
  }

  Widget _success(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.check_circle, color: AppColors.success),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Text(
                context.tr('trust.report.success'),
                key: const Key('trust_report_success'),
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.md),
        Align(
          alignment: AlignmentDirectional.centerEnd,
          child: TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text(context.tr('trust.report.close')),
          ),
        ),
      ],
    );
  }

  Widget _form(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          context.tr('trust.report.title'),
          style: Theme.of(context)
              .textTheme
              .titleMedium
              ?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: AppSpacing.xs),
        Text(
          context.tr('trust.report.note'),
          style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
        ),
        const SizedBox(height: AppSpacing.md),
        InputDecorator(
          decoration: InputDecoration(labelText: context.tr('trust.report.type')),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              key: const Key('trust_report_type'),
              isExpanded: true,
              value: _type,
              hint: Text(
                context.tr('trust.report.type_hint'),
                overflow: TextOverflow.ellipsis,
              ),
              items: [
                for (final t in kReportTypes)
                  DropdownMenuItem<String>(
                    value: t,
                    child: Text(
                      context.tr('trust.report_type.$t'),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
              onChanged: _busy ? null : (v) => setState(() => _type = v),
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        TextField(
          key: const Key('trust_report_text'),
          controller: _text,
          enabled: !_busy,
          minLines: 3,
          maxLines: 5,
          maxLength: kReportMaxLength,
          decoration: InputDecoration(labelText: context.tr('trust.report.text')),
        ),
        if (_errorKey != null) ...[
          const SizedBox(height: AppSpacing.sm),
          Text(
            context.tr(_errorKey!),
            key: const Key('trust_report_error'),
            style: const TextStyle(color: AppColors.danger),
          ),
        ],
        const SizedBox(height: AppSpacing.md),
        PrimaryButton(
          label: context.tr('trust.report.submit'),
          loading: _busy,
          onPressed: _busy ? null : _submit,
        ),
      ],
    );
  }
}
