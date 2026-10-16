import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/requests/data/mock_rfq.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:factory_finder/features/requests/screens/requests_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Seller side: other buyers' live requests (GET /v1/requests?scope=public).
/// Tapping one opens the offer screen.
class OpenRequestsScreen extends ConsumerWidget {
  const OpenRequestsScreen({super.key});

  static const RfqFilter _filter = RfqFilter(mine: false);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(rfqListProvider(_filter));
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('req.seller.title'))),
      body: async.when(
        loading: () => const LoadingList(),
        error: (e, _) => ErrorState(
          error: e,
          onRetry: () => ref.invalidate(rfqListProvider(_filter)),
        ),
        data: (page) {
          if (page.items.isEmpty) {
            return EmptyState(
              icon: Icons.request_quote_outlined,
              title: context.tr('req.empty.open_title'),
              message: context.tr('req.empty.open_msg'),
            );
          }
          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(rfqListProvider(_filter));
              await ref.read(rfqListProvider(_filter).future);
            },
            child: ListView.separated(
              padding: const EdgeInsets.all(AppSpacing.lg),
              itemCount: page.items.length,
              separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
              itemBuilder: (context, i) {
                final r = page.items[i];
                return RequestCard(
                  key: ValueKey<String>('open-req-${r.id}'),
                  request: r,
                  onTap: () => context.push('/requests/${r.id}/offer'),
                );
              },
            ),
          );
        },
      ),
    );
  }
}
