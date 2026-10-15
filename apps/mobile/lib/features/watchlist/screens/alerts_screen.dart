import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/watchlist/data/watch_models.dart';
import 'package:factory_finder/features/watchlist/data/watch_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Bell icon with an unread-count badge; opens `/alerts`.
class AlertsBell extends ConsumerWidget {
  const AlertsBell({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final n = ref.watch(unreadAlertsProvider).maybeWhen(data: (v) => v, orElse: () => 0);
    return IconButton(
      tooltip: context.tr('alerts.bell'),
      onPressed: () => context.push('/alerts'),
      icon: Stack(
        clipBehavior: Clip.none,
        children: [
          const Icon(Icons.notifications_none),
          if (n > 0)
            PositionedDirectional(
              top: -4,
              end: -4,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                constraints: const BoxConstraints(minWidth: 16),
                decoration: BoxDecoration(
                  color: AppColors.danger,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  n > 99 ? '99+' : '$n',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 10,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class AlertsScreen extends ConsumerWidget {
  const AlertsScreen({super.key});

  void _refreshAll(WidgetRef ref) {
    ref.invalidate(alertsProvider);
    ref.invalidate(unreadAlertsProvider);
  }

  Future<void> _open(BuildContext context, WidgetRef ref, PriceAlert a) async {
    final listingId = a.listingId;
    final trackingRoute = a.trackingRoute;
    final router = GoRouter.of(context);
    if (!a.read) {
      try {
        await ref.read(watchlistRepositoryProvider).markRead(a.id);
      } catch (_) {
        // Non-fatal: still open the listing.
      }
      _refreshAll(ref);
    }
    if (trackingRoute != null) {
      router.push(trackingRoute);
    } else if (listingId != null) {
      router.push('/listing/$listingId');
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(alertsProvider);
    final unread = async.maybeWhen(data: (p) => p.unreadTotal, orElse: () => 0);
    return Scaffold(
      appBar: AppBar(
        title: Text(context.tr('watch.alerts_title')),
        actions: [
          if (unread > 0)
            TextButton(
              onPressed: () async {
                final messenger = ScaffoldMessenger.of(context);
                final failText = context.tr('watch.failed');
                try {
                  await ref.read(watchlistRepositoryProvider).markAllRead();
                  _refreshAll(ref);
                } catch (_) {
                  messenger.showSnackBar(SnackBar(content: Text(failText)));
                }
              },
              child: Text(context.tr('alerts.mark_all')),
            ),
        ],
      ),
      body: async.when(
        loading: () => const LoadingList(),
        error: (e, _) => ErrorState(
          message: localizedError(context, e),
          onRetry: () => ref.invalidate(alertsProvider),
        ),
        data: (page) {
          Future<void> refresh() async {
            _refreshAll(ref);
            await ref.read(alertsProvider.future);
          }

          if (page.items.isEmpty) {
            return RefreshIndicator(
              onRefresh: refresh,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  SizedBox(
                    height: 420,
                    child: EmptyState(
                      icon: Icons.notifications_none,
                      title: context.tr('watch.alerts_empty_title'),
                      message: context.tr('watch.alerts_empty_msg'),
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
              itemCount: page.items.length,
              separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.sm),
              itemBuilder: (context, i) => _AlertTile(
                alert: page.items[i],
                onTap: () => _open(context, ref, page.items[i]),
              ),
            ),
          );
        },
      ),
    );
  }
}

/// Distinct icon per rule; unknown rules fall back to a generic bell.
IconData alertIcon(String rule) {
  switch (rule) {
    case 'price_drop':
    case 'below_target':
      return Icons.trending_down;
    case kRuleShipmentStatus:
      return Icons.local_shipping_outlined;
    case kRuleShipmentDelayed:
      return Icons.schedule;
    default:
      return Icons.notifications_active_outlined;
  }
}

class _AlertTile extends StatelessWidget {
  const _AlertTile({required this.alert, required this.onTap});
  final PriceAlert alert;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final lang = Localizations.localeOf(context).languageCode;
    final a = alert;
    return AppCard(
      onTap: onTap,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            alertIcon(a.rule),
            key: Key('alert_icon_${a.rule}'),
            color: a.read
                ? AppColors.textSecondary
                : (a.rule == kRuleShipmentDelayed
                    ? AppColors.danger
                    : theme.colorScheme.primary),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  a.displayTitle(lang).isNotEmpty
                      ? a.displayTitle(lang)
                      : (a.isShipment ? context.tr('alerts.${a.rule}') : ''),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: a.read ? FontWeight.w500 : FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  a.displayBody(lang),
                  maxLines: 4,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: AppColors.textSecondary, height: 1.4),
                ),
              ],
            ),
          ),
          if (!a.read)
            Container(
              margin: const EdgeInsetsDirectional.only(start: AppSpacing.sm, top: 6),
              width: 10,
              height: 10,
              decoration: BoxDecoration(
                color: theme.colorScheme.primary,
                shape: BoxShape.circle,
              ),
            ),
        ],
      ),
    );
  }
}
