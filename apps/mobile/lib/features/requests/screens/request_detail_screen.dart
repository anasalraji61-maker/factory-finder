import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/deals/deals_models.dart';
import 'package:factory_finder/features/deals/deals_repository.dart';
import 'package:factory_finder/features/deals/widgets/deal_lifecycle_section.dart';
import 'package:factory_finder/features/payments/widgets/deal_payment_section.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:factory_finder/features/requests/screens/create_request_screen.dart'
    show formatDate;
import 'package:factory_finder/features/requests/screens/requests_screen.dart';
import 'package:factory_finder/features/reviews/widgets/deal_review_section.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class RequestDetailScreen extends ConsumerWidget {
  const RequestDetailScreen({super.key, required this.requestId});

  final String requestId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final reqAsync = ref.watch(rfqDetailProvider(requestId));
    final offersAsync = ref.watch(rfqOffersProvider(requestId));
    final me = ref.watch(authProvider);
    final sessionDeal = ref.watch(acceptedDealsProvider)[requestId];
    // Not in memory (supplier, reopened app): ask the backend.
    final acceptedDeal = sessionDeal ??
        ref.watch(requestDealProvider(requestId)).valueOrNull;
    final isMock = ref.watch(apiClientProvider).isMock;
    final myId = me?.id ?? (isMock ? kMockUserId : null);

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('req.detail.title'))),
      body: reqAsync.when(
        loading: () => const LoadingList(itemCount: 3),
        error: (e, _) => ErrorState(
          message: localizedError(context, e),
          onRetry: () => ref.invalidate(rfqDetailProvider(requestId)),
        ),
        data: (r) {
          final isMine = r.buyerId == null || r.buyerId == myId;
          return ListView(
            padding: const EdgeInsets.all(AppSpacing.lg),
            children: [
              _RequestHeader(request: r),
              const SizedBox(height: AppSpacing.lg),
              SectionHeader(title: context.tr('req.detail.offers')),
              offersAsync.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(AppSpacing.xl),
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (e, _) => ErrorState(
                  message: localizedError(context, e),
                  onRetry: () => ref.invalidate(rfqOffersProvider(requestId)),
                ),
                data: (offers) {
                  if (offers.isEmpty) {
                    return Padding(
                      padding: const EdgeInsets.all(AppSpacing.xl),
                      child: Center(child: Text(context.tr('req.detail.no_offers'))),
                    );
                  }
                  return Column(
                    children: [
                      for (final o in offers)
                        Padding(
                          padding: const EdgeInsets.only(bottom: AppSpacing.md),
                          child: OfferCard(
                            offer: o,
                            canAccept: isMine &&
                                r.isLive &&
                                o.status == OfferStatus.active,
                            onAccept: () => _accept(context, ref, r, o),
                          ),
                        ),
                    ],
                  );
                },
              ),
              if (acceptedDeal != null) ...[
                if (dealRoleFor(acceptedDeal, myId,
                        demo: isMock, assumeBuyer: isMine) !=
                    DealRole.none) ...[
                  const SizedBox(height: AppSpacing.lg),
                  DealLifecycleSection(
                    deal: acceptedDeal,
                    role: dealRoleFor(acceptedDeal, myId,
                        demo: isMock, assumeBuyer: isMine),
                  ),
                ],
                if (isMine) ...[
                  const SizedBox(height: AppSpacing.lg),
                  DealPaymentSection(deal: acceptedDeal),
                  const SizedBox(height: AppSpacing.lg),
                  DealReviewSection(
                    deal: acceptedDeal,
                    supplierRef: _supplierOf(offersAsync.valueOrNull, acceptedDeal),
                  ),
                ],
              ],
            ],
          );
        },
      ),
    );
  }

  /// Supplier id of the offer the deal was made on, when known.
  static String? _supplierOf(List<Offer>? offers, Deal deal) {
    if (offers == null) return null;
    for (final o in offers) {
      if (o.id == deal.offerId) return o.supplierId;
    }
    return null;
  }

  Future<void> _accept(
    BuildContext context,
    WidgetRef ref,
    RfqRequest request,
    Offer offer,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => _AcceptDialog(request: request, offer: offer),
    );
    if (confirmed != true || !context.mounted) return;
    try {
      final deal = await ref.read(rfqRepositoryProvider).accept(offer);
      if (!context.mounted) return;
      ref.read(dealsRepositoryProvider).track(deal);
      ref.read(acceptedDealsProvider.notifier).update(
            (m) => <String, Deal>{...m, requestId: deal},
          );
      ref.invalidate(rfqDetailProvider(requestId));
      ref.invalidate(rfqOffersProvider(requestId));
      ref.invalidate(rfqListProvider);
      if (!context.mounted) return;
      await showDialog<void>(
        context: context,
        builder: (ctx) => _DealDialog(deal: deal, rate: deal.commissionRate),
      );
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(localizedError(context, e))));
      }
    }
  }
}

class _RequestHeader extends StatelessWidget {
  const _RequestHeader({required this.request});

  final RfqRequest request;

  @override
  Widget build(BuildContext context) {
    final r = request;
    final theme = Theme.of(context);
    Widget row(String labelKey, Widget value) => Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Row(
            children: [
              Flexible(
                child: Text(
                  context.tr(labelKey),
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: AppColors.textSecondary),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Align(
                  alignment: AlignmentDirectional.centerEnd,
                  child: value,
                ),
              ),
            ],
          ),
        );
    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  r.title,
                  style: theme.textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              StatusPill(
                label: context.tr('req.status.${r.status.json}'),
                color: rfqStatusColor(r.status),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            children: [
              if (r.isInviteOnly)
                StatusPill(
                  key: const ValueKey<String>('req-invite-only-pill'),
                  label: context.tr('req.invite.pill'),
                  color: AppColors.warning,
                ),
              StatusPill(
                label: context.tr('req.kind.${r.kind.json}'),
                color: AppColors.accent,
              ),
              StatusPill(
                label: context.tr('req.cond.${r.condition?.json ?? 'any'}'),
                color: AppColors.textSecondary,
              ),
            ],
          ),
          if (r.description.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.md),
            Text(r.description),
          ],
          const Divider(height: AppSpacing.xl),
          row(
            'req.form.quantity',
            Text(
              '${r.quantity} ${rfqUnitLabel(context, r.unit)}',
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
          if (r.targetPrice != null) row('req.detail.target', MoneyText(r.targetPrice!)),
          if (r.destination != null)
            row(
              'req.detail.destination',
              Text(
                locationLabel(context, r.destination),
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
          if (r.deadline != null)
            row(
              'req.detail.deadline',
              Directionality(
                textDirection: TextDirection.ltr,
                child: Text(
                  formatDate(r.deadline!.toLocal()),
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class OfferCard extends StatelessWidget {
  const OfferCard({
    super.key,
    required this.offer,
    required this.canAccept,
    required this.onAccept,
  });

  final Offer offer;
  final bool canAccept;
  final VoidCallback onAccept;

  @override
  Widget build(BuildContext context) {
    final o = offer;
    final theme = Theme.of(context);
    Widget fact(String labelKey, Widget value) => Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Row(
            children: [
              Flexible(
                child: Text(
                  context.tr(labelKey),
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: AppColors.textSecondary),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Align(
                  alignment: AlignmentDirectional.centerEnd,
                  child: value,
                ),
              ),
            ],
          ),
        );
    return AppCard(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (o.supplierLocation != null) ...[
                CountryFlag(countryCode: o.supplierLocation!.countryCode, size: 18),
                const SizedBox(width: 6),
              ],
              Expanded(
                child: Text(
                  o.supplierName,
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
              if (o.trustScore != null || o.trustBand != TrustBand.unknown)
                TrustBadge(band: o.trustBand, score: o.trustScore, compact: true),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          fact(
            'req.offer.price',
            MoneyText(
              o.unitPrice,
              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
            ),
          ),
          if (o.moq != null)
            fact('req.offer.moq', Text('${o.moq}', style: _bold)),
          if (o.leadTimeDays != null)
            fact(
              'req.offer.lead',
              Text(
                context.tr('req.offer.lead_days', {'n': '${o.leadTimeDays}'}),
                style: _bold,
              ),
            ),
          if (o.incoterm != null)
            fact('req.offer.incoterm', Text(o.incoterm!.json, style: _bold)),
          if (o.validUntil != null)
            fact(
              'req.offer.valid',
              Directionality(
                textDirection: TextDirection.ltr,
                child: Text(formatDate(o.validUntil!.toLocal()), style: _bold),
              ),
            ),
          if (o.note.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(o.note, style: const TextStyle(color: AppColors.textSecondary)),
          ],
          if (o.status == OfferStatus.accepted)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.md),
              child: StatusPill(
                label: context.tr('req.offer.accepted'),
                color: AppColors.success,
              ),
            ),
          if (o.status == OfferStatus.rejected)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.md),
              child: StatusPill(
                label: context.tr('req.offer.rejected'),
                color: AppColors.textSecondary,
              ),
            ),
          if (canAccept) ...[
            const SizedBox(height: AppSpacing.md),
            SizedBox(
              width: double.infinity,
              child: PrimaryButton(
                label: context.tr('req.offer.accept'),
                icon: Icons.check_circle_outline,
                onPressed: onAccept,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

const TextStyle _bold = TextStyle(fontWeight: FontWeight.w700);

class _AcceptDialog extends StatelessWidget {
  const _AcceptDialog({required this.request, required this.offer});

  final RfqRequest request;
  final Offer offer;

  @override
  Widget build(BuildContext context) {
    final est = estimateDeal(request, offer);
    final rate = '${(est.rate * 100).toStringAsFixed(0)}%';
    return AlertDialog(
      title: Text(context.tr('req.accept.title')),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(offer.supplierName, style: _bold),
          const SizedBox(height: AppSpacing.md),
          _amountRow(context.tr('req.accept.goods'), est.goods),
          _amountRow(context.tr('req.accept.commission', {'rate': rate}), est.commission),
          const Divider(),
          _amountRow(context.tr('req.accept.net'), est.net, bold: true),
          const SizedBox(height: AppSpacing.md),
          Text(
            context.tr('req.accept.note'),
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(context.tr('common.cancel')),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: Text(context.tr('req.accept.confirm')),
        ),
      ],
    );
  }
}

class _DealDialog extends StatelessWidget {
  const _DealDialog({required this.deal, this.rate});

  final Deal deal;
  final String? rate;

  @override
  Widget build(BuildContext context) {
    final r = double.tryParse(rate ?? '');
    final rateLabel = r == null ? '' : '${(r * 100).toStringAsFixed(0)}%';
    final net = deal.supplierNet ??
        Money(
          amount: (deal.subtotal.value - deal.commission.value).toStringAsFixed(2),
          currency: deal.subtotal.currency,
        );
    return AlertDialog(
      title: Row(
        children: [
          const Icon(Icons.verified_outlined, color: AppColors.success),
          const SizedBox(width: AppSpacing.sm),
          Expanded(child: Text(context.tr('req.deal.title'))),
        ],
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _amountRow(context.tr('req.deal.id'), null, text: deal.id),
          _amountRow(context.tr('req.accept.goods'), deal.subtotal),
          _amountRow(context.tr('req.accept.commission', {'rate': rateLabel}), deal.commission),
          const Divider(),
          _amountRow(context.tr('req.accept.net'), net, bold: true),
        ],
      ),
      actions: [
        FilledButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(context.tr('req.deal.done')),
        ),
      ],
    );
  }
}

Widget _amountRow(String label, Money? money, {bool bold = false, String? text}) {
  final style = TextStyle(fontWeight: bold ? FontWeight.w800 : FontWeight.w600);
  return Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(
      children: [
        Expanded(child: Text(label)),
        if (money != null)
          MoneyText(money, style: style)
        else
          Directionality(
            textDirection: TextDirection.ltr,
            child: Text(text ?? '', style: style),
          ),
      ],
    ),
  );
}
