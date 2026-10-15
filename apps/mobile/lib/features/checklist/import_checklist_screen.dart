import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/checklist/checklist_logic.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Offline guidance checklist of typical import documents. No network;
/// checkbox state is kept in the app key-value store.
class ImportChecklistScreen extends ConsumerStatefulWidget {
  const ImportChecklistScreen({super.key, this.countryCode, this.incoterm});

  /// Overrides the destination country (defaults to the profile destination, then IQ).
  final String? countryCode;
  final String? incoterm;

  @override
  ConsumerState<ImportChecklistScreen> createState() => _ImportChecklistScreenState();
}

class _ImportChecklistScreenState extends ConsumerState<ImportChecklistScreen> {
  late String _incoterm;
  Set<String> _checked = <String>{};
  int _loadToken = 0;

  @override
  void initState() {
    super.initState();
    final given = widget.incoterm?.toUpperCase();
    _incoterm = (given != null && kChecklistIncoterms.contains(given))
        ? given
        : kDefaultChecklistIncoterm;
    _load();
  }

  String get _country {
    final fromWidget = widget.countryCode;
    if (fromWidget != null && fromWidget.isNotEmpty) return fromWidget.toUpperCase();
    final dest = ref.read(destinationProvider)?.countryCode;
    if (dest != null && dest.isNotEmpty) return dest.toUpperCase();
    return kDefaultChecklistCountry;
  }

  Future<void> _load() async {
    final token = ++_loadToken;
    final key = checklistStorageKey(_country, _incoterm);
    String? raw;
    try {
      raw = await ref.read(keyValueStoreProvider).get(key);
    } catch (_) {
      raw = null;
    }
    if (!mounted || token != _loadToken) return;
    setState(() => _checked = decodeChecked(raw));
  }

  Future<void> _toggle(String id, bool value) async {
    final next = <String>{..._checked};
    if (value) {
      next.add(id);
    } else {
      next.remove(id);
    }
    setState(() => _checked = next);
    try {
      await ref
          .read(keyValueStoreProvider)
          .set(checklistStorageKey(_country, _incoterm), encodeChecked(next));
    } catch (_) {
      // Persistence is best-effort; the in-memory state stays correct.
    }
  }

  void _pickIncoterm(String value) {
    if (value == _incoterm) return;
    setState(() {
      _incoterm = value;
      _checked = <String>{};
    });
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final docs = checklistDocsFor(_incoterm);
    final done = docs.where((d) => _checked.contains(d.id)).length;
    final total = docs.length;
    final theme = Theme.of(context);
    final countryName = context.tr('country.$_country');

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('checklist.title'))),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.md),
        children: [
          Text(
            context.tr('checklist.destination', {'country': countryName}),
            style: theme.textTheme.titleMedium,
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(context.tr('checklist.incoterm'), style: theme.textTheme.labelLarge),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            children: [
              for (final t in kChecklistIncoterms)
                ChoiceChip(
                  key: ValueKey<String>('checklist-incoterm-$t'),
                  label: Text(t),
                  selected: t == _incoterm,
                  onSelected: (_) => _pickIncoterm(t),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Row(
            children: [
              Expanded(
                child: Text(
                  context.tr('checklist.progress', {'done': '$done', 'total': '$total'}),
                  key: const ValueKey<String>('checklist-progress-text'),
                ),
              ),
              Chip(label: Text(context.tr('checklist.guidance_badge'))),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          LinearProgressIndicator(
            key: const ValueKey<String>('checklist-progress-bar'),
            value: total == 0 ? 0 : done / total,
          ),
          const SizedBox(height: AppSpacing.md),
          for (final d in docs)
            CheckboxListTile(
              key: ValueKey<String>('checklist-item-${d.id}'),
              value: _checked.contains(d.id),
              onChanged: (v) => _toggle(d.id, v ?? false),
              controlAffinity: ListTileControlAffinity.leading,
              title: Text(context.tr('checklist.doc.${d.id}')),
              subtitle: Text(
                context.tr(d.insuranceIncluded
                    ? 'checklist.doc.${d.id}.included'
                    : 'checklist.doc.${d.id}.hint'),
              ),
            ),
          const SizedBox(height: AppSpacing.md),
          Card(
            key: const ValueKey<String>('checklist-disclaimer'),
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.md),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.info_outline),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(child: Text(context.tr('checklist.disclaimer'))),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
