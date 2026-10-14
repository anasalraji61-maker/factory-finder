import 'package:factory_finder/core/models/models.dart';

/// Additive `facets` block of GET /v1/search: counts per facet value.
/// Parsing is tolerant: a facet may be a `{value: count}` map or a list of
/// `{value|key|name, count}` objects; anything else is ignored.
class SearchFacets {
  const SearchFacets({
    this.kind = const {},
    this.condition = const {},
    this.originCountry = const {},
    this.category = const {},
  });

  final Map<String, int> kind;
  final Map<String, int> condition;
  final Map<String, int> originCountry;
  final Map<String, int> category;

  bool get isEmpty =>
      kind.isEmpty && condition.isEmpty && originCountry.isEmpty && category.isEmpty;

  /// Null when [json] is not a map or carries no usable counts.
  static SearchFacets? tryParse(Object? json) {
    if (json is! Map) return null;
    final f = SearchFacets(
      kind: _counts(json['kind']),
      condition: _counts(json['condition']),
      originCountry: _counts(json['origin_country']),
      category: _counts(json['category']),
    );
    return f.isEmpty ? null : f;
  }

  /// Builds facets by counting [items] (used by the mock catalogue).
  static SearchFacets fromListings(List<Listing> items) {
    final kind = <String, int>{};
    final condition = <String, int>{};
    final origin = <String, int>{};
    final category = <String, int>{};
    void bump(Map<String, int> m, String? k) {
      if (k == null || k.isEmpty) return;
      m[k] = (m[k] ?? 0) + 1;
    }

    for (final l in items) {
      bump(kind, l.kind.json);
      bump(condition, l.condition.json);
      bump(origin, l.origin?.countryCode);
      bump(category, l.category);
    }
    return SearchFacets(
      kind: kind,
      condition: condition,
      originCountry: origin,
      category: category,
    );
  }

  static Map<String, int> _counts(Object? v) {
    final out = <String, int>{};
    if (v is Map) {
      v.forEach((k, c) {
        if (c is num) out[k.toString()] = c.toInt();
      });
    } else if (v is List) {
      for (final e in v) {
        if (e is Map) {
          final key = e['value'] ?? e['key'] ?? e['name'];
          final c = e['count'];
          if (key != null && c is num) out[key.toString()] = c.toInt();
        }
      }
    }
    return out;
  }
}

/// Search page that also carries the optional facet counts.
class ListingPage extends PageResult<Listing> {
  const ListingPage({
    required super.items,
    required super.total,
    required super.page,
    required super.pageSize,
    this.facets,
  });

  final SearchFacets? facets;
}

/// " (12)" suffix for a chip label, or '' when the count is unknown.
String facetSuffix(Map<String, int>? counts, String key) {
  final n = counts?[key];
  return n == null ? '' : ' ($n)';
}
