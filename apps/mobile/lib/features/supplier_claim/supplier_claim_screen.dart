import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/supplier_claim/supplier_claim_logic.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class SupplierClaimScreen extends ConsumerStatefulWidget {
  const SupplierClaimScreen({super.key});

  @override
  ConsumerState<SupplierClaimScreen> createState() => _SupplierClaimScreenState();
}

class _SupplierClaimScreenState extends ConsumerState<SupplierClaimScreen> {
  final TextEditingController _controller = TextEditingController();
  bool _loading = false;
  String? _errorKey;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _run(String? supplierId, String okKey) async {
    setState(() {
      _loading = true;
      _errorKey = null;
    });
    try {
      await ref.read(authProvider.notifier).claimSupplier(supplierId);
      if (!mounted) return;
      setState(() => _loading = false);
      if (supplierId == null) _controller.clear();
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(context.tr(okKey))));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _errorKey = claimErrorKey(e);
      });
    }
  }

  void _claim() {
    final value = _controller.text.trim();
    final err = supplierIdErrorKey(value);
    if (err != null) {
      setState(() => _errorKey = err);
      return;
    }
    _run(value, 'claim.ok_claimed');
  }

  @override
  Widget build(BuildContext context) {
    final me = ref.watch(authProvider);
    final current = me?.supplierId;
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('claim.title'))),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          if (me == null)
            Text(context.tr('claim.signin'))
          else ...[
            Text(context.tr('claim.intro')),
            const SizedBox(height: AppSpacing.md),
            Text(
              current == null
                  ? context.tr('claim.not_linked')
                  : context.tr('claim.current', {'id': current}),
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            if (current != null && me.supplierClaimStatus != 'none') ...[
              const SizedBox(height: AppSpacing.sm),
              Text(
                context.tr(me.supplierClaimStatus == 'pending'
                    ? 'claim.status.pending'
                    : 'claim.status.verified'),
              ),
            ],
            const SizedBox(height: AppSpacing.md),
            TextField(
              controller: _controller,
              enabled: !_loading,
              textDirection: TextDirection.ltr,
              autocorrect: false,
              decoration: InputDecoration(
                labelText: context.tr('claim.field'),
                hintText: context.tr('claim.hint'),
                errorText: _errorKey == null ? null : context.tr(_errorKey!),
              ),
              onChanged: (_) {
                if (_errorKey != null) setState(() => _errorKey = null);
              },
              onSubmitted: (_) => _loading ? null : _claim(),
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: context.tr('claim.claim'),
              icon: Icons.link,
              loading: _loading,
              onPressed: _loading ? null : _claim,
            ),
            if (current != null) ...[
              const SizedBox(height: AppSpacing.md),
              OutlinedButton.icon(
                onPressed: _loading ? null : () => _run(null, 'claim.ok_released'),
                icon: const Icon(Icons.link_off),
                label: Text(context.tr('claim.release')),
              ),
            ],
          ],
        ],
      ),
    );
  }
}
