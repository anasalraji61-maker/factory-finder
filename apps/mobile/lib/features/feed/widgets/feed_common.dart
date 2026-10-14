import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/feed/feed_logic.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Localised message for any feed failure (all error codes, 429 Retry-After).
String feedErrorMessage(BuildContext context, Object error) {
  final t = describeFeedError(error);
  return context.tr(t.key, t.args);
}

void showFeedSnack(BuildContext context, String message) {
  final messenger = ScaffoldMessenger.maybeOf(context);
  messenger
    ?..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

void showFeedError(BuildContext context, Object error) =>
    showFeedSnack(context, feedErrorMessage(context, error));

/// True when the signed-in user owns a verified supplier account.
bool isVerifiedSupplier(Me? me) =>
    me != null && me.supplierId != null && me.supplierClaimStatus == 'verified';

final verifiedSupplierProvider = Provider<bool>((ref) => isVerifiedSupplier(ref.watch(authProvider)));

/// Relative time ("5 min ago"), falling back to the date after a week.
String feedTimeLabel(BuildContext context, DateTime? at, {DateTime? now}) {
  if (at == null) return '';
  final diff = (now ?? DateTime.now()).toUtc().difference(at.toUtc());
  if (diff.inMinutes < 1) return context.tr('feed.time.now');
  if (diff.inMinutes < 60) return context.tr('feed.time.min', {'n': '${diff.inMinutes}'});
  if (diff.inHours < 24) return context.tr('feed.time.hour', {'n': '${diff.inHours}'});
  if (diff.inDays < 7) return context.tr('feed.time.day', {'n': '${diff.inDays}'});
  final d = at.toUtc();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${d.year}-${two(d.month)}-${two(d.day)}';
}

Future<bool> confirmFeedAction(
  BuildContext context, {
  required String title,
  required String confirmLabel,
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(ctx).pop(false),
          child: Text(ctx.tr('common.cancel')),
        ),
        FilledButton(
          key: const ValueKey<String>('feed-confirm'),
          onPressed: () => Navigator.of(ctx).pop(true),
          child: Text(confirmLabel),
        ),
      ],
    ),
  );
  return ok ?? false;
}
