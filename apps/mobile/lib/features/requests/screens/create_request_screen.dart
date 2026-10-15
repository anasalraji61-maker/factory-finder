import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:factory_finder/features/requests/data/rfq_validators.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

const List<String> kRfqUnits = ['piece', 'kg', 'ton', 'set', 'm', 'line'];
const List<String> kRfqCurrencies = ['USD', 'EUR', 'CNY', 'IQD'];

class CreateRequestScreen extends ConsumerStatefulWidget {
  const CreateRequestScreen({
    super.key,
    this.initialInvites = const <InvitedSupplier>[],
  });

  /// Suppliers pre-added as invitees (e.g. from the supplier profile).
  final List<InvitedSupplier> initialInvites;

  @override
  ConsumerState<CreateRequestScreen> createState() => _CreateRequestScreenState();
}

class _CreateRequestScreenState extends ConsumerState<CreateRequestScreen> {
  final _formKey = GlobalKey<FormState>();
  final _title = TextEditingController();
  final _description = TextEditingController();
  final _quantity = TextEditingController(text: '1');
  final _price = TextEditingController();

  ListingKind _kind = ListingKind.product;
  ItemCondition? _condition; // null = any
  String _unit = 'piece';
  String _currency = 'USD';
  Location? _destination;
  DateTime? _deadline;
  String? _deadlineError;
  bool _busy = false;
  final List<InvitedSupplier> _invites = <InvitedSupplier>[];

  @override
  void initState() {
    super.initState();
    for (final i in widget.initialInvites) {
      if (_invites.length < kRfqMaxInvites &&
          !_invites.any((e) => e.id == i.id)) {
        _invites.add(i);
      }
    }
    _destination = ref.read(destinationProvider);
  }

  @override
  void dispose() {
    _title.dispose();
    _description.dispose();
    _quantity.dispose();
    _price.dispose();
    super.dispose();
  }

  String? _v(String? Function() check) {
    final k = check();
    return k == null ? null : context.tr(k);
  }

  Future<void> _pickDeadline() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _deadline ?? now.add(const Duration(days: 14)),
      firstDate: now,
      lastDate: now.add(const Duration(days: 365 * 2)),
    );
    if (picked != null) {
      setState(() {
        _deadline = picked;
        _deadlineError = null;
      });
    }
  }

  Future<void> _pickDestination() async {
    final picked = await showLocationEditor(
      context,
      initial: _destination ?? const Location(countryCode: 'IQ', city: 'Baghdad'),
    );
    if (picked != null) setState(() => _destination = picked);
  }

  Future<void> _submit() async {
    final deadlineKey = validateRfqDeadline(_deadline, DateTime.now());
    setState(() => _deadlineError = deadlineKey == null ? null : context.tr(deadlineKey));
    final ok = _formKey.currentState?.validate() ?? false;
    if (!ok || deadlineKey != null) return;
    final dest = _destination;
    if (dest == null) return;

    final api = ref.read(apiClientProvider);
    if (!api.isMock && ref.read(authProvider) == null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(context.tr('auth.session_required'))));
      context.push('/login');
      return;
    }

    final priceText = normalizeNumberInput(_price.text);
    final draft = RfqDraft(
      kind: _kind,
      condition: _condition,
      title: _title.text.trim(),
      description: _description.text.trim(),
      quantity: normalizeNumberInput(_quantity.text),
      unit: _unit,
      targetPrice: priceText.isEmpty
          ? null
          : Money(amount: priceText, currency: _currency),
      destination: dest,
      deadline: _deadline == null
          ? null
          : DateTime(_deadline!.year, _deadline!.month, _deadline!.day, 23, 59),
      invitedSupplierIds: <String>[for (final i in _invites) i.id],
    );
    setState(() => _busy = true);
    try {
      final created = await ref.read(rfqRepositoryProvider).create(draft);
      ref.invalidate(rfqListProvider);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(context.tr('req.form.created'))));
      context.pushReplacement('/requests/${created.id}');
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(localizedError(context, e))));
      }
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
    final deadline = _deadline;
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('req.new'))),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            _label('req.form.kind'),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final k in ListingKind.values)
                  ChoiceChip(
                    label: Text(context.tr('req.kind.${k.json}')),
                    selected: _kind == k,
                    onSelected: (_) => setState(() => _kind = k),
                  ),
              ],
            ),
            _label('req.form.condition'),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                ChoiceChip(
                  label: Text(context.tr('req.cond.any')),
                  selected: _condition == null,
                  onSelected: (_) => setState(() => _condition = null),
                ),
                for (final c in const [ItemCondition.brandNew, ItemCondition.used])
                  ChoiceChip(
                    label: Text(context.tr('req.cond.${c.json}')),
                    selected: _condition == c,
                    onSelected: (_) => setState(() => _condition = c),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.lg),
            TextFormField(
              controller: _title,
              textInputAction: TextInputAction.next,
              decoration: InputDecoration(labelText: context.tr('req.form.title')),
              validator: (v) => _v(() => validateRfqTitle(v)),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              controller: _description,
              minLines: 3,
              maxLines: 6,
              decoration: InputDecoration(labelText: context.tr('req.form.description')),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              controller: _quantity,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(labelText: context.tr('req.form.quantity')),
              validator: (v) =>
                  _v(() => validateRfqQuantity(normalizeNumberInput(v ?? ''))),
            ),
            _label('req.form.unit'),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final u in kRfqUnits)
                  ChoiceChip(
                    label: Text(context.tr('req.unit.$u')),
                    selected: _unit == u,
                    onSelected: (_) => setState(() => _unit = u),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.lg),
            TextFormField(
              controller: _price,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration:
                  InputDecoration(labelText: context.tr('req.form.target_price')),
              validator: (v) =>
                  _v(() => validateRfqTargetPrice(normalizeNumberInput(v ?? ''))),
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
            _label('req.form.destination'),
            AppCard(
              onTap: _pickDestination,
              child: Row(
                children: [
                  if (_destination != null)
                    CountryFlag(countryCode: _destination!.countryCode, size: 22)
                  else
                    const Icon(Icons.place_outlined),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(child: Text(locationLabel(context, _destination))),
                  const Icon(Icons.edit_outlined, size: 20),
                ],
              ),
            ),
            _label('req.form.deadline'),
            AppCard(
              onTap: _pickDeadline,
              child: Row(
                children: [
                  const Icon(Icons.event_outlined),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Text(
                      deadline == null
                          ? context.tr('req.form.deadline_none')
                          : formatDate(deadline),
                    ),
                  ),
                  if (deadline != null)
                    IconButton(
                      tooltip: context.tr('common.reset'),
                      icon: const Icon(Icons.close, size: 18),
                      onPressed: () => setState(() {
                        _deadline = null;
                        _deadlineError = null;
                      }),
                    ),
                ],
              ),
            ),
            if (_deadlineError != null)
              Padding(
                padding: const EdgeInsets.only(top: 6, left: 12, right: 12),
                child: Text(
                  _deadlineError!,
                  style: const TextStyle(color: AppColors.danger, fontSize: 12),
                ),
              ),
            if (_invites.isNotEmpty) ...[
              _label('req.invite.title'),
              Text(
                context.tr('req.invite.count', {
                  'n': '${_invites.length}',
                  'max': '$kRfqMaxInvites',
                }),
                key: const ValueKey<String>('req-invite-count'),
              ),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: [
                  for (final i in _invites)
                    InputChip(
                      key: ValueKey<String>('req-invite-${i.id}'),
                      label: Text(i.name),
                      deleteButtonTooltipMessage: context.tr('req.invite.remove'),
                      onDeleted: () => setState(() => _invites.remove(i)),
                    ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                context.tr('req.invite.note'),
                style: TextStyle(
                  fontSize: 12,
                  color: AppColors.secondaryOf(context),
                ),
              ),
            ],
            const SizedBox(height: AppSpacing.xl),
            PrimaryButton(
              label: context.tr('req.form.submit'),
              icon: Icons.send_rounded,
              loading: _busy,
              onPressed: _submit,
            ),
            const SizedBox(height: AppSpacing.xl),
          ],
        ),
      ),
    );
  }
}

/// yyyy-MM-dd (locale-neutral, digits stay Latin).
String formatDate(DateTime d) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${d.year}-${two(d.month)}-${two(d.day)}';
}
