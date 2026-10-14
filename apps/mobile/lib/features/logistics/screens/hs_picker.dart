import 'dart:async';

import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/logistics/data/hs_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// HS code field with search-as-you-type suggestions (debounced 300 ms).
/// Writes the chosen code into [controller]; shows the duty hint as an estimate.
class HsCodePicker extends ConsumerStatefulWidget {
  const HsCodePicker({
    super.key,
    required this.controller,
    this.destinationCountry,
  });

  final TextEditingController controller;
  final String? destinationCountry;

  @override
  ConsumerState<HsCodePicker> createState() => _HsCodePickerState();
}

class _HsCodePickerState extends ConsumerState<HsCodePicker> {
  Timer? _debounce;
  int _requestId = 0;
  List<HsItem> _items = const [];
  HsItem? _selected;
  String _disclaimer = '';

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  void _onChanged(String text) {
    final selected = _selected;
    if (selected != null && selected.code != text.trim()) {
      setState(() => _selected = null);
    }
    _debounce?.cancel();
    final q = text.trim();
    if (q.length < 2) {
      _requestId++;
      setState(() {
        _items = const [];
        _selected = null;
      });
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 300), () => _search(q));
  }

  Future<void> _search(String q) async {
    final id = ++_requestId;
    try {
      final res = await ref.read(hsRepositoryProvider).search(
            q,
            destinationCountry: widget.destinationCountry,
            limit: 10,
          );
      if (!mounted || id != _requestId) return;
      setState(() {
        _items = res.items;
        _disclaimer = res.disclaimer;
      });
    } catch (_) {
      if (!mounted || id != _requestId) return;
      setState(() => _items = const []);
    }
  }

  void _select(HsItem item) {
    _debounce?.cancel();
    _requestId++;
    widget.controller.text = item.code;
    setState(() {
      _selected = item;
      _items = const [];
    });
  }

  String _pct(double v) =>
      v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(1);

  @override
  Widget build(BuildContext context) {
    final lang = Localizations.localeOf(context).languageCode;
    final selected = _selected;
    final hint = selected?.dutyHintPercent;
    final disclaimer =
        _disclaimer.isNotEmpty ? _disclaimer : context.tr('logistics.hs.disclaimer');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          controller: widget.controller,
          onChanged: _onChanged,
          decoration: InputDecoration(
            labelText: context.tr('logistics.calc.hs'),
            hintText: context.tr('logistics.hs.search_hint'),
            suffixIcon: const Icon(Icons.search),
          ),
        ),
        if (_items.isNotEmpty)
          Card(
            margin: const EdgeInsets.only(top: AppSpacing.sm),
            child: Column(
              children: [
                for (final item in _items)
                  ListTile(
                    key: ValueKey('hs-${item.code}'),
                    dense: true,
                    title: Text(
                      item.code,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w800),
                    ),
                    subtitle: Text(
                      item.description(lang),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    onTap: () => _select(item),
                  ),
              ],
            ),
          ),
        if (selected != null)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.sm),
            child: Text(
              hint == null
                  ? selected.description(lang)
                  : '${selected.description(lang)}\n${context.tr('logistics.hs.duty_hint', {'p': _pct(hint)})}',
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
        if (selected != null)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.xs),
            child: Text(
              disclaimer,
              style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
            ),
          ),
      ],
    );
  }
}
