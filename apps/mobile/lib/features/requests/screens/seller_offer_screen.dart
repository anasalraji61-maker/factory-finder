import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:factory_finder/features/requests/data/rfq_validators.dart';
import 'package:factory_finder/features/requests/screens/create_request_screen.dart'
    show kRfqCurrencies;
import 'package:factory_finder/features/requests/screens/requests_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Seller view of one request: summary, my offers (with withdraw) and the
/// offer form.
class SellerOfferScreen extends ConsumerStatefulWidget {
  const SellerOfferScreen({super.key, required this.requestId});

  final String requestId;

  @override
  ConsumerState<SellerOfferScreen> createState() => _SellerOfferScreenState();
}

class _SellerOfferScreenState extends ConsumerState<SellerOfferScreen> {
  final _formKey = GlobalKey<FormState>();
  final _supplier = TextEditingController();
  final _price = TextEditingController();
  final _moq = TextEditingController();
  final _lead = TextEditingController();
  final _note = TextEditingController();
  String _currency = 'USD';
  bool _busy = false;

  @override
  void dispose() {
    _supplier.dispose();
    _price.dispose();
    _moq.dispose();
    _lead.dispose();
    _note.dispose();
    super.dispose();
  }

  String? _v(String? key) => key == null ? null : context.tr(key);

  void _toast(String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  bool _signedIn() {
    final api = ref.read(apiClientProvider);
    if (!api.isMock && ref.read(authProvider) == null) {
      _toast(context.tr('auth.session_required'));
      context.push('/login');
      return false;
    }
    return true;
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (!_signedIn()) return;
    final moq = normalizeNumberInput(_moq.text);
    final lead = normalizeNumberInput(_lead.text);
    final draft = OfferDraft(
      price: Money(amount: normalizeNumberInput(_price.text), currency: _currency),
      supplierName: _supplier.text.trim(),
      moq: moq.isEmpty ? null : int.tryParse(moq),
      leadTimeDays: lead.isEmpty ? null : int.tryParse(lead),
      note: _note.text.trim(),
    );
    setState(() => _busy = true);
    try {
      await ref.read(rfqRepositoryProvider).submitOffer(widget.requestId, draft);
      ref.invalidate(myOffersProvider(widget.requestId));
      ref.invalidate(rfqListProvider);
      if (!mounted) return;
      _price.clear();
      _moq.clear();
      _lead.clear();
      _note.clear();
      _toast(context.tr('req.offer.sent'));
    } catch (e) {
      if (mounted) _toast(localizedError(context, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _withdraw(Offer offer) async {
    if (!_signedIn()) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        content: Text(ctx.tr('req.offer.withdraw_confirm')),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(ctx.tr('common.cancel')),
          ),
          FilledButton(
            key: const ValueKey<String>('offer-withdraw-confirm'),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(ctx.tr('req.offer.withdraw')),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _busy = true);
    try {
      await ref.read(rfqRepositoryProvider).withdrawOffer(offer);
      ref.invalidate(myOffersProvider(widget.requestId));
      ref.invalidate(rfqListProvider);
      if (mounted) _toast(context.tr('req.offer.withdraw_done'));
    } catch (e) {
      if (mounted) _toast(localizedError(context, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _label(String key) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.lg, bottom: AppSpacing.sm),
        child: Text(
          context.tr(key),
          style: const TextStyle(fontWeight: FontWeight.w800),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final reqAsync = ref.watch(rfqDetailProvider(widget.requestId));
    final offersAsync = ref.watch(myOffersProvider(widget.requestId));
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('req.seller.title'))),
      body: reqAsync.when(
        loading: () => const LoadingList(),
        error: (e, _) => ErrorState(
          error: e,
          onRetry: () => ref.invalidate(rfqDetailProvider(widget.requestId)),
        ),
        data: (r) => ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            RequestCard(request: r, onTap: () {}),
            _label('req.seller.my_offers'),
            ...offersAsync.when(
              loading: () => const <Widget>[
                Center(child: CircularProgressIndicator()),
              ],
              error: (e, _) => <Widget>[
                ErrorState(
                  error: e,
                  onRetry: () => ref.invalidate(myOffersProvider(widget.requestId)),
                ),
              ],
              data: (offers) => _offersAndForm(context, r, offers),
            ),
            const SizedBox(height: AppSpacing.xl),
          ],
        ),
      ),
    );
  }

  List<Widget> _offersAndForm(
    BuildContext context,
    RfqRequest r,
    List<Offer> offers,
  ) {
    final hasActive = offers.any((o) => o.status == OfferStatus.active);
    return [
      if (offers.isEmpty)
        Text(
          context.tr('req.seller.no_offers'),
          style: const TextStyle(color: AppColors.textSecondary),
        ),
      for (final o in offers) ...[
        _MyOfferCard(
          offer: o,
          busy: _busy,
          onWithdraw: () => _withdraw(o),
        ),
        const SizedBox(height: AppSpacing.md),
      ],
      if (!r.isLive)
        Text(
          context.tr('req.seller.closed_note'),
          style: const TextStyle(color: AppColors.textSecondary),
        )
      else if (hasActive)
        Text(
          context.tr('req.seller.active_note'),
          style: const TextStyle(color: AppColors.textSecondary),
        )
      else
        _form(context),
    ];
  }

  Widget _form(BuildContext context) {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _label('req.offer.form_title'),
          TextFormField(
            key: const ValueKey<String>('offer-supplier'),
            controller: _supplier,
            decoration: InputDecoration(labelText: context.tr('req.offer.supplier_name')),
            validator: (v) => _v(validateOfferSupplierName(v)),
          ),
          const SizedBox(height: AppSpacing.md),
          TextFormField(
            key: const ValueKey<String>('offer-price'),
            controller: _price,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(labelText: context.tr('req.offer.price')),
            validator: (v) => _v(validateOfferPrice(normalizeNumberInput(v ?? ''))),
          ),
          _label('req.form.currency'),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              for (final c in kRfqCurrencies)
                ChoiceChip(
                  label: Text(c),
                  selected: _currency == c,
                  onSelected: (_) => setState(() => _currency = c),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          TextFormField(
            key: const ValueKey<String>('offer-moq'),
            controller: _moq,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(labelText: context.tr('req.offer.moq_field')),
            validator: (v) => _v(validateOfferInt(normalizeNumberInput(v ?? ''))),
          ),
          const SizedBox(height: AppSpacing.md),
          TextFormField(
            key: const ValueKey<String>('offer-lead'),
            controller: _lead,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(labelText: context.tr('req.offer.lead_field')),
            validator: (v) => _v(validateOfferInt(normalizeNumberInput(v ?? ''))),
          ),
          const SizedBox(height: AppSpacing.md),
          TextFormField(
            key: const ValueKey<String>('offer-note'),
            controller: _note,
            maxLines: 4,
            decoration: InputDecoration(labelText: context.tr('req.offer.note')),
          ),
          const SizedBox(height: AppSpacing.xl),
          PrimaryButton(
            key: const ValueKey<String>('offer-submit'),
            label: context.tr('req.offer.submit'),
            icon: Icons.send_rounded,
            loading: _busy,
            onPressed: _busy ? null : _submit,
          ),
        ],
      ),
    );
  }
}

String _offerStatusKey(OfferStatus s) {
  switch (s) {
    case OfferStatus.active:
      return 'req.offer.pending';
    case OfferStatus.accepted:
      return 'req.offer.accepted';
    case OfferStatus.rejected:
      return 'req.offer.rejected';
    case OfferStatus.withdrawn:
      return 'req.offer.withdrawn';
    case OfferStatus.expired:
      return 'req.offer.expired';
  }
}

class _MyOfferCard extends StatelessWidget {
  const _MyOfferCard({
    required this.offer,
    required this.busy,
    required this.onWithdraw,
  });

  final Offer offer;
  final bool busy;
  final VoidCallback onWithdraw;

  @override
  Widget build(BuildContext context) {
    final o = offer;
    final active = o.status == OfferStatus.active;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  o.supplierName,
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              StatusPill(
                label: context.tr(_offerStatusKey(o.status)),
                color: active ? AppColors.primary : AppColors.textSecondary,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: [
              Text('${context.tr('req.offer.price')}: '),
              MoneyText(o.unitPrice),
            ],
          ),
          if (o.moq != null) Text('${context.tr('req.offer.moq')}: ${o.moq}'),
          if (o.leadTimeDays != null)
            Text(
              '${context.tr('req.offer.lead')}: '
              '${context.tr('req.offer.lead_days', {'n': '${o.leadTimeDays}'})}',
            ),
          if (o.note.isNotEmpty) Text(o.note),
          if (active) ...[
            const SizedBox(height: AppSpacing.sm),
            OutlinedButton.icon(
              key: ValueKey<String>('offer-withdraw-${o.id}'),
              onPressed: busy ? null : onWithdraw,
              icon: const Icon(Icons.undo_rounded, size: 18),
              label: Text(context.tr('req.offer.withdraw')),
            ),
          ],
        ],
      ),
    );
  }
}
