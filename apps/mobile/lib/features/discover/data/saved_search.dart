import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';

/// True when [q] has anything worth saving (keywords, filters or a category).
bool canSaveSearch(ListingQuery q) =>
    q.query.trim().isNotEmpty || q.activeFilterCount > 0 || q.category != null;

/// `SearchQuery` body for POST /v1/watchlist (contracts/openapi/notifications.yaml).
/// Mirrors how [DiscoverRepository.search] maps the UI query to `/v1/search`.
Map<String, dynamic> savedSearchPayload(ListingQuery q) {
  final cat = q.category;
  final hasSlugMap = cat != null && kLiveCategorySlugs.containsKey(cat);
  final slug = cat == null ? null : (hasSlugMap ? kLiveCategorySlugs[cat] : cat);
  var keyword = q.query.trim();
  if (hasSlugMap && slug == null && keyword.isEmpty) {
    keyword = cat.replaceAll('_', ' ');
  }
  return <String, dynamic>{
    if (keyword.isNotEmpty) 'q': keyword,
    if (q.kind != null) 'kind': q.kind!.json,
    if (q.condition != null) 'condition': q.condition!.json,
    if (q.originCountry != null) 'origin_country': q.originCountry,
    if (slug != null) 'category': slug,
    if (q.maxMoq != null) 'moq_max': q.maxMoq,
    if (q.verifiedOnly) 'verified_only': true,
  };
}

/// Display title for a saved search: the keywords, else the category key.
String savedSearchTitle(ListingQuery q) {
  final t = q.query.trim();
  if (t.isNotEmpty) return t;
  final c = q.category;
  return c == null ? '' : c.replaceAll('_', ' ');
}
