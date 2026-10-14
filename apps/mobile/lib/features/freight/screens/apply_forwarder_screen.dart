import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/freight/data/freight_drafts.dart';
import 'package:factory_finder/features/freight/data/freight_errors.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Apply as a forwarder: company, lanes, modes, incoterms, certifications.
/// An admin reviews the application (never auto-approved by the service).
class ApplyForwarderScreen extends ConsumerStatefulWidget {
  const ApplyForwarderScreen({super.key});

  @override
  ConsumerState<ApplyForwarderScreen> createState() => _ApplyForwarderScreenState();
}

class _LaneRow {
  _LaneRow(this.id, this.origin, this.destination);

  final int id;
  String origin;
  String destination;
}

class _ApplyForwarderScreenState extends ConsumerState<ApplyForwarderScreen> {
  final GlobalKey<FormState> _form = GlobalKey<FormState>();
  final TextEditingController _company = TextEditingController();
  final TextEditingController _description = TextEditingController();
  final TextEditingController _certs = TextEditingController();
  String _country = 'CN';
  int _laneSeq = 1;
  late final List<_LaneRow> _lanes = [_LaneRow(0, 'CN', 'IQ')];
  final Set<String> _modes = {'sea'};
  final Set<String> _incoterms = {'FOB'};
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _company.dispose();
    _description.dispose();
    _certs.dispose();
    super.dispose();
  }

  List<String> _certList() => [
        for (final p in _certs.text.split(RegExp(r'[,\n،]')))
          if (p.trim().isNotEmpty) p.trim(),
      ];

  ApplicationDraft _draft() => ApplicationDraft(
        companyName: _company.text,
        countryCode: _country,
        description: _description.text,
        lanes: [
          for (final l in _lanes) Lane(origin: l.origin, destination: l.destination),
        ],
        modes: [for (final m in kFreightModes) if (_modes.contains(m)) m],
        incoterms: [for (final i in kFreightIncoterms) if (_incoterms.contains(i)) i],
        certifications: _certList(),
      );

  Future<void> _submit() async {
    setState(() => _error = null);
    if (!(_form.currentState?.validate() ?? false)) return;
    final draft = _draft();
    final invalid = draft.validate();
    if (invalid != null) {
      setState(() => _error = context.tr(invalid));
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(freightRepositoryProvider).apply(draft);
      ref.read(freightRefreshProvider.notifier).state++;
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(context.tr('freight.apply.sent'))));
      context.pop();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = context.freightError(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('freight.apply.title'))),
      body: Form(
        key: _form,
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            if (_error != null)
              FreightErrorBox(_error!, key: const ValueKey<String>('freight_apply_error')),
            TextFormField(
              key: const ValueKey<String>('freight_company'),
              controller: _company,
              maxLength: 120,
              decoration: InputDecoration(labelText: context.tr('freight.apply.company')),
              validator: (v) {
                final k = FreightValidators.company(v ?? '');
                return k == null ? null : context.tr(k);
              },
            ),
            FreightCountryDropdown(
              label: context.tr('freight.apply.country'),
              value: _country,
              onChanged: (v) => setState(() => _country = v),
            ),
            const SizedBox(height: AppSpacing.md),
            TextFormField(
              key: const ValueKey<String>('freight_description'),
              controller: _description,
              maxLength: 1000,
              minLines: 2,
              maxLines: 4,
              decoration: InputDecoration(
                labelText: context.tr('freight.apply.description'),
                helperText: context.tr('freight.form.no_contacts'),
                helperMaxLines: 2,
              ),
            ),
            SectionHeader(title: context.tr('freight.apply.lanes')),
            for (var i = 0; i < _lanes.length; i++)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    FreightCountryDropdown(
                      key: ValueKey<String>('freight_lane_origin_${_lanes[i].id}'),
                      label: context.tr('freight.apply.lane_origin'),
                      value: _lanes[i].origin,
                      allowAny: true,
                      onChanged: (v) => setState(() => _lanes[i].origin = v),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    FreightCountryDropdown(
                      key: ValueKey<String>('freight_lane_dest_${_lanes[i].id}'),
                      label: context.tr('freight.apply.lane_dest'),
                      value: _lanes[i].destination,
                      allowAny: true,
                      onChanged: (v) => setState(() => _lanes[i].destination = v),
                    ),
                    if (_lanes.length > 1)
                      Align(
                        alignment: AlignmentDirectional.centerEnd,
                        child: TextButton.icon(
                          key: ValueKey<String>('freight_lane_remove_${_lanes[i].id}'),
                          onPressed: () => setState(() => _lanes.removeAt(i)),
                          icon: const Icon(Icons.delete_outline),
                          label: Text(context.tr('freight.apply.remove_lane')),
                        ),
                      ),
                  ],
                ),
              ),
            if (_lanes.length < 50)
              OutlinedButton.icon(
                key: const ValueKey<String>('freight_lane_add'),
                style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
                onPressed: () => setState(() => _lanes.add(_LaneRow(_laneSeq++, '*', '*'))),
                icon: const Icon(Icons.add),
                label: Text(context.tr('freight.apply.add_lane')),
              ),
            SectionHeader(title: context.tr('freight.apply.modes')),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final m in kFreightModes)
                  FilterChip(
                    key: ValueKey<String>('freight_apply_mode_$m'),
                    label: Text(freightModeName(context, m)),
                    selected: _modes.contains(m),
                    onSelected: (on) => setState(() => on ? _modes.add(m) : _modes.remove(m)),
                  ),
              ],
            ),
            SectionHeader(title: context.tr('freight.apply.incoterms')),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final i in kFreightIncoterms)
                  FilterChip(
                    key: ValueKey<String>('freight_apply_incoterm_$i'),
                    label: Text(i),
                    selected: _incoterms.contains(i),
                    onSelected: (on) =>
                        setState(() => on ? _incoterms.add(i) : _incoterms.remove(i)),
                  ),
              ],
            ),
            SectionHeader(title: context.tr('freight.apply.certs')),
            TextFormField(
              key: const ValueKey<String>('freight_certs'),
              controller: _certs,
              decoration: InputDecoration(
                labelText: context.tr('freight.apply.certs_field'),
                helperText: context.tr('freight.apply.certs_hint'),
                helperMaxLines: 2,
              ),
              validator: (v) {
                final list = _certList();
                final bad = list.length > 10 || list.any((e) => e.length < 2 || e.length > 40);
                return bad ? context.tr('freight.v.certs') : null;
              },
            ),
            const SizedBox(height: AppSpacing.xl),
            PrimaryButton(
              key: const ValueKey<String>('freight_apply_submit'),
              label: context.tr('freight.apply.submit'),
              icon: Icons.send_outlined,
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
