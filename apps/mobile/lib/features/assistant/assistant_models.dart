import 'package:factory_finder/core/api/api_client.dart';

/// Ids from card refs are third-party data: only plain ids may build a route.
final RegExp _safeId = RegExp(r'^[A-Za-z0-9_.:@-]{1,64}$');

String? _str(Object? v) {
  if (v == null) return null;
  final s = v.toString();
  return s.isEmpty ? null : s;
}

/// Locale pick with fallback to the other language, then null.
String? pickLocalized(String? en, String? ar, String lang) {
  final primary = lang == 'ar' ? ar : en;
  final secondary = lang == 'ar' ? en : ar;
  if (primary != null && primary.isNotEmpty) return primary;
  if (secondary != null && secondary.isNotEmpty) return secondary;
  return null;
}

class AssistantCardColumn {
  const AssistantCardColumn({required this.id, required this.title, this.titleAr});

  final String id;
  final String title;
  final String? titleAr;

  String label(String lang) => pickLocalized(title, titleAr, lang) ?? id;

  static AssistantCardColumn? tryParse(Object? v) {
    if (v is! Map) return null;
    return AssistantCardColumn(
      id: _str(v['id']) ?? '',
      title: _str(v['title']) ?? '',
      titleAr: _str(v['title_ar']),
    );
  }
}

class AssistantCardRow {
  const AssistantCardRow({
    required this.key,
    this.label,
    this.labelAr,
    this.value,
    this.valueAr,
    this.values,
    this.highlight,
  });

  final String key;
  final String? label;
  final String? labelAr;
  final String? value;
  final String? valueAr;

  /// Comparison rows: one entry per column.
  final List<String>? values;

  /// Comparison rows: index of the better column.
  final int? highlight;

  String labelFor(String lang) => pickLocalized(label, labelAr, lang) ?? key;

  String? valueFor(String lang) => pickLocalized(value, valueAr, lang);

  static AssistantCardRow? tryParse(Object? v) {
    if (v is! Map) return null;
    final raw = v['values'];
    final hl = v['highlight'];
    return AssistantCardRow(
      key: _str(v['key']) ?? '',
      label: _str(v['label']),
      labelAr: _str(v['label_ar']),
      value: _str(v['value']),
      valueAr: _str(v['value_ar']),
      values: raw is List ? [for (final e in raw) e?.toString() ?? '-'] : null,
      highlight: hl is num ? hl.toInt() : null,
    );
  }
}

/// Where a card action leads (an existing app route).
class CardAction {
  const CardAction({required this.labelKey, required this.route, this.args = const {}});

  final String labelKey;
  final String route;
  final Map<String, String> args;
}

/// One card of an assistant answer. Unknown [type]s and missing fields are
/// tolerated: the card is still rendered from its title and rows.
class AssistantCard {
  const AssistantCard({
    required this.type,
    this.title,
    this.titleAr,
    this.severity = 'info',
    this.rows = const [],
    this.columns = const [],
    this.refs = const {},
    this.footnote,
    this.footnoteAr,
  });

  static const List<String> knownTypes = [
    'shipment_status',
    'deal_status',
    'listing_comparison',
    'hs_code',
    'notice',
  ];

  final String type;
  final String? title;
  final String? titleAr;
  final String severity;
  final List<AssistantCardRow> rows;
  final List<AssistantCardColumn> columns;
  final Map<String, String> refs;
  final String? footnote;
  final String? footnoteAr;

  bool get isKnownType => knownTypes.contains(type);

  String titleFor(String lang) => pickLocalized(title, titleAr, lang) ?? type;

  String? footnoteFor(String lang) => pickLocalized(footnote, footnoteAr, lang);

  String? _ref(String key) {
    final v = refs[key];
    return v != null && _safeId.hasMatch(v) ? v : null;
  }

  /// Deep links this card offers (only ids that look like plain ids).
  List<CardAction> get actions {
    final out = <CardAction>[];
    final shipment = _ref('shipment_id');
    if (shipment != null) {
      out.add(CardAction(
        labelKey: 'assistant.open_shipment',
        route: '/logistics/tracking/${Uri.encodeComponent(shipment)}',
      ));
    }
    final a = _ref('listing_a');
    if (a != null) {
      out.add(CardAction(
        labelKey: 'assistant.open_listing',
        route: '/listing/${Uri.encodeComponent(a)}',
        args: const {'n': '1'},
      ));
    }
    final b = _ref('listing_b');
    if (b != null) {
      out.add(CardAction(
        labelKey: 'assistant.open_listing',
        route: '/listing/${Uri.encodeComponent(b)}',
        args: const {'n': '2'},
      ));
    }
    if (type == 'deal_status' && _ref('deal_id') != null) {
      out.add(const CardAction(labelKey: 'assistant.open_deals', route: '/deals'));
    }
    final code = refs['code'];
    if (type == 'notice' && code != null && code.startsWith('auth_required')) {
      out.add(const CardAction(labelKey: 'assistant.sign_in', route: '/login'));
    }
    return out;
  }

  static AssistantCard? tryParse(Object? v) {
    if (v is! Map) return null;
    try {
      final rows = v['rows'];
      final cols = v['columns'];
      final refs = v['refs'];
      return AssistantCard(
        type: _str(v['type']) ?? 'unknown',
        title: _str(v['title']),
        titleAr: _str(v['title_ar']),
        severity: _str(v['severity']) ?? 'info',
        rows: rows is List
            ? [
                for (final r in rows)
                  if (AssistantCardRow.tryParse(r) != null) AssistantCardRow.tryParse(r)!,
              ]
            : const [],
        columns: cols is List
            ? [
                for (final c in cols)
                  if (AssistantCardColumn.tryParse(c) != null) AssistantCardColumn.tryParse(c)!,
              ]
            : const [],
        refs: refs is Map
            ? {
                for (final e in refs.entries)
                  if (e.value != null) e.key.toString(): e.value.toString(),
              }
            : const {},
        footnote: _str(v['footnote']),
        footnoteAr: _str(v['footnote_ar']),
      );
    } catch (_) {
      return null;
    }
  }
}

class AssistantAnswer {
  const AssistantAnswer({
    required this.intent,
    required this.text,
    this.cards = const [],
    this.warnings = const [],
  });

  final String intent;
  final String text;
  final List<AssistantCard> cards;
  final List<String> warnings;

  bool get textFiltered => warnings.contains('untrusted_text_filtered');

  factory AssistantAnswer.fromJson(Map<String, dynamic> j) {
    final cards = j['cards'];
    final warnings = j['warnings'];
    return AssistantAnswer(
      intent: _str(j['intent']) ?? 'help',
      text: _str(j['answer_text']) ?? '',
      cards: cards is List
          ? [
              for (final c in cards)
                if (AssistantCard.tryParse(c) != null) AssistantCard.tryParse(c)!,
            ]
          : const [],
      warnings: warnings is List ? [for (final w in warnings) w.toString()] : const [],
    );
  }
}

/// True for the per-user daily quota error (HTTP 429 / code quota_exceeded).
bool isQuotaError(Object e) =>
    e is ApiException && (e.status == 429 || e.code == 'quota_exceeded');
